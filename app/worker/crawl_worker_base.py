"""
크롤링 워커 기반 클래스.

Instagram/Universal 크롤링 워커들이 공유하는 공통 로직을 제공합니다.
- 브라우저 컨텍스트/탭 풀 관리
- 브라우저 Lock 정리
- 요청 정리
- WorkerStatus 연동

BaseWorker를 상속하며, 크롤링 특화 기능을 추가합니다.
"""
import asyncio
import sys
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Optional
from abc import abstractmethod

from playwright.async_api import Page

from app.shared.worker.base_worker import BaseWorker
from app.shared.browser.browser_manager import BrowserManager
from app.database import SessionLocal
from app.modules.instagram.services.worker_status_service import WorkerStatusService

logger = logging.getLogger(__name__)


class CrawlWorkerBase(BaseWorker):
    """크롤링 워커 기반 클래스.

    브라우저 관리, 요청 정리, 상태 추적 등 공통 기능을 제공합니다.
    서브클래스는 _main_loop_iteration()과 _get_loop_interval()을 구현해야 합니다.

    Attributes:
        browser_manager: 브라우저 중앙 관리자
        worker_type: 워커 타입 (scheduled, ondemand 등)
    """

    # 브라우저 closed 에러 키워드들
    BROWSER_CLOSED_KEYWORDS = [
        "Target page, context or browser has been closed",
        "browser has been closed",
        "context has been closed",
        "page has been closed",
        "Target closed",
    ]

    def __init__(
        self,
        name: str,
        worker_type: str = "crawl",
        browser_manager: Optional[BrowserManager] = None
    ):
        """CrawlWorkerBase 초기화.

        Args:
            name: 워커 이름
            worker_type: 워커 타입 (scheduled, ondemand 등)
            browser_manager: 외부에서 주입받을 BrowserManager (None이면 자체 생성)
        """
        # BrowserManager: 외부 주입 또는 자체 생성
        if browser_manager is None:
            browser_manager = BrowserManager()
            self._owns_browser = True  # 자체 생성 시 cleanup 책임
        else:
            self._owns_browser = False  # 외부 주입 시 cleanup 책임 없음

        super().__init__(name, browser_manager)

        self.worker_type = worker_type
        self._browser_initialized = False

    async def _initialize(self):
        """BaseWorker의 _initialize 오버라이드.

        _on_start()를 호출하여 초기화 작업을 수행합니다.
        """
        await self._on_start()

    async def _on_start(self):
        """시작 시 초기화 훅.

        오래된 요청 정리 및 브라우저 Lock 정리를 수행합니다.
        """
        # 오래된 processing 요청 정리 (좀비 요청 방지)
        self._cleanup_stale_requests()

        # 기존 브라우저 프로필 Lock 정리 (비정상 종료 후 재시작 시)
        self._cleanup_stale_browser_locks()

    async def _on_stop(self):
        """종료 시 정리 훅."""
        # 브라우저 매니저 정리 (자체 생성한 경우에만)
        if self._owns_browser and self.browser and self.browser.is_initialized:
            try:
                await self.browser.cleanup()
                logger.info(f"[{self.name}] 브라우저 매니저 정리 완료")
            except Exception as e:
                logger.error(f"[{self.name}] 브라우저 매니저 정리 오류: {e}")

    async def _ensure_browser_initialized(self):
        """브라우저 초기화를 보장합니다 (lazy initialization)."""
        if not self._browser_initialized and self.browser:
            await self.browser.initialize()
            self._browser_initialized = True
            logger.info(f"[{self.name}] 브라우저 매니저 초기화 완료")

    async def execute_with_tab(
        self,
        callback,
        service_account_id: Optional[int] = None,
        **kwargs
    ):
        """탭을 사용하여 콜백을 실행합니다.

        BrowserManager의 execute_with_tab을 래핑하여 lazy initialization을 제공합니다.

        Args:
            callback: 탭(Page)을 첫 번째 인자로 받는 async 함수
            service_account_id: 브라우저 프로필 ID
            **kwargs: 콜백에 전달할 추가 인자

        Returns:
            콜백 실행 결과
        """
        await self._ensure_browser_initialized()
        return await self.browser.execute_with_tab(
            callback=callback,
            service_account_id=service_account_id,
            **kwargs
        )

    def is_browser_closed_error(self, error: Exception) -> bool:
        """브라우저 관련 오류인지 확인합니다.

        Args:
            error: 예외 객체

        Returns:
            브라우저 closed 관련 오류 여부
        """
        error_str = str(error)
        return any(keyword in error_str for keyword in self.BROWSER_CLOSED_KEYWORDS)

    # ========== Worker Status 관련 (DB 연동) ==========

    def _register_worker_status(self):
        """워커 상태를 DB에 등록합니다.

        BaseWorker의 메서드를 오버라이드하여 WorkerStatusService 사용.
        """
        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            status = service.register_worker()
            self.worker_id = status.worker_id
            logger.info(f"[{self.name}] 워커 상태 등록 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"[{self.name}] 워커 상태 등록 실패: {e}")
        finally:
            db.close()

    def _update_heartbeat(self):
        """워커 heartbeat를 업데이트합니다.

        BaseWorker의 메서드를 오버라이드하여 WorkerStatusService 사용.
        """
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            service.update_heartbeat(self.worker_id)
        except Exception as e:
            logger.warning(f"[{self.name}] Heartbeat 업데이트 실패: {e}")
        finally:
            db.close()

    def _update_worker_state(self, state: str, account: str = None, run_id: int = None):
        """워커 상태를 업데이트합니다.

        Args:
            state: 워커 상태 (idle, crawling, processing 등)
            account: 계정 이름
            run_id: 실행 ID
        """
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            service.update_state(self.worker_id, state, account, run_id)
        except Exception as e:
            logger.warning(f"[{self.name}] 워커 상태 업데이트 실패: {e}")
        finally:
            db.close()

    def _mark_worker_dead(self):
        """워커를 종료 상태로 표시합니다.

        BaseWorker의 메서드를 오버라이드하여 WorkerStatusService 사용.
        """
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            service.mark_dead(self.worker_id)
            logger.info(f"[{self.name}] 워커 종료 상태 표시 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"[{self.name}] 워커 종료 상태 표시 실패: {e}")
        finally:
            db.close()

    # ========== 정리 메서드 ==========

    @abstractmethod
    def _cleanup_stale_requests(self):
        """오래된 processing 상태 요청 정리.

        서브클래스에서 구현해야 합니다.
        """
        pass

    def _cleanup_stale_browser_locks(self):
        """비정상 종료된 브라우저의 Lock 파일 및 프로세스 정리."""
        from app.config import settings

        profile_base = Path(settings.DATA_DIR) / settings.BROWSER_PROFILES_DIR

        if not profile_base.exists():
            return

        try:
            # 1. 해당 프로필을 사용하는 모든 Chromium 프로세스 종료
            killed_count = self._kill_chromium_for_profiles(profile_base)
            if killed_count > 0:
                logger.info(f"[{self.name}] 기존 Chromium 프로세스 {killed_count}개 종료됨")
                import time
                time.sleep(1)

            # 2. Lock 파일 정리
            for profile_dir in profile_base.iterdir():
                if not profile_dir.is_dir():
                    continue
                self._remove_lock_files(profile_dir)

        except Exception as e:
            logger.warning(f"[{self.name}] 브라우저 정리 중 오류 (무시): {e}")

    def _kill_chromium_for_profiles(self, profile_base: Path) -> int:
        """프로필 디렉토리를 사용하는 Chromium 프로세스 종료."""
        killed_count = 0

        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/V"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'chrome.exe' in line.lower():
                            try:
                                parts = line.split(',')
                                if len(parts) > 1:
                                    pid_str = parts[1].strip('"')
                                    if pid_str.isdigit():
                                        pid = int(pid_str)
                                        if self._is_chromium_using_profile(pid, profile_base):
                                            logger.info(f"[{self.name}] Chromium 프로세스 종료: PID {pid}")
                                            subprocess.run(
                                                ["taskkill", "/F", "/PID", str(pid)],
                                                capture_output=True,
                                                timeout=5
                                            )
                                            killed_count += 1
                            except (ValueError, IndexError):
                                continue
            else:
                subprocess.run(
                    ["pkill", "-f", str(profile_base)],
                    capture_output=True,
                    timeout=5
                )
                killed_count = 1

        except subprocess.TimeoutExpired:
            logger.warning(f"[{self.name}] Chromium 종료 타임아웃")
        except Exception as e:
            logger.warning(f"[{self.name}] Chromium 종료 오류: {e}")

        return killed_count

    def _is_chromium_using_profile(self, pid: int, profile_base: Path) -> bool:
        """특정 PID의 Chromium이 해당 프로필 경로를 사용하는지 확인."""
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    cmd_line = result.stdout.lower()
                    return 'browser_profiles' in cmd_line or 'ms-playwright' in cmd_line
            else:
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    return str(profile_base) in result.stdout
        except Exception:
            pass

        return False

    def _remove_lock_files(self, profile_dir: Path):
        """프로필 디렉토리의 Lock 파일들 제거."""
        lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]

        for lock_name in lock_files:
            lock_path = profile_dir / lock_name
            if lock_path.exists():
                try:
                    if lock_path.is_file() or lock_path.is_symlink():
                        lock_path.unlink()
                    else:
                        shutil.rmtree(lock_path, ignore_errors=True)
                    logger.debug(f"[{self.name}] Lock 파일 삭제: {lock_path}")
                except Exception as e:
                    logger.warning(f"[{self.name}] Lock 파일 삭제 실패 ({lock_path}): {e}")

    def get_status(self) -> dict:
        """워커 상태 정보 반환.

        BaseWorker의 상태에 브라우저 상태를 추가합니다.

        Returns:
            dict: 상태 정보
        """
        status = super().get_status()
        status["worker_type"] = self.worker_type
        status["browser_initialized"] = self._browser_initialized

        if self.browser:
            status["browser_status"] = self.browser.get_status()

        return status
