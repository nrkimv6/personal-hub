"""
비디오 다운로드 워커.

YouTube/Vimeo/Instagram Reel 등 비디오 다운로드 요청을 처리합니다:
- pending 상태의 VideoDownload 요청을 폴링
- python-youtube-stream-download 프로젝트의 함수를 호출하여 다운로드
- 진행률 및 완료/실패 상태 업데이트

실행 방법:
    python -m app.worker.video_download_worker
"""
import os
import sys
import asyncio
import logging
import re
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional

# python-youtube-stream-download 프로젝트 경로 추가
DOWNLOADER_PROJECT_PATH = r"D:\work\project\tools\python-youtube-stream-download"
if DOWNLOADER_PROJECT_PATH not in sys.path:
    sys.path.insert(0, DOWNLOADER_PROJECT_PATH)

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.models import VideoDownload
from app.services.video_download_service import VideoDownloadService
from app.config import settings

logger = logging.getLogger(__name__)

# 기본 다운로드 경로
DEFAULT_OUTPUT_DIR = r"D:\Videos\contents\download"


class VideoDownloadWorker(BaseWorker):
    """비디오 다운로드 워커.

    VideoDownload 테이블의 pending 요청을 처리합니다.
    브라우저가 필요 없으므로 BaseWorker를 직접 상속합니다.

    Attributes:
        output_dir: 다운로드 파일 저장 디렉토리
        max_concurrent: 동시 다운로드 최대 개수
    """

    def __init__(
        self,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        max_concurrent: int = 2
    ):
        """VideoDownloadWorker 초기화.

        Args:
            output_dir: 다운로드 파일 저장 디렉토리
            max_concurrent: 동시 다운로드 최대 개수
        """
        super().__init__(name="video_download_worker")
        self.output_dir = output_dir
        self.max_concurrent = max_concurrent
        self._current_process: Optional[asyncio.subprocess.Process] = None

        # 출력 디렉토리 생성
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환."""
        return 2.0  # 2초마다 체크

    async def _initialize(self):
        """시작 시 초기화."""
        # 오래된 processing 요청 정리
        self._cleanup_stale_requests()
        logger.info(f"[{self.name}] 출력 디렉토리: {self.output_dir}")

    def _cleanup_stale_requests(self):
        """오래된 processing 상태 요청 정리."""
        db = SessionLocal()
        try:
            service = VideoDownloadService(db)
            cleaned = service.cleanup_stale_processing(timeout_minutes=120)
            if cleaned > 0:
                logger.info(f"[{self.name}] {cleaned}개의 오래된 processing 요청 정리 완료")
        except Exception as e:
            logger.error(f"[{self.name}] Stale request 정리 오류: {e}")
        finally:
            db.close()

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클."""
        # 완료된 태스크 정리
        self._cleanup_completed_tasks()

        # 현재 실행 중인 태스크 수 확인
        active_count = len(self._running_tasks)
        if active_count >= self.max_concurrent:
            return  # 동시 실행 제한

        # Pending 요청 디스패치
        await self._dispatch_pending_requests(self.max_concurrent - active_count)

    async def _dispatch_pending_requests(self, limit: int):
        """Pending 요청을 백그라운드 태스크로 디스패치."""
        db = SessionLocal()
        try:
            service = VideoDownloadService(db)
            pending_list = service.get_pending_requests(limit=limit)

            for pending in pending_list:
                task_name = f"download_{pending.id}"
                if self._is_task_running(task_name):
                    continue

                # 요청을 picked 상태로 변경
                picked = service.pick_request(pending.id, self.name)
                if not picked:
                    continue  # 다른 워커가 먼저 가져감

                self._create_task(
                    self._execute_download(picked.id),
                    task_name
                )
                logger.info(
                    f"[{self.name}] 다운로드 태스크 시작: id={picked.id}, "
                    f"type={picked.download_type}, url={picked.url[:50]}..."
                )

        except Exception as e:
            self._log_worker_error("Pending 요청 디스패치", e)
        finally:
            db.close()

    async def _execute_download(self, request_id: int):
        """다운로드 실행.

        Args:
            request_id: VideoDownload 요청 ID
        """
        db = SessionLocal()
        try:
            service = VideoDownloadService(db)
            request = service.get_request_by_id(request_id)

            if not request:
                logger.warning(f"[{self.name}] 요청을 찾을 수 없음: id={request_id}")
                return

            # processing 상태로 변경 (commit 발생하므로 반환된 객체 사용)
            request = service.start_processing(request_id) or request

            logger.info(
                f"[{self.name}] 다운로드 시작: id={request_id}, "
                f"type={request.download_type}, url={request.url}, "
                f"output_filename={request.output_filename}"
            )

            # 다운로드 타입에 따라 분기
            if request.download_type == VideoDownload.TYPE_VIMEO:
                result = await self._download_vimeo(request)
            elif request.download_type == VideoDownload.TYPE_INSTAGRAM:
                result = await self._download_instagram(request)
            elif request.download_type == VideoDownload.TYPE_YOUTUBE_STREAM:
                result = await self._download_youtube_stream(request)
            else:  # youtube
                result = await self._download_youtube(request)

            if result.get("success"):
                service.complete_request(
                    request_id,
                    output_path=result.get("output_path", ""),
                    file_size=result.get("file_size"),
                    title=result.get("title")
                )
                logger.info(
                    f"[{self.name}] 다운로드 완료: id={request_id}, "
                    f"path={result.get('output_path')}"
                )
            else:
                service.fail_request(
                    request_id,
                    error_message=result.get("error", "알 수 없는 오류")
                )
                logger.warning(
                    f"[{self.name}] 다운로드 실패: id={request_id}, "
                    f"error={result.get('error')}"
                )

        except Exception as e:
            logger.error(
                f"[{self.name}] 다운로드 예외: id={request_id}, error={e}",
                exc_info=True
            )
            try:
                service = VideoDownloadService(db)
                service.fail_request(request_id, str(e))
            except Exception:
                pass
        finally:
            db.close()

    async def _download_youtube(self, request: VideoDownload) -> dict:
        """YouTube 일반 영상 다운로드.

        Args:
            request: VideoDownload 요청 객체

        Returns:
            결과 딕셔너리 {success, output_path, file_size, title, error}
        """
        try:
            from download import download_video_from_start
            from convert import convert_and_rename

            current_datetime = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base = os.path.join(self.output_dir, f'ts_{current_datetime}')

            # 동기 함수를 비동기로 실행
            downloaded_file = await asyncio.to_thread(
                download_video_from_start,
                request.url,
                output_base
            )

            if not downloaded_file or not os.path.exists(downloaded_file):
                return {"success": False, "error": "다운로드된 파일을 찾을 수 없음"}

            # 변환 실행
            await asyncio.to_thread(
                convert_and_rename,
                downloaded_file,
                f'video_{current_datetime}',
                remove_ts_after_conversion=True,
                naming_option='id_title_if_av'
            )

            # 변환된 파일 찾기
            output_path = self._find_converted_file(self.output_dir, current_datetime)
            if output_path:
                file_size = os.path.getsize(output_path)
                title = self._extract_title_from_filename(output_path)
                return {
                    "success": True,
                    "output_path": output_path,
                    "file_size": file_size,
                    "title": title
                }

            return {"success": True, "output_path": downloaded_file}

        except Exception as e:
            logger.error(f"[{self.name}] YouTube 다운로드 오류: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _download_youtube_stream(self, request: VideoDownload) -> dict:
        """YouTube 라이브 스트림 다운로드.

        Args:
            request: VideoDownload 요청 객체

        Returns:
            결과 딕셔너리 {success, output_path, file_size, title, error}
        """
        try:
            from download import download_live_stream
            from convert import convert_and_rename

            current_datetime = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base = os.path.join(self.output_dir, f'ts_{current_datetime}')

            # 동기 함수를 비동기로 실행
            downloaded_file = await asyncio.to_thread(
                download_live_stream,
                request.url,
                output_base,
                "1"  # bv*+ba 옵션
            )

            if not downloaded_file or not os.path.exists(downloaded_file):
                return {"success": False, "error": "다운로드된 파일을 찾을 수 없음"}

            # 변환 실행
            await asyncio.to_thread(
                convert_and_rename,
                downloaded_file,
                f'video_{current_datetime}',
                remove_ts_after_conversion=True,
                naming_option='id_title_if_av'
            )

            # 변환된 파일 찾기
            output_path = self._find_converted_file(self.output_dir, current_datetime)
            if output_path:
                file_size = os.path.getsize(output_path)
                title = self._extract_title_from_filename(output_path)
                return {
                    "success": True,
                    "output_path": output_path,
                    "file_size": file_size,
                    "title": title
                }

            return {"success": True, "output_path": downloaded_file}

        except Exception as e:
            logger.error(f"[{self.name}] YouTube Stream 다운로드 오류: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _download_vimeo(self, request: VideoDownload) -> dict:
        """Vimeo 다운로드 (yt-dlp 직접 호출, 진행률 로깅).

        Args:
            request: VideoDownload 요청 객체

        Returns:
            결과 딕셔너리 {success, output_path, file_size, title, error}
        """
        try:
            current_datetime = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 사용자 지정 파일명이 있으면 사용, 없으면 기본 패턴
            if request.output_filename:
                output_filename = os.path.join(self.output_dir, request.output_filename)
            else:
                output_filename = os.path.join(self.output_dir, f'vimeo_{current_datetime}')

            return await self._download_with_yt_dlp(
                request=request,
                output_filename=output_filename,
                referer=request.embedding_url,
            )

        except Exception as e:
            logger.error(f"[{self.name}] Vimeo 다운로드 오류: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _download_instagram(self, request: VideoDownload) -> dict:
        """Instagram Reel 다운로드 (yt-dlp 직접 호출)."""
        try:
            current_datetime = datetime.now().strftime("%Y%m%d_%H%M%S")
            if request.output_filename:
                output_filename = os.path.join(self.output_dir, request.output_filename)
            else:
                output_filename = os.path.join(self.output_dir, f'instagram_{current_datetime}')

            return await self._download_with_yt_dlp(
                request=request,
                output_filename=output_filename,
            )
        except Exception as e:
            logger.error(f"[{self.name}] Instagram 다운로드 오류: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _download_with_yt_dlp(
        self,
        request: VideoDownload,
        output_filename: str,
        referer: Optional[str] = None,
    ) -> dict:
        """yt-dlp 기반 다운로드 공통 처리."""
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--progress',
            '--newline',
            '--merge-output-format', 'mp4',
            '-o', f'{output_filename}.%(ext)s',
        ]

        if referer:
            cmd.extend(['--referer', referer])

        cmd.append(request.url)

        logger.info(f"[{self.name}] yt-dlp 시작: type={request.download_type}, url={request.url[:60]}...")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        last_progress = -1
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded = line.decode('utf-8', errors='ignore').strip()

            if '[download]' in decoded and '%' in decoded:
                try:
                    percent_str = decoded.split('%')[0].split()[-1]
                    percent = int(float(percent_str))
                    if percent >= last_progress + 10:
                        logger.info(f"[{self.name}] 다운로드 진행: {percent}%")
                        last_progress = percent
                except (ValueError, IndexError):
                    pass
            elif '[Merger]' in decoded or 'Merging' in decoded:
                logger.info(f"[{self.name}] 비디오/오디오 병합 중...")

        stderr_output = await process.stderr.read()
        await process.wait()

        if process.returncode != 0:
            error_msg = self._format_yt_dlp_error(
                request.download_type,
                stderr_output.decode('utf-8', errors='ignore')
            )
            return {"success": False, "error": error_msg}

        possible_extensions = ['.mp4', '.webm', '.mkv']
        for ext in possible_extensions:
            output_path = f"{output_filename}{ext}"
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                title = self._extract_title_from_filename(output_path)
                logger.info(f"[{self.name}] 다운로드 완료: {file_size / 1024 / 1024:.1f}MB")
                return {
                    "success": True,
                    "output_path": output_path,
                    "file_size": file_size,
                    "title": title
                }

        return {"success": False, "error": "다운로드된 파일을 찾을 수 없음"}

    def _format_yt_dlp_error(self, download_type: str, stderr_text: str) -> str:
        """yt-dlp stderr를 사용자 친화적인 메시지로 정규화."""
        stderr_text = (stderr_text or "").strip()
        lowered = stderr_text.lower()

        if download_type == VideoDownload.TYPE_INSTAGRAM:
            if "login required" in lowered:
                return "Instagram 로그인 필요: 공개 Reel만 1차 지원합니다."
            if "private" in lowered or "not available" in lowered:
                return "Instagram 비공개 또는 접근 불가 Reel입니다."
            if "429" in lowered or "too many requests" in lowered:
                return "Instagram 요청 제한에 걸렸습니다. 잠시 후 다시 시도해주세요."
            if "requested content is not available" in lowered:
                return "Instagram Reel을 찾을 수 없습니다."

        if "sign in" in lowered or "login" in lowered:
            return f"yt-dlp 실패: 접근 권한 또는 로그인 필요 ({stderr_text[:160]})"

        return f"yt-dlp 실패: {stderr_text[:200] or '알 수 없는 오류'}"

    def _find_converted_file(self, directory: str, timestamp: str) -> Optional[str]:
        """변환된 파일을 찾습니다.

        Args:
            directory: 검색할 디렉토리
            timestamp: 타임스탬프 (파일명 패턴 매칭용)

        Returns:
            파일 경로 (없으면 None)
        """
        import glob

        # video_* 패턴으로 찾기
        patterns = [
            os.path.join(directory, f"video_{timestamp}_*.mp4"),
            os.path.join(directory, f"*_{timestamp}_*.mp4"),
            os.path.join(directory, "*.mp4"),
        ]

        for pattern in patterns:
            files = glob.glob(pattern)
            if files:
                # 가장 최근 파일 반환
                return max(files, key=os.path.getctime)

        return None

    def _extract_title_from_filename(self, filepath: str) -> str:
        """파일 경로에서 제목을 추출합니다.

        Args:
            filepath: 파일 경로

        Returns:
            추출된 제목
        """
        filename = os.path.basename(filepath)
        # 확장자 제거
        name, _ = os.path.splitext(filename)

        # video_YYYYMMDD_HHMMSS_제목 형식에서 제목 추출
        match = re.match(r'^(?:video_|ts_)?\d{8}_\d{6}_(.+)$', name)
        if match:
            return match.group(1)

        # ID_제목 형식에서 제목 추출
        match = re.match(r'^[a-zA-Z0-9_-]{11}_(.+)$', name)
        if match:
            return match.group(1)

        return name


def main():
    """워커 실행 진입점."""
    import argparse

    parser = argparse.ArgumentParser(description="비디오 다운로드 워커")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="다운로드 파일 저장 디렉토리"
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=2,
        help="동시 다운로드 최대 개수"
    )
    args = parser.parse_args()

    # 로깅 설정 (stdout으로 출력 - logs.ps1에서 읽을 수 있도록)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(handler)

    worker = VideoDownloadWorker(
        output_dir=args.output_dir,
        max_concurrent=args.max_concurrent
    )

    # 시그널 핸들러 설정
    def signal_handler(signum, frame):
        logger.info(f"시그널 {signum} 수신, 종료 중...")
        worker.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 워커 실행
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        logger.info("키보드 인터럽트로 종료")
    except Exception as e:
        logger.error(f"워커 오류: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
