"""로그 스트리밍 서비스"""

import asyncio
from collections import deque
from pathlib import Path
from typing import Optional, AsyncGenerator
import glob

from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import LogResponse


class LogService:
    """로그 파일 스트리밍 서비스"""

    def _find_latest_log(self) -> Optional[Path]:
        """최신 로그 파일 찾기"""
        log_dir = config.WTOOLS_BASE_DIR / config.LOG_DIR
        if not log_dir.exists():
            return None

        pattern = str(log_dir / config.LOG_FILE_PATTERN)
        log_files = glob.glob(pattern)

        if not log_files:
            return None

        # 최신 파일 반환 (mtime 기준)
        latest_file = max(log_files, key=lambda f: Path(f).stat().st_mtime)
        return Path(latest_file)

    def tail_log_file(self, n_lines: int = 100) -> LogResponse:
        """로그 파일 끝에서 N줄 읽기"""
        log_file = self._find_latest_log()

        if not log_file or not log_file.exists():
            return LogResponse(lines=[], total_lines=0)

        # 파일 끝에서 N줄 읽기 (deque 활용)
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = deque(f, maxlen=n_lines)
                return LogResponse(
                    lines=list(lines),
                    total_lines=len(lines)
                )
        except Exception as e:
            return LogResponse(
                lines=[f"Error reading log: {str(e)}"],
                total_lines=1
            )

    async def stream_log_file(self) -> AsyncGenerator[str, None]:
        """로그 파일 실시간 스트리밍 (SSE 형식)"""
        log_file = self._find_latest_log()

        if not log_file or not log_file.exists():
            yield "data: [No log file found]\n\n"
            return

        # 파일 열기 및 끝으로 이동
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                # 파일 끝으로 이동
                f.seek(0, 2)

                # 무한 루프로 새 줄 읽기
                while True:
                    line = f.readline()
                    if line:
                        # 새 줄이 있으면 전송
                        yield f"data: {line}\n\n"
                    else:
                        # 새 줄이 없으면 0.5초 대기
                        await asyncio.sleep(0.5)
        except Exception as e:
            yield f"data: [Error: {str(e)}]\n\n"


# 싱글톤 인스턴스
log_service = LogService()

__all__ = ['log_service', 'LogService']
