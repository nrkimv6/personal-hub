"""로그 파일 탐색·메타데이터 파싱 서비스 (LogService에서 분리)"""

import hashlib
import os
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
        """특정 runner의 표시용 로그 파일을 찾는다.

        stream 로그에 START marker만 있고 본로그에 실제 runner 출력이 있으면 본로그를
        선택한다. stream 파일에 실제 출력이 있으면 기존 stream 우선 계약을 유지한다.
        """
        try:
            stream_path_str = self._redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
            log_path_str = self._redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")

            stream_path = self._existing_path(stream_path_str)
            log_path = self._existing_path(log_path_str)

            if stream_path and log_path:
                return self.select_display_log(stream_path, log_path)

            return stream_path or log_path
        except redis.ConnectionError:
            pass

        # Phase 3 fallback: Redis TTL 만료 후 파일시스템 검색 (신규 형식 전용)
        # lg- 접두사는 레거시 파일용으로 Phase 2에서 별도 처리
        if runner_id.startswith("lg-"):
            return None
        return self.find_filesystem_log(runner_id)

    def find_filesystem_log(self, runner_id: str, log_dir: Optional[Path] = None) -> Optional[Path]:
        """Redis 상태가 없을 때 runner id 기반 stream/main 로그 pair를 파일시스템에서 찾는다."""
        if runner_id.startswith("lg-"):
            return None
        log_dir = log_dir or self.get_log_dir()
        if log_dir.exists():
            stream_path = self._best_display_candidate(log_dir.glob(f"plan-runner-stream-{runner_id}-*.log"))
            log_path = self._best_display_candidate(log_dir.glob(f"plan-runner-{runner_id}-*.log"))
            return self.select_display_log(stream_path, log_path)
        return None

    @classmethod
    def _runner_id_from_log_name(cls, path: Path) -> Optional[str]:
        """plan-runner 로그 파일명에서 runner_id를 추출한다.

        runner_id 자체에 '-'가 포함될 수 있으므로 뒤쪽 timestamp 구간을 기준으로 자른다.
        """
        match = re.match(
            r"^plan-runner(?:-stream)?-(?P<runner_id>.+?)-\d{8}(?:[-_]\d{6})?\.log$",
            path.name,
        )
        if not match:
            return None
        runner_id = match.group("runner_id").strip()
        return runner_id or None

    def discover_runner_log_evidence(self, log_dir: Optional[Path] = None) -> dict[str, dict]:
        """runner_id별 최신 표시 로그와 header 메타를 반환한다."""
        log_dir = log_dir or self.get_log_dir()
        if not log_dir.exists():
            return {}

        grouped: dict[str, list[Path]] = {}
        for pattern in ("plan-runner-stream-*.log", "plan-runner-*.log"):
            for path in log_dir.glob(pattern):
                runner_id = self._runner_id_from_log_name(path)
                if not runner_id:
                    continue
                grouped.setdefault(runner_id, []).append(path)

        result: dict[str, dict] = {}
        for runner_id, paths in grouped.items():
            stream_path = self._best_display_candidate(
                p for p in paths if p.name.startswith("plan-runner-stream-")
            )
            log_path = self._best_display_candidate(
                p for p in paths if not p.name.startswith("plan-runner-stream-")
            )
            selected = self.select_display_log(stream_path, log_path)
            if not selected:
                continue
            meta = self.parse_meta_from_log(str(selected), scan_lines=30)
            warnings: list[str] = []
            if not meta.get("trigger") and not meta.get("started_at") and not meta.get("plan_key"):
                warnings.append("log_header_missing")
            log_runner_id = meta.get("runner_id")
            if log_runner_id and str(log_runner_id) != runner_id:
                warnings.append("runner_id_mismatch")
            try:
                stat = selected.stat()
                log_mtime = stat.st_mtime
            except OSError:
                log_mtime = None
            result[runner_id] = {
                "runner_id": runner_id,
                "log_file": str(selected),
                "log_mtime": log_mtime,
                "meta": meta,
                "warnings": warnings,
            }
        return result

    @staticmethod
    def _existing_path(raw_path) -> Optional[Path]:
        if not raw_path:
            return None
        try:
            path = Path(os.fsdecode(raw_path))
        except (TypeError, ValueError, OSError):
            return None
        return path if path.exists() else None

    @staticmethod
    def _latest_existing(paths) -> Optional[Path]:
        existing = [p for p in paths if p.exists()]
        if not existing:
            return None
        return max(existing, key=lambda p: p.stat().st_mtime)

    @classmethod
    def _best_display_candidate(cls, paths) -> Optional[Path]:
        existing = [p for p in paths if p.exists()]
        if not existing:
            return None

        def quality(path: Path) -> tuple[int, float]:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            if cls._has_runner_output(path):
                return (3, mtime)
            if not cls._is_empty_or_start_marker_only(path):
                return (2, mtime)
            try:
                if path.stat().st_size > 0:
                    return (1, mtime)
            except OSError:
                pass
            return (0, mtime)

        return max(existing, key=quality)

    @classmethod
    def select_display_log(cls, stream_path: Optional[Path], log_path: Optional[Path]) -> Optional[Path]:
        """stream/main pair 중 UI와 API에 보여줄 로그를 고른다."""
        if stream_path and log_path:
            if cls._is_empty_or_start_marker_only(stream_path) and cls._has_runner_output(log_path):
                return log_path
            return stream_path
        return stream_path or log_path

    @staticmethod
    def _read_sample_lines(path: Path, max_lines: int = 20) -> list[str]:
        lines: list[str] = []
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for _ in range(max_lines):
                    line = f.readline()
                    if not line:
                        break
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
        except (OSError, IOError):
            return []
        return lines

    @classmethod
    def _is_start_marker_only(cls, path: Path) -> bool:
        lines = cls._read_sample_lines(path, max_lines=5)
        if not lines:
            return False
        if len(lines) > 3:
            return False
        marker_patterns = (
            "START",
            "log_path=",
            "marker",
        )
        return all(any(token in line for token in marker_patterns) for line in lines)

    @classmethod
    def _is_empty_or_start_marker_only(cls, path: Path) -> bool:
        try:
            if path.stat().st_size == 0:
                return True
        except OSError:
            return False
        return cls._is_start_marker_only(path)

    @classmethod
    def _has_runner_output(cls, path: Path) -> bool:
        lines = cls._read_sample_lines(path, max_lines=80)
        real_markers = (
            "[TRIGGER]",
            "[RUN_META]",
            "[PLAN-RUNNER",
            "[MERGE]",
            "MERGE_PRECHECK_FAILED",
            "service_lock",
            "[ERROR]",
            "[WARN]",
            "[INFO]",
            "WRITE_SCOPE_REROUTE_REQUIRED",
        )
        return any(any(marker in line for marker in real_markers) for line in lines)

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
    def _basename_from_plan_value(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        if value in {"__ALL_PLANS__", "ALL"}:
            return "전체 실행"
        name = Path(value).name
        return name or value

    @classmethod
    def display_plan_name_from_meta(cls, meta: dict) -> Optional[str]:
        """[TRIGGER] plan= 또는 [RUN_META] plan_key=에서 UI fallback 표시명을 만든다."""
        return cls._basename_from_plan_value(meta.get("plan")) or cls._basename_from_plan_value(meta.get("plan_key"))

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
            "engine": None,
            "fix_engine": None,
            "runner_id": None,
            "started_at": None,
            "execution_count": None,
            "plan_key": None,
            "start_log_path": None,
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
                            elif p.startswith("engine=") and result["engine"] is None:
                                result["engine"] = p[len("engine="):]
                            elif p.startswith("fix_engine=") and result["fix_engine"] is None:
                                result["fix_engine"] = p[len("fix_engine="):]
                            elif p.startswith("runner_id=") and result["runner_id"] is None:
                                result["runner_id"] = p[len("runner_id="):]
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
                    elif "START" in line and "log_path=" in line and result["start_log_path"] is None:
                        marker = "log_path="
                        start = line.find(marker)
                        if start >= 0:
                            result["start_log_path"] = line[start + len(marker):].strip()
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
