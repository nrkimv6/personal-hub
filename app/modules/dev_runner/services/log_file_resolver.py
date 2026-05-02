"""로그 파일 탐색·메타데이터 파싱 서비스 (LogService에서 분리)"""

import hashlib
import re
from pathlib import Path
from typing import Optional

import redis

from app.modules.dev_runner.services.redis_connection import RUNNER_KEY_PREFIX

__all__ = ["LogFileResolver"]


class LogFileResolver:
    """로그 파일 경로 결정 및 메타데이터 파싱.

    LogService에서 파일 탐색 책임을 분리한다.
    생성자에서 config와 redis_client를 주입받아 독립적으로 동작한다.
    """

    # 레거시 파일명(runner_id 없음) pseudo_id → Path 역매핑 캐시
    _legacy_map: dict[str, Path] = {}

    def __init__(self, config, redis_client: redis.Redis):
        self._config = config
        self._redis_client = redis_client

    # ------------------------------------------------------------------
    # 로그 디렉토리
    # ------------------------------------------------------------------

    def get_log_dir(self) -> Path:
        """로그 디렉토리 경로 반환 (config.LOG_DIR 기준, wtools 절대경로로 보정)"""
        log_dir = self._config.LOG_DIR
        if not log_dir.is_absolute():
            log_dir = self._config.WTOOLS_BASE_DIR / log_dir
        return log_dir

    # ------------------------------------------------------------------
    # 로그 파일 탐색
    # ------------------------------------------------------------------

    def find_current_log(self, runner_id: str) -> Optional[Path]:
        """특정 runner의 로그 파일 (Redis에서 조회)

        stream_log_path와 log_file_path 둘 다 있으면 stream 로그를 우선한다.
        runner 탭의 실시간/후속 조회 계약은 PS stream 로그 기준이며, 작은 START marker만 있어도
        일반 plan log로 바꾸면 runner/log 매핑이 다시 어긋난다.
        """
        try:
            stream_path_str = self._redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
            log_path_str = self._redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")

            stream_path = None
            log_path = None

            if stream_path_str:
                p = Path(stream_path_str)
                if p.exists():
                    stream_path = p

            if log_path_str:
                p = Path(log_path_str)
                if p.exists():
                    log_path = p

            if stream_path and log_path:
                return stream_path

            return stream_path or log_path
        except redis.ConnectionError:
            pass

        # Phase 3 fallback: Redis TTL 만료 후 파일시스템 검색 (신규 형식 전용)
        # lg- 접두사는 레거시 파일용으로 Phase 2에서 별도 처리
        if runner_id.startswith("lg-"):
            return None
        log_dir = self.get_log_dir()
        if log_dir.exists():
            for pattern in [
                f"plan-runner-stream-{runner_id}-*.log",
                f"plan-runner-{runner_id}-*.log",
            ]:
                matches = list(log_dir.glob(pattern))
                if matches:
                    return max(matches, key=lambda p: p.stat().st_mtime)
        return None

    def resolve_legacy_log(self, runner_id: str) -> Optional[Path]:
        """lg- 접두사 pseudo runner_id로 레거시 파일 탐색.

        1. _legacy_map 캐시 히트 → 즉시 반환
        2. 캐시 미스 → 전체 스캔 후 _legacy_map 갱신
        """
        if runner_id in self._legacy_map:
            return self._legacy_map[runner_id]
        log_dir = self.get_log_dir()
        if not log_dir.exists():
            return None
        for log_path in log_dir.glob("plan-runner-stream-*.log"):
            m = re.match(r"plan-runner-stream-(\d{8}_\d{6})\.log$", log_path.name)
            if not m:
                continue
            ts = m.group(1)
            pseudo_id = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"
            self._legacy_map[pseudo_id] = log_path
        return self._legacy_map.get(runner_id)

    # ------------------------------------------------------------------
    # 메타데이터 파싱
    # ------------------------------------------------------------------

    @staticmethod
    def parse_meta_from_log(log_file_path: str, scan_lines: int = 15) -> dict:
        """로그 파일 선두 N줄에서 [TRIGGER]/[RUN_META] 메타데이터 파싱.

        Returns:
            {
                "trigger": str|None,
                "plan": str|None,
                "started_at": str|None,   # [RUN_META] started_at=
                "execution_count": int|None,  # [RUN_META] execution_count=
                "plan_key": str|None,     # [RUN_META] plan_key=
            }
        """
        result: dict = {
            "trigger": None,
            "plan": None,
            "started_at": None,
            "execution_count": None,
            "plan_key": None,
        }
        try:
            with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                for _ in range(scan_lines):
                    line = f.readline()
                    if not line:
                        break
                    line = line.rstrip("\n")
                    if line.startswith("[TRIGGER] ") and result["trigger"] is None:
                        rest = line[len("[TRIGGER] "):]
                        parts = rest.split(" | ")
                        result["trigger"] = parts[0]
                        for p in parts[1:]:
                            if p.startswith("plan=") and result["plan"] is None:
                                result["plan"] = p[5:]
                    elif line.startswith("[RUN_META] ") and result["started_at"] is None:
                        parts = line[len("[RUN_META] "):].split(" | ")
                        for p in parts:
                            if p.startswith("started_at="):
                                result["started_at"] = p[len("started_at="):]
                            elif p.startswith("execution_count="):
                                raw = p[len("execution_count="):]
                                try:
                                    result["execution_count"] = int(raw)
                                except (ValueError, TypeError):
                                    pass
                            elif p.startswith("plan_key="):
                                result["plan_key"] = p[len("plan_key="):]
                    # 두 줄 모두 파싱 완료되면 종료
                    if result["trigger"] and result["started_at"] is not None:
                        break
        except (OSError, IOError):
            pass
        return result

    @staticmethod
    def parse_trigger_from_log(log_file_path: str) -> Optional[str]:
        """로그 파일 선두 N줄에서 [TRIGGER] 파싱. 기존 호출처 호환."""
        return LogFileResolver.parse_meta_from_log(log_file_path).get("trigger")
