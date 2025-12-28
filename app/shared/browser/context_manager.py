"""
브라우저 컨텍스트 관리 모듈

계정별 브라우저 컨텍스트의 생성, 관리, 종료를 담당합니다.

Proxy Support (2025-12-11):
- ProxyManager를 통한 Playwright 프록시 설정 지원
"""

import os
import asyncio
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from playwright.async_api import async_playwright, BrowserContext

from app.core.config import settings, logger

if TYPE_CHECKING:
    from app.services.proxy_manager import ProxyManager


class ContextManager:
    """브라우저 컨텍스트 관리자"""

    def __init__(self, proxy_manager: Optional["ProxyManager"] = None):
        """
        ContextManager 초기화

        Args:
            proxy_manager: 프록시 매니저 (없으면 프록시 미사용)
        """
        # 다중 프로필 지원: account_id별 브라우저 컨텍스트 관리
        self.browser_contexts: Dict[int, BrowserContext] = {}
        self.browser_context: Optional[BrowserContext] = None  # 하위 호환성 (기본 컨텍스트)
        self.playwright_instance = None

        # 프록시 매니저
        self._proxy_manager = proxy_manager

        # 계정별 브라우저 생성 Lock (동시 생성 방지)
        self._context_locks: Dict[int, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()  # Lock 딕셔너리 접근용 Lock

    def set_proxy_manager(self, proxy_manager: Optional["ProxyManager"]):
        """프록시 매니저 설정 (런타임 변경용)"""
        self._proxy_manager = proxy_manager
        logger.info(f"[ContextManager] 프록시 매니저 {'설정됨' if proxy_manager else '해제됨'}")

    def _get_proxy_config(self) -> Optional[Dict]:
        """Playwright용 프록시 설정 반환"""
        if self._proxy_manager and self._proxy_manager.is_available:
            proxy_config = self._proxy_manager.get_playwright_proxy()
            if proxy_config:
                logger.debug(f"[ContextManager] 프록시 사용: {proxy_config.get('server')}")
                return proxy_config
        return None

    async def initialize_browser(self) -> BrowserContext:
        """
        단일 브라우저 컨텍스트를 초기화합니다.
        (레거시 메서드 - get_or_create_context 사용 권장)
        """
        if self.browser_context is not None:
            return self.browser_context

        # 새 프로필 구조 사용: data/browser_profiles/default
        profile_dir = Path(os.path.abspath(settings.DATA_DIR)) / settings.BROWSER_PROFILES_DIR / settings.DEFAULT_PROFILE_NAME
        try:
            # 디렉토리가 없으면 생성
            if not profile_dir.exists():
                os.makedirs(profile_dir, exist_ok=True)
                logger.info(f"브라우저 프로필 디렉토리 생성: {profile_dir}")
            else:
                logger.info(f"브라우저 프로필 디렉토리 확인: {profile_dir}")

            # 디렉토리 권한 확인
            if not os.access(profile_dir, os.W_OK):
                logger.warning(f"브라우저 프로필 디렉토리에 쓰기 권한이 없습니다: {profile_dir}")
                # 임시 디렉토리 사용 시도
                temp_dir = Path(os.path.abspath(settings.USER_DATA_DIR)) / "temp_profile"
                os.makedirs(temp_dir, exist_ok=True)
                profile_dir = temp_dir
                logger.info(f"임시 프로필 디렉토리 사용: {profile_dir}")
        except Exception as e:
            logger.error(f"프로필 디렉토리 생성 실패: {str(e)}")
            raise

        try:
            # Playwright 초기화
            logger.info("Playwright 브라우저 초기화 시작")

            # 현재 이벤트 루프 확인
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Playwright 인스턴스가 없으면 새로 생성
            if self.playwright_instance is None:
                self.playwright_instance = await async_playwright().start()
                logger.info("Playwright 인스턴스 생성 완료")

            # 브라우저 컨텍스트 생성 - 설정에서 headless 모드 읽기
            self.browser_context = await self.playwright_instance.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=settings.BROWSER_HEADLESS,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-site-isolation-trials',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--window-size=1920,1080',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-site-isolation-trials',
                    '--disable-features=BlockInsecurePrivateNetworkRequests',
                    '--disable-features=CrossSiteDocumentBlockingAlways',
                    '--disable-features=CrossSiteDocumentBlockingIfIsolating',
                    '--disable-features=IsolateOrigins',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-features=NetworkService',
                    '--disable-features=NetworkServiceInProcess',
                    '--disable-features=NetworkServiceInProcess2',
                    '--disable-features=NetworkServiceInProcess3',
                    '--disable-features=NetworkServiceInProcess4',
                    '--disable-features=NetworkServiceInProcess5',
                    '--window-position=2000,1000',
                ],
                viewport={'width': 800, 'height': 600},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            # 자동화 감지 방지 스크립트 주입
            await self._bypass_automation_detection(self.browser_context)

            # default 프로필을 사용하는 계정이 있으면 browser_contexts에도 등록
            # 이렇게 해야 get_or_create_context(service_account_id)가 중복 창을 열지 않음
            from app.core.database import SessionLocal
            from app.shared.service_account import service_account_service
            db = SessionLocal()
            try:
                # default 프로필을 사용하는 서비스 계정 찾기
                accounts = service_account_service.get_all(db)
                for account in accounts:
                    if account.profile and account.profile.profile_dir == settings.DEFAULT_PROFILE_NAME:
                        self.browser_contexts[account.id] = self.browser_context
                        logger.info(f"default 프로필 컨텍스트를 계정 {account.id}에 등록")
            finally:
                db.close()

            logger.info("브라우저 컨텍스트 초기화 완료")
            return self.browser_context

        except Exception as e:
            logger.error(f"브라우저 초기화 중 오류 발생: {str(e)}", exc_info=True)
            # 오류 발생 시 리소스 정리
            if self.playwright_instance:
                try:
                    await self.playwright_instance.stop()
                except:
                    pass
                self.playwright_instance = None
            self.browser_context = None
            raise

    async def _get_context_lock(self, service_account_id: int) -> asyncio.Lock:
        """계정별 Lock을 가져오거나 생성합니다."""
        async with self._locks_lock:
            if service_account_id not in self._context_locks:
                self._context_locks[service_account_id] = asyncio.Lock()
            return self._context_locks[service_account_id]

    async def get_or_create_context(self, service_account_id: Optional[int] = None) -> BrowserContext:
        """
        계정별 브라우저 컨텍스트를 가져오거나 생성합니다.

        Args:
            service_account_id: 계정 ID (None이면 기본 계정 사용)

        Returns:
            BrowserContext: 계정에 해당하는 브라우저 컨텍스트
        """
        # account_id가 None이면 기본 계정(id=1) 사용
        if service_account_id is None:
            from app.core.database import SessionLocal
            from app.shared.browser_profile import browser_profile_service
            from app.shared.service_account import service_account_service
            db = SessionLocal()
            try:
                # default 프로필을 사용하는 서비스 계정 찾기
                default_profile = browser_profile_service.get_default_profile(db)
                if default_profile:
                    accounts = service_account_service.get_by_profile_id(db, default_profile.id)
                    service_account_id = accounts[0].id if accounts else 1
                else:
                    service_account_id = 1  # fallback
            finally:
                db.close()

        # 계정별 Lock 획득 (동시 브라우저 생성 방지)
        context_lock = await self._get_context_lock(service_account_id)

        async with context_lock:
            # 이미 존재하면 유효성 확인 후 반환
            if service_account_id in self.browser_contexts:
                context = self.browser_contexts[service_account_id]
                # 컨텍스트가 닫혔는지 확인 (더 엄격한 검사)
                context_valid = False
                try:
                    pages = context.pages  # 유효성 확인
                    # 실제로 페이지에 접근 가능한지도 확인
                    if len(pages) > 0:
                        try:
                            _ = pages[0].url
                            context_valid = True
                        except Exception as e:
                            logger.warning(f"페이지 접근 실패 (service_account_id={service_account_id}): {e}")
                    else:
                        # 페이지가 없으면 브라우저가 살아있는지 직접 확인
                        try:
                            browser = context.browser
                            if browser and browser.is_connected():
                                context_valid = True
                            else:
                                logger.warning(f"브라우저 연결 끊김 (service_account_id={service_account_id})")
                        except Exception as e:
                            logger.warning(f"브라우저 연결 상태 확인 실패 (service_account_id={service_account_id}): {e}")
                except Exception as e:
                    logger.warning(f"브라우저 컨텍스트 유효성 검사 실패 (service_account_id={service_account_id}): {e}")

                if context_valid:
                    logger.debug(f"기존 브라우저 컨텍스트 재사용 (service_account_id={service_account_id})")
                    return context
                else:
                    # 컨텍스트가 닫혔으면 딕셔너리에서 제거
                    logger.info(f"브라우저 컨텍스트가 닫혀있어 새로 생성합니다 (service_account_id={service_account_id})")
                    try:
                        del self.browser_contexts[service_account_id]
                    except Exception:
                        pass

            # 새로 생성
            logger.info(f"새 브라우저 컨텍스트 생성 중 (service_account_id={service_account_id})")
            context = await self._create_browser_context(service_account_id)
            self.browser_contexts[service_account_id] = context

            # 첫 번째 컨텍스트는 하위 호환을 위해 browser_context에도 저장
            if self.browser_context is None:
                self.browser_context = context
                logger.info("기본 브라우저 컨텍스트 설정 완료")

            return context

    async def _create_browser_context(self, service_account_id: int) -> BrowserContext:
        """
        계정별 브라우저 컨텍스트를 생성합니다.

        Args:
            service_account_id: 계정 ID

        Returns:
            BrowserContext: 생성된 브라우저 컨텍스트
        """
        from app.core.database import SessionLocal
        from app.shared.service_account import service_account_service

        db = SessionLocal()
        try:
            account = service_account_service.get_by_id(db, service_account_id)
            if not account or not account.profile:
                raise ValueError(f"ServiceAccount {service_account_id} not found or has no profile")

            profile_path = Path(account.profile.profile_path)

            # 프로필 디렉토리 생성
            if not profile_path.exists():
                profile_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"프로필 디렉토리 생성: {profile_path}")

            # Playwright 인스턴스 초기화
            if self.playwright_instance is None:
                self.playwright_instance = await async_playwright().start()
                logger.info("Playwright 인스턴스 생성 완료")

            # 프록시 설정 가져오기
            proxy_config = self._get_proxy_config()

            # 브라우저 컨텍스트 생성 (손상된 인스턴스 복구 지원)
            try:
                context = await self.playwright_instance.chromium.launch_persistent_context(
                    user_data_dir=str(profile_path),
                    headless=settings.BROWSER_HEADLESS,
                    proxy=proxy_config,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-site-isolation-trials',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--disable-gpu',
                        '--window-size=800,600',
                        '--window-position=2000,1000',
                        '--disable-web-security',
                        '--disable-features=BlockInsecurePrivateNetworkRequests',
                    ],
                    viewport={'width': 800, 'height': 600},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
            except Exception as e:
                # Playwright 인스턴스가 손상된 경우 재생성 후 재시도
                if "closed" in str(e).lower():
                    logger.warning(f"Playwright 인스턴스 손상 감지, 재생성 중: {e}")
                    try:
                        await self.playwright_instance.stop()
                    except Exception:
                        pass
                    self.playwright_instance = await async_playwright().start()
                    logger.info("Playwright 인스턴스 재생성 완료")

                    context = await self.playwright_instance.chromium.launch_persistent_context(
                        user_data_dir=str(profile_path),
                        headless=settings.BROWSER_HEADLESS,
                        proxy=proxy_config,
                        args=[
                            '--disable-blink-features=AutomationControlled',
                            '--disable-features=IsolateOrigins,site-per-process',
                            '--disable-site-isolation-trials',
                            '--no-sandbox',
                            '--disable-setuid-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-accelerated-2d-canvas',
                            '--disable-gpu',
                            '--window-size=800,600',
                            '--window-position=2000,1000',
                            '--disable-web-security',
                            '--disable-features=BlockInsecurePrivateNetworkRequests',
                        ],
                        viewport={'width': 800, 'height': 600},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    )
                else:
                    raise

            # 자동화 감지 방지
            await self._bypass_automation_detection(context)

            proxy_info = f", proxy={proxy_config.get('server')}" if proxy_config else ""
            logger.info(f"브라우저 컨텍스트 생성 완료 (service_account_id={service_account_id}, profile={account.profile_dir}{proxy_info})")

            # 마지막 사용 시간 업데이트
            service_account_service.update_last_used(db, service_account_id)

            return context

        finally:
            db.close()

    async def _create_browser_context_visible(self, service_account_id: int) -> BrowserContext:
        """
        계정별 브라우저 컨텍스트를 headless=False로 생성합니다.
        수동 로그인용으로 사용합니다.

        Args:
            service_account_id: 계정 ID

        Returns:
            BrowserContext: 생성된 브라우저 컨텍스트
        """
        from app.core.database import SessionLocal
        from app.shared.service_account import service_account_service

        # 이미 존재하면 유효성 확인 후 반환
        if service_account_id in self.browser_contexts:
            context = self.browser_contexts[service_account_id]
            context_valid = False
            try:
                pages = context.pages  # 유효성 확인
                # 페이지가 있으면 URL에 접근해서 실제로 살아있는지 확인
                if len(pages) > 0:
                    try:
                        _ = pages[0].url
                        context_valid = True
                    except Exception as e:
                        logger.warning(f"페이지 접근 실패 (service_account_id={service_account_id}): {e}")
                else:
                    # 페이지가 없으면 브라우저 연결 상태 확인
                    try:
                        browser = context.browser
                        if browser and browser.is_connected():
                            context_valid = True
                        else:
                            logger.warning(f"브라우저 연결 끊김 (service_account_id={service_account_id})")
                    except Exception as e:
                        logger.warning(f"브라우저 연결 상태 확인 실패 (service_account_id={service_account_id}): {e}")
            except Exception as e:
                logger.warning(f"브라우저 컨텍스트 유효성 검사 실패 (service_account_id={service_account_id}): {e}")

            if context_valid:
                logger.debug(f"기존 브라우저 컨텍스트 재사용 (service_account_id={service_account_id})")
                return context
            else:
                logger.info(f"브라우저 컨텍스트가 닫혀있어 새로 생성합니다 (service_account_id={service_account_id})")
                try:
                    del self.browser_contexts[service_account_id]
                except Exception:
                    pass

        db = SessionLocal()
        try:
            account = service_account_service.get_by_id(db, service_account_id)
            if not account or not account.profile:
                raise ValueError(f"ServiceAccount {service_account_id} not found or has no profile")

            profile_path = Path(account.profile.profile_path)

            # 프로필 디렉토리 생성
            if not profile_path.exists():
                profile_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"프로필 디렉토리 생성: {profile_path}")

            # Playwright 인스턴스 초기화
            if self.playwright_instance is None:
                self.playwright_instance = await async_playwright().start()
                logger.info("Playwright 인스턴스 생성 완료")

            # 브라우저 컨텍스트 생성 (headless=False 강제)
            context = await self.playwright_instance.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-site-isolation-trials',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--window-size=1280,800',
                    '--window-position=100,100',
                ],
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            # 자동화 감지 방지
            await self._bypass_automation_detection(context)

            logger.info(f"브라우저 컨텍스트 생성 완료 (service_account_id={service_account_id}, profile={account.profile_dir}, headless=False)")

            # 컨텍스트 저장
            self.browser_contexts[service_account_id] = context

            # 마지막 사용 시간 업데이트
            account_service.update_last_used(db, service_account_id)

            return context

        finally:
            db.close()

    async def close_context(self, service_account_id: int):
        """
        특정 계정의 브라우저 컨텍스트를 닫습니다.

        Args:
            service_account_id: 계정 ID
        """
        if service_account_id in self.browser_contexts:
            try:
                context = self.browser_contexts[service_account_id]
                await context.close()
                del self.browser_contexts[service_account_id]
                logger.info(f"브라우저 컨텍스트 종료 완료 (service_account_id={service_account_id})")
            except Exception as e:
                logger.error(f"브라우저 컨텍스트 종료 실패 (service_account_id={service_account_id}): {str(e)}")

    async def close_all_contexts(self):
        """모든 브라우저 컨텍스트를 닫습니다."""
        for service_account_id in list(self.browser_contexts.keys()):
            await self.close_context(service_account_id)

        if self.playwright_instance:
            try:
                await self.playwright_instance.stop()
                self.playwright_instance = None
                logger.info("Playwright 인스턴스 종료 완료")
            except Exception as e:
                logger.error(f"Playwright 인스턴스 종료 실패: {str(e)}")

    async def _bypass_automation_detection(self, context: BrowserContext):
        """자동화 감지를 우회하기 위한 스크립트를 주입합니다."""
        await context.add_init_script(self._get_anti_detection_script())

    @staticmethod
    def _get_anti_detection_script() -> str:
        """자동화 감지 우회 JavaScript 스크립트를 반환합니다."""
        return """
        // 1. navigator.webdriver 완전 제거
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        // 프로토타입에서도 제거 시도
        try {
            delete Object.getPrototypeOf(navigator).webdriver;
        } catch (e) {}

        // 2. window.chrome 객체 스푸핑 (일반 Chrome처럼 보이게)
        if (!window.chrome) {
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
        }

        // 3. navigator.permissions.query 스푸핑
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // 4. navigator.plugins 실제 플러그인 형태로 개선
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const plugins = [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                ];
                plugins.length = 3;
                return plugins;
            }
        });

        // 5. navigator.languages 한국어 우선 설정
        Object.defineProperty(navigator, 'languages', {
            get: () => ['ko-KR', 'ko', 'en-US', 'en']
        });

        // 6. navigator.maxTouchPoints 설정
        Object.defineProperty(navigator, 'maxTouchPoints', {
            get: () => 1
        });
        """

    async def move_window_to_center(self) -> bool:
        """브라우저 창을 화면 중앙으로 이동합니다."""
        try:
            if not self.browser_context:
                logger.warning("브라우저 컨텍스트가 없어 창 이동 불가")
                return False

            pages = self.browser_context.pages
            if not pages:
                logger.warning("열린 페이지가 없어 창 이동 불가")
                return False

            page = pages[0]
            cdp = await page.context.new_cdp_session(page)

            window_info = await cdp.send("Browser.getWindowForTarget")
            window_id = window_info.get("windowId")

            if window_id:
                center_x = 560
                center_y = 240

                await cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {
                        "left": center_x,
                        "top": center_y,
                        "width": 800,
                        "height": 600,
                        "windowState": "normal"
                    }
                })
                logger.info(f"브라우저 창을 화면 중앙으로 이동 (x={center_x}, y={center_y})")
                return True

            return False
        except Exception as e:
            logger.error(f"창 위치 이동 실패: {e}")
            return False

    async def move_window_to_corner(self) -> bool:
        """브라우저 창을 화면 우측 하단 구석으로 이동합니다."""
        try:
            if not self.browser_context:
                logger.warning("브라우저 컨텍스트가 없어 창 이동 불가")
                return False

            pages = self.browser_context.pages
            if not pages:
                logger.warning("열린 페이지가 없어 창 이동 불가")
                return False

            page = pages[0]
            cdp = await page.context.new_cdp_session(page)

            window_info = await cdp.send("Browser.getWindowForTarget")
            window_id = window_info.get("windowId")

            if window_id:
                corner_x = 2000
                corner_y = 1000

                await cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {
                        "left": corner_x,
                        "top": corner_y,
                        "width": 800,
                        "height": 600,
                        "windowState": "normal"
                    }
                })
                logger.info(f"브라우저 창을 구석으로 이동 (x={corner_x}, y={corner_y})")
                return True

            return False
        except Exception as e:
            logger.error(f"창 위치 이동 실패: {e}")
            return False

    async def take_screenshot(self, filename_prefix: str = "screenshot") -> Optional[str]:
        """
        현재 브라우저 페이지의 스크린샷을 저장합니다.

        Args:
            filename_prefix: 파일명 접두사 (타임스탬프가 자동 추가됨)

        Returns:
            저장된 파일 경로, 실패 시 None
        """
        try:
            if not self.browser_context:
                logger.warning("브라우저 컨텍스트가 없어 스크린샷 불가")
                return None

            pages = self.browser_context.pages
            if not pages:
                logger.warning("열린 페이지가 없어 스크린샷 불가")
                return None

            # 스크린샷 저장 디렉토리 생성
            screenshot_dir = Path(settings.BASE_DIR) / "logs" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            # 타임스탬프 포함 파일명 생성
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 밀리초까지
            filename = f"{filename_prefix}_{timestamp}.png"
            filepath = screenshot_dir / filename

            # 첫 번째 페이지 스크린샷 (활성 탭)
            page = pages[0]
            await page.screenshot(path=str(filepath), full_page=False)

            logger.info(f"스크린샷 저장됨: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"스크린샷 저장 실패: {e}")
            return None

    async def take_screenshots_all_pages(self, filename_prefix: str = "screenshot") -> list[str]:
        """
        모든 열린 페이지의 스크린샷을 저장합니다.

        Args:
            filename_prefix: 파일명 접두사

        Returns:
            저장된 파일 경로 목록
        """
        saved_paths = []
        try:
            if not self.browser_context:
                logger.warning("브라우저 컨텍스트가 없어 스크린샷 불가")
                return saved_paths

            pages = self.browser_context.pages
            if not pages:
                logger.warning("열린 페이지가 없어 스크린샷 불가")
                return saved_paths

            # 스크린샷 저장 디렉토리 생성
            screenshot_dir = Path(settings.BASE_DIR) / "logs" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

            for idx, page in enumerate(pages):
                try:
                    filename = f"{filename_prefix}_{timestamp}_tab{idx}.png"
                    filepath = screenshot_dir / filename
                    await page.screenshot(path=str(filepath), full_page=False)
                    saved_paths.append(str(filepath))
                    logger.info(f"스크린샷 저장됨: {filepath}")
                except Exception as page_err:
                    logger.warning(f"탭 {idx} 스크린샷 실패: {page_err}")

            return saved_paths
        except Exception as e:
            logger.error(f"스크린샷 저장 실패: {e}")
            return saved_paths
