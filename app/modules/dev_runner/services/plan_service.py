"""plan 문서 관리 서비스"""

import asyncio
import json
import logging
import os
import re
import redis
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import List, Optional

from app.modules.dev_runner.config import config
from app.modules.dev_runner.services.plan_path_helpers import (
    load_wtools_project_roots,
    iter_repo_plan_path_candidates,
    extract_repo_root_from_plan_path,
    backfill_dual_paths,
    canonicalize_wtools_legacy_common_path,
    dedupe_prefer_worktree,
    resolve_plans_ledger_paths,
)
from app.modules.dev_runner.services._plan_header_utils import validate_done_preconditions, update_plan_headers
from app.modules.dev_runner.services.archive_service import archive_plan_bundle, resolve_archive_target_or_raise
from app.modules.dev_runner.services.git_commit_roots import commit_files_by_git_root
from app.modules.dev_runner.services.log_service import SYSTEM_LOG_CHANNEL, REDIS_HOST, REDIS_PORT
from app.modules.dev_runner.services.git_utils import check_branch_exists, check_worktree_exists
from app.modules.dev_runner.services.plan_path_resolver import PathRuleError
from app.core.config import PROJECT_ROOT
from app.shared.io import write_json_atomic
from app.modules.dev_runner.schemas import (
    PlanFileResponse, PlanProgressResponse,
    PlanDetailResponse, PlanPhaseResponse, PlanItemResponse,
    RegisteredPathResponse,
)

logger = logging.getLogger(__name__)

# 모듈 레벨 Redis 연결 (lazy — 첫 호출 시 생성)
_redis_client: Optional[redis.Redis] = None


def _get_monitor_page_plan_paths() -> dict[str, tuple[Path, Path]]:
    return {
        "plan": (
            PROJECT_ROOT / "docs" / "plan",
            PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "plan",
        ),
        "archive": (
            PROJECT_ROOT / "docs" / "archive",
            PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "archive",
        ),
    }


def _extract_created_at(content: str, path: Path) -> Optional[str]:
    """plan 헤더에서 작성일시 추출.
    fallback: 파일명 날짜 → file mtime.
    """
    from datetime import datetime

    # 1. 헤더 > 작성일시: YYYY-MM-DD HH:MM
    m = re.search(r'^>\s*작성일시:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    # 2. 파일명 YYYY-MM-DD
    m2 = re.match(r'^(\d{4}-\d{2}-\d{2})', path.name)
    if m2:
        return m2.group(1) + ' 00:00'
    # 3. file mtime
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return '0000-00-00 00:00'


def _get_redis() -> Optional[redis.Redis]:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT,
                decode_responses=True, socket_connect_timeout=2
            )
        except Exception:
            return None
    return _redis_client


def _publish_log(tag: str, message: str):
    """Redis pub/sub으로 로그 publish (LogViewer에 실시간 표시)"""
    from datetime import datetime
    try:
        r = _get_redis()
        if r:
            ts = datetime.now().strftime("%H:%M:%S")
            r.publish(SYSTEM_LOG_CHANNEL, f"[{ts}] [{tag}] {message}")
    except Exception:
        pass  # Redis 미연결 시 무시


class PlanService:
    """plan 문서 탐색 및 파싱 서비스"""

    def __init__(self):
        self._registered_paths: List[dict] = []  # {"path": str, "type": "plan"|"archive"}
        self._ignored_plans: List[str] = []
        # archive 캐시: {dir_path: {"mtime": float, "results": [PlanFileResponse]}}
        # include_ignored=True 경로에서만 활용 (기본 리스트는 archive 스캔 자체를 스킵)
        self._archive_cache: dict[str, dict] = {}
        # plan 전체 목록 캐시 (startup 시 빌드, mutation 시 무효화)
        self._plans_cache: Optional[List[PlanFileResponse]] = None
        self._plans_cache_with_ignored: Optional[List[PlanFileResponse]] = None
        self._plans_cache_time: float = 0  # 캐시 빌드 시각 (time.monotonic)
        self._migrate_to_registered_paths()
        self._load_registered_paths()
        self._load_ignored_plans()

    # ========== 경로 저장/로드 ==========

    def _migrate_to_registered_paths(self):
        """external_plans.json → registered_paths.json 마이그레이션 (1회성)
        + 문자열 배열 → 객체 배열 마이그레이션 (스키마 변경 대응)
        """
        reg_path = config.REGISTERED_PATHS_FILE

        if reg_path.exists():
            changed = False
            try:
                data = json.loads(reg_path.read_text(encoding="utf-8"))
                if data and isinstance(data[0], str):
                    migrated = [{"path": p, "type": "plan"} for p in data]
                    data = migrated
                    changed = True
                    logger.info(f"[마이그레이션] 문자열→객체 배열 변환 완료 ({len(migrated)}개)")
                normalized, normalized_changed = self._normalize_registered_paths(data)
                if normalized_changed or changed:
                    write_json_atomic(reg_path, normalized)
            except Exception:
                pass
            return

        entries: List[dict] = []
        existing_keys: set[tuple[str, str]] = set()

        def _add_entry(
            path: Path,
            path_type: str,
            *,
            require_exists: bool = True,
            raw_path: str | None = None,
        ) -> None:
            if require_exists and not path.exists():
                return
            resolved = raw_path if raw_path is not None else str(path.resolve())
            key = (resolved, path_type)
            if key not in existing_keys:
                entries.append({"path": resolved, "type": path_type})
                existing_keys.add(key)

        # 기존 external_plans.json에서 가져오기
        ext_path = config.EXTERNAL_PLANS_FILE
        if ext_path.exists():
            try:
                raw = json.loads(ext_path.read_text(encoding="utf-8"))
                for p in raw:
                    if isinstance(p, str):
                        _add_entry(Path(p), "plan", require_exists=False, raw_path=p)
                logger.info(f"[마이그레이션] external_plans.json에서 로드")
            except Exception:
                pass

        # .claude/projects.json 기반 시드 (우선)
        project_roots = load_wtools_project_roots()
        if project_roots:
            for root in project_roots:
                for candidate_path, path_type in iter_repo_plan_path_candidates(root):
                    _add_entry(candidate_path, path_type)
            logger.info(f"[마이그레이션] projects.json 시드 완료 — {len(project_roots)}개 repo")
        else:
            # fallback: WTOOLS_BASE_DIR + PROJECT_DIRS (projects.json 없는 환경)
            base = config.WTOOLS_BASE_DIR
            if base.exists():
                for candidate_path, path_type in iter_repo_plan_path_candidates(base):
                    _add_entry(candidate_path, path_type)
                for project in config.PROJECT_DIRS:
                    project_root = base / project
                    for candidate_path, path_type in iter_repo_plan_path_candidates(project_root):
                        _add_entry(candidate_path, path_type)
                logger.info(f"[마이그레이션] WTOOLS fallback 시드 완료")

        if entries:
            normalized, _ = self._normalize_registered_paths(entries)
            write_json_atomic(reg_path, normalized)
            logger.info(f"[마이그레이션] registered_paths.json 생성 완료 ({len(normalized)}개)")

    def _load_registered_paths(self):
        """등록된 경로 목록 로드 (JSON 파일) — 객체 배열 {"path", "type"}"""
        path = config.REGISTERED_PATHS_FILE
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                normalized, changed = self._normalize_registered_paths(loaded)
                backfilled, backfill_changed = self._backfill_dual_paths(normalized)
                self._registered_paths = backfilled
                if changed or backfill_changed:
                    write_json_atomic(path, backfilled)
            except Exception:
                self._registered_paths = []

    def _backfill_dual_paths(self, entries: List[dict]) -> tuple[List[dict], bool]:
        """기존 등록 목록에서 docs <-> worktree 상호 보완 경로를 backfill한다.

        docs/plan 만 등록되어 있고 .worktrees/plans/docs/plan 이 실재하면 추가 (vice versa).
        """
        return backfill_dual_paths(entries)

    def _save_registered_paths(self):
        """등록된 경로 목록 저장 — 객체 배열 {"path", "type"}"""
        path = config.REGISTERED_PATHS_FILE
        normalized, _ = self._normalize_registered_paths(self._registered_paths)
        self._registered_paths = normalized
        write_json_atomic(path, normalized)

    def _get_registered_path_strs(self) -> List[str]:
        """등록 경로를 문자열 목록으로 반환 (내부 탐색용)"""
        return [entry["path"] for entry in self._registered_paths]

    @staticmethod
    def _resolve_path_str(path_str: str) -> str:
        try:
            path = Path(path_str)
            if path_str.startswith("/") and not path.exists():
                return path_str
            return str(path.resolve())
        except Exception:
            return path_str

    def _normalize_registered_paths(self, entries: List[dict] | List[str]) -> tuple[List[dict], bool]:
        """monitor-page 레거시 docs 경로를 plans worktree SSOT로 정규화한다."""
        normalized: List[dict] = []
        seen: set[tuple[str, str]] = set()
        changed = False

        legacy_map: dict[str, tuple[str, str]] = {}
        for path_type, (legacy_path, ssot_path) in _get_monitor_page_plan_paths().items():
            legacy_map[self._resolve_path_str(str(legacy_path))] = (str(ssot_path.resolve()), path_type)

        for entry in entries:
            if isinstance(entry, str):
                item = {"path": entry, "type": "plan"}
                changed = True
            else:
                item = {"path": entry.get("path"), "type": entry.get("type", "plan")}

            path_value = item.get("path")
            if not path_value:
                changed = True
                continue

            resolved = self._resolve_path_str(path_value)
            replacement = legacy_map.get(resolved)
            if replacement is not None:
                path_value, expected_type = replacement
                if item["type"] != expected_type or item["path"] != path_value:
                    changed = True
                item["path"] = path_value
                item["type"] = expected_type
            else:
                canonical = canonicalize_wtools_legacy_common_path(resolved, item["type"])
                if canonical is not None:
                    path_value, expected_type = canonical
                    if item["type"] != expected_type or item["path"] != path_value:
                        changed = True
                    item["path"] = path_value
                    item["type"] = expected_type

            dedupe_key = (item["path"], item["type"])
            if dedupe_key in seen:
                changed = True
                continue
            seen.add(dedupe_key)
            normalized.append(item)

        return normalized, changed

    def _load_ignored_plans(self):
        """수동 무시 plan 목록 로드"""
        path = config.IGNORED_PLANS_FILE
        if path.exists():
            try:
                self._ignored_plans = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._ignored_plans = []

    def _save_ignored_plans(self):
        """수동 무시 plan 목록 저장"""
        path = config.IGNORED_PLANS_FILE
        write_json_atomic(path, self._ignored_plans)

    # ========== 경로 관리 ==========

    def add_to_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에 추가"""
        resolved = str(Path(plan_path).resolve())
        if resolved not in self._ignored_plans:
            self._ignored_plans.append(resolved)
            self._save_ignored_plans()
            self.invalidate_plans_cache()
            return True
        return False

    def remove_from_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에서 제거"""
        resolved = str(Path(plan_path).resolve())
        if resolved in self._ignored_plans:
            self._ignored_plans.remove(resolved)
            self._save_ignored_plans()
            self.invalidate_plans_cache()
            return True
        return False

    def add_path(self, plan_path: str, path_type: str = "plan") -> bool:
        """등록 경로 추가 (영구 저장)

        Args:
            plan_path: 등록할 경로
            path_type: "plan" | "archive" (기본값: "plan")
        """
        resolved = str(Path(plan_path).resolve())
        existing_paths = self._get_registered_path_strs()
        if resolved not in existing_paths:
            self._registered_paths.append({"path": resolved, "type": path_type})
            self._save_registered_paths()
            self.invalidate_plans_cache()
            return True
        return False

    def remove_path(self, plan_path: str) -> bool:
        """등록 경로 제거"""
        resolved = str(Path(plan_path).resolve())
        for i, entry in enumerate(self._registered_paths):
            if entry["path"] == resolved:
                self._registered_paths.pop(i)
                self._save_registered_paths()
                self.invalidate_plans_cache()
                return True
        return False

    # ========== plan 목록 ==========

    def invalidate_plans_cache(self):
        """plan 목록 캐시 무효화 — mutation 후 호출"""
        self._plans_cache = None
        self._plans_cache_with_ignored = None
        self._plans_cache_time = 0

    def _scan_all_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """실제 파일시스템 스캔 (캐시 미스 시 호출).

        같은 (repo_root, filename) 조합이 docs와 .worktrees/plans/docs 양쪽에 있으면
        worktree 경로를 우선 노출하고 docs 경로는 제거한다.
        """
        seen: set[str] = set()
        raw_results: List[PlanFileResponse] = []

        for entry in self._registered_paths:
            is_archive = entry.get("type") == "archive"
            # archive 경로는 include_ignored=True 시에만 스캔 (기본 리스트에서 제외)
            if is_archive and not include_ignored:
                continue
            reg_path = entry["path"]
            p = Path(reg_path)
            if not p.exists():
                continue
            if p.is_dir():
                self._scan_plan_dir(
                    p, seen, raw_results, include_ignored,
                    path_type="folder",
                    recursive=is_archive,
                )
            elif p.is_file():
                if str(p) not in seen:
                    seen.add(str(p))
                    status = self.get_plan_status(p)
                    progress = self.get_plan_progress(p)
                    is_ignored = self._is_ignored_plan(p, status, progress)
                    if include_ignored or not is_ignored:
                        try:
                            content = p.read_text(encoding="utf-8")
                            summary = self._extract_summary(content)
                            created_at = _extract_created_at(content, p)
                        except Exception:
                            summary = None
                            created_at = _extract_created_at('', p)
                        raw_results.append(
                            PlanFileResponse(
                                path=str(p),
                                filename=p.name,
                                status=status,
                                progress=progress,
                                source=self._resolve_source(p.parent),
                                ignored=is_ignored,
                                path_type="file",
                                summary=summary,
                                created_at=created_at,
                            )
                        )

        results = self._dedupe_prefer_worktree(raw_results)
        results.sort(key=lambda x: x.created_at or x.filename, reverse=True)
        return results

    @staticmethod
    def _dedupe_prefer_worktree(results: List[PlanFileResponse]) -> List[PlanFileResponse]:
        """같은 (repo_root, filename)이면 worktree 경로를 남기고 docs 경로를 제거한다."""
        return dedupe_prefer_worktree(results)

    def list_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """
        plan 목록 조회 — 캐시 우선, 미스 시 파일시스템 스캔

        모든 경로를 동등하게 취급 (고정/외부 구분 없음)
        """
        # TTL 만료 시 캐시 무효화 (runner 종료 트리거 없는 경우 fallback)
        if getattr(self, "_plans_cache", None) is not None and time.monotonic() - getattr(self, "_plans_cache_time", 0) > self._PLANS_CACHE_TTL:
            self.invalidate_plans_cache()

        if include_ignored:
            if self._plans_cache_with_ignored is None:
                self._plans_cache_with_ignored = self._scan_all_plans(include_ignored=True)
                self._plans_cache_time = time.monotonic()
            return self._plans_cache_with_ignored
        else:
            if self._plans_cache is None:
                self._plans_cache = self._scan_all_plans(include_ignored=False)
                self._plans_cache_time = time.monotonic()
            return self._plans_cache

    def list_ignored_plans(self) -> List[PlanFileResponse]:
        """무시된(완료/빈) plan 목록만 조회"""
        all_plans = self.list_plans(include_ignored=True)
        return [p for p in all_plans if p.ignored]

    def _resolve_source(self, path: Path) -> str:
        """경로에서 source 자동 결정

        - .../프로젝트/docs/plan → 프로젝트명
        - .../common/docs/plan → "common"
        - .../폴더명 → 폴더명
        """
        parts = path.parts
        # .worktrees 포함 시 .worktrees 직전 디렉토리명 반환 (plans 오분류 차단)
        if ".worktrees" in parts:
            wt_idx = list(parts).index(".worktrees")
            if wt_idx > 0:
                return parts[wt_idx - 1]
        for i, part in enumerate(parts):
            if part == "docs" and i + 1 < len(parts) and parts[i + 1] == "plan":
                # docs/plan 직전 디렉토리 = 프로젝트명
                if i > 0:
                    return parts[i - 1]
                return "common"
        # docs/plan 패턴 없음 → 폴더명 자체
        return path.name or "unknown"

    def _get_dir_fingerprint(self, plan_dir: Path) -> float:
        """디렉토리 mtime 반환 (캐시 무효화용, 가벼운 단일 stat)"""
        try:
            return plan_dir.stat().st_mtime
        except Exception:
            return 0.0

    def _scan_plan_dir(
        self,
        plan_dir: Path,
        seen: set,
        results: List[PlanFileResponse],
        include_ignored: bool,
        path_type: Optional[str] = None,
        recursive: bool = False,
    ):
        """plan 디렉토리 스캔

        Args:
            plan_dir: 스캔할 디렉토리
            seen: 이미 처리된 경로 집합 (중복 방지)
            results: 결과 목록 (append)
            include_ignored: True이면 무시된 plan도 포함
            path_type: "folder" | None — PlanFileResponse.path_type에 설정할 값
            recursive: True이면 하위 폴더까지 재귀 스캔 (archive 타입에 사용)
        """
        if not plan_dir.exists():
            return

        # archive 디렉토리는 캐시 사용 (파일 변경이 거의 없음)
        if recursive:
            cache_key = str(plan_dir)
            cached = self._archive_cache.get(cache_key)
            if cached:
                cur_mtime = self._get_dir_fingerprint(plan_dir)
                if cached["mtime"] == cur_mtime:
                    # 캐시 히트: seen 업데이트 + 필터링된 결과 추가
                    for item in cached["results"]:
                        if item.path not in seen:
                            seen.add(item.path)
                            if include_ignored or not item.ignored:
                                results.append(item)
                    return

        source = self._resolve_source(plan_dir)
        scanned_items: List[PlanFileResponse] = []

        glob_fn = plan_dir.rglob if recursive else plan_dir.glob
        for plan_file in glob_fn("*.md"):
            if plan_file.stem.endswith("_todo"):
                pass  # _todo.md는 항상 표시 (체크박스가 있는 작업 파일)
            else:
                # 대응 _todo.md가 있으면 메인 파일 스킵 (_todo가 대표)
                todo_file = plan_file.parent / (plan_file.stem + "_todo.md")
                if todo_file.exists():
                    continue
            key = str(plan_file)
            if key in seen:
                continue
            seen.add(key)

            status = self.get_plan_status(plan_file)
            progress = self.get_plan_progress(plan_file)
            is_ignored = self._is_ignored_plan(plan_file, status, progress)

            try:
                content = plan_file.read_text(encoding="utf-8")
                summary = self._extract_summary(content)
                created_at = _extract_created_at(content, plan_file)
                wt_meta = self._extract_worktree_meta(content)
            except Exception:
                summary = None
                created_at = _extract_created_at('', plan_file)
                wt_meta = {"branch": None, "worktree_path": None, "worktree_owner": None}

            item = PlanFileResponse(
                path=str(plan_file),
                filename=plan_file.name,
                status=status,
                progress=progress,
                source=source,
                ignored=is_ignored,
                path_type=path_type,
                summary=summary,
                created_at=created_at,
                branch=wt_meta.get("branch"),
                worktree_path=wt_meta.get("worktree_path"),
                worktree_owner=wt_meta.get("worktree_owner"),
            )
            scanned_items.append(item)

            if include_ignored or not is_ignored:
                results.append(item)

        # archive 디렉토리 결과를 캐시에 저장
        if recursive:
            self._archive_cache[str(plan_dir)] = {
                "mtime": self._get_dir_fingerprint(plan_dir),
                "results": scanned_items,
            }

    # 자동 무시 대상 상태 (정확히 일치해야 함)
    _IGNORED_STATUSES = {"보류", "가이드"}
    # 완료 계열 상태 (아카이브 허용 + 목록 숨김)
    _DONE_STATUSES = {"구현완료", "완료", "수정 완료", "배포완료", "수정완료"}
    # plans 캐시 TTL (초) — runner 종료 트리거 없이도 stale 캐시가 자동 갱신됨
    _PLANS_CACHE_TTL = 60

    def _is_ignored_plan(self, path: Path, status: str, progress: Optional[PlanProgressResponse] = None) -> bool:
        """plan이 무시 대상인지 판단"""
        # 수동 무시 목록
        if str(path.resolve()) in self._ignored_plans:
            return True
        # 보류 상태
        if status in self._IGNORED_STATUSES:
            return True
        # 완료 계열 상태
        if status in self._DONE_STATUSES:
            return True
        # 진행률 100% plan은 자동 숨김 (완료 처리 전 임시 잔존 방지)
        if progress and progress.total > 0 and progress.done >= progress.total:
            return True
        return False

    # ========== plan 파싱 ==========

    def get_plan_progress(self, path: Path) -> PlanProgressResponse:
        """plan 진행률 파싱"""
        if not path.exists():
            return PlanProgressResponse(done=0, total=0, percent=0)

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            content = self._remove_code_blocks(content)
            # 멀티레벨 체크박스 지원: "- [x]", "  - [x]", "1. - [x]", "1. [x]" 모두 인식
            checkbox_pattern = r"^[ \t]*(?:\d+\.\s+(?:[-*]\s*)?|[-*]+\s*)\[([ x→])\]"
            matches = re.findall(checkbox_pattern, content, re.MULTILINE)

            total = len(matches)
            done = sum(1 for m in matches if m == "x")
            percent = int(done / total * 100) if total > 0 else 0

            return PlanProgressResponse(done=done, total=total, percent=percent)
        except Exception:
            return PlanProgressResponse(done=0, total=0, percent=0)

    @staticmethod
    def _strip_markdown_inline(text: str) -> str:
        """마크다운 인라인 스타일 제거 (**굵게**, *기울임*, ~~취소선~~, `코드`)"""
        return re.sub(r'[*_~`]+', '', text).strip()

    def get_plan_status(self, path: Path) -> str:
        """plan 상태 파싱 (> 상태: ...), 없으면 유형으로 판단"""
        if not path.exists():
            return "unknown"

        try:
            doc_type = None
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    match = re.match(r">\s*상태:\s*(.+)", line)
                    if match:
                        return self._strip_markdown_inline(match.group(1))
                    # - **상태**: ... (리스트+bold 형식)
                    match2 = re.match(r"-\s*\*{0,2}상태\*{0,2}:\s*(.+)", line)
                    if match2:
                        return self._strip_markdown_inline(match2.group(1))
                    type_match = re.match(r">\s*유형:\s*(.+)", line)
                    if type_match:
                        doc_type = self._strip_markdown_inline(type_match.group(1))
            # 상태 라인이 없고, 보고서 유형이면 완료로 간주
            if doc_type and re.search(r'보고서|report', doc_type, re.IGNORECASE):
                return "완료"
            # 파일명에 -report, -postmortem 포함 시 완료로 간주
            stem = path.stem.lower()
            if '-report' in stem or '-postmortem' in stem:
                return "완료"
            # 가이드/아이디어/개요 문서 유형 감지
            if doc_type and re.search(r'가이드|guide|아이디어|idea|개요|overview|설계|design', doc_type, re.IGNORECASE):
                return "가이드"
            if any(kw in stem for kw in ('-guide', '-overview', '-idea', '-design', '-spec')):
                return "가이드"
            return "unknown"
        except Exception:
            return "unknown"

    def _find_todo_file(self, plan_path: Path) -> Optional[Path]:
        """plan 경로에서 대응하는 _todo.md 파일 탐색"""
        todo_name = plan_path.stem + "_todo.md"
        todo_path = plan_path.parent / todo_name
        if todo_path.exists():
            return todo_path
        return None

    @staticmethod
    def _extract_worktree_meta(content: str) -> dict:
        """plan 헤더에서 branch/worktree/worktree-owner 메타데이터를 추출한다.

        상단 20줄만 탐색. 경로 정규화:
        - 백슬래시 → 슬래시
        - 프로젝트 루트 절대경로 prefix 제거 → 상대경로
        반환: {"branch": str|None, "worktree_path": str|None, "worktree_owner": str|None}
        """
        project_root = str(PROJECT_ROOT).replace("\\", "/").rstrip("/") + "/"
        result: dict = {"branch": None, "worktree_path": None, "worktree_owner": None}
        for line in content.split("\n")[:20]:
            if result["branch"] is None:
                m = re.match(r'^>\s*branch:\s*(.+)', line)
                if m:
                    result["branch"] = m.group(1).strip()
            if result["worktree_path"] is None:
                m = re.match(r'^>\s*worktree:\s*(.+)', line)
                if m:
                    val = m.group(1).strip().replace("\\", "/")
                    if val.startswith(project_root):
                        val = val[len(project_root):]
                    result["worktree_path"] = val
            if result["worktree_owner"] is None:
                m = re.match(r'^>\s*worktree-owner:\s*(.+)', line)
                if m:
                    val = m.group(1).strip().replace("\\", "/")
                    if val.startswith(project_root):
                        val = val[len(project_root):]
                    result["worktree_owner"] = val
        return result

    @staticmethod
    def _extract_summary(content: str) -> Optional[str]:
        """plan 파일에서 요약 텍스트를 추출한다.

        우선순위:
        1. `> 요약: {텍스트}` 헤더 블록쿼트
        2. `## 개요` 섹션 첫 단락 (코드블럭 제외)
        3. `## 요약` 섹션 (구버전 하위 호환)
        """
        lines = content.split("\n")

        # 1. `> 요약:` 블록쿼트 탐색
        for line in lines:
            m = re.match(r'^>\s*요약:\s*(.+)', line)
            if m:
                text = m.group(1).strip()
                if text:
                    return text

        # 2. `## 개요` 섹션 첫 단락
        in_개요 = False
        in_codeblock = False
        collected: List[str] = []
        for line in lines:
            if re.match(r'^##\s+개요', line):
                in_개요 = True
                continue
            if in_개요:
                if re.match(r'^##\s+', line):
                    break
                if line.strip().startswith('```'):
                    in_codeblock = not in_codeblock
                    continue
                if in_codeblock:
                    continue
                # 빈 줄이 나오고 이미 내용이 있으면 첫 단락 종료
                if not line.strip() and collected:
                    break
                if line.strip():
                    collected.append(line.strip())
        text = " ".join(collected).strip()
        if text:
            return text

        # 3. `## 요약` (구버전 하위 호환)
        in_section = False
        collected = []
        for line in lines:
            if re.match(r'^##\s+요약', line):
                in_section = True
                continue
            if in_section:
                if re.match(r'^##\s+', line):
                    break
                collected.append(line)
        text = "\n".join(collected).strip()
        return text if text else None

    def parse_plan_items(self, path: Path) -> PlanDetailResponse:
        """plan 파일을 Phase별 항목으로 파싱"""
        # _todo 파일이 있으면 우선 사용
        todo_file = self._find_todo_file(path)
        parse_path = todo_file if todo_file else path

        content = parse_path.read_text(encoding="utf-8", errors="ignore")
        # 요약: todo 파일 우선, 없으면 원본 plan에서 fallback
        summary = self._extract_summary(content)
        if summary is None and todo_file is not None:
            orig_content = path.read_text(encoding="utf-8", errors="ignore")
            summary = self._extract_summary(orig_content)
        lines = content.split("\n")

        phases: List[PlanPhaseResponse] = []
        current_phase_name = "기타"
        current_items: List[PlanItemResponse] = []
        current_parent: Optional[PlanItemResponse] = None

        # 파일 경로 패턴: `path/to/file.ext`
        file_path_pattern = re.compile(r'`([^`]+\.[a-zA-Z]+)`')

        for line in lines:
            # Phase 헤더 감지
            phase_match = re.match(r'^#{2,3}\s+Phase\s+\d+[:\s—–-]*(.*)', line)
            if phase_match:
                # 이전 phase 저장
                if current_items:
                    done = sum(1 for i in current_items if i.checked)
                    total_children = sum(len(i.children) for i in current_items)
                    done_children = sum(1 for i in current_items for c in i.children if c.checked)
                    phases.append(PlanPhaseResponse(
                        name=current_phase_name,
                        items=current_items,
                        done_count=done + done_children,
                        total_count=len(current_items) + total_children,
                    ))
                current_phase_name = phase_match.group(0).lstrip("#").strip()
                current_items = []
                current_parent = None
                continue

            # 번호 체크박스 (상위): 1. [ ] or 1. [x]
            num_match = re.match(r'^(\d+)\.\s*\[([ x→])\]\s*(.*)', line)
            if num_match:
                text = num_match.group(3).strip()
                fp = file_path_pattern.search(text)
                item = PlanItemResponse(
                    level=0,
                    text=text,
                    checked=num_match.group(2) == 'x',
                    file_path=fp.group(1) if fp else None,
                )
                current_items.append(item)
                current_parent = item
                continue

            # 대시 체크박스: - [ ] or - [x] (최상위 + 하위 모두)
            dash_match = re.match(r'^(\s*)-\s*\[([ x→])\]\s*(.*)', line)
            if dash_match:
                indent = len(dash_match.group(1))
                text = dash_match.group(3).strip()
                fp = file_path_pattern.search(text)
                if indent > 0 and current_parent is not None:
                    # 들여쓰기 있음 → 하위 항목
                    child = PlanItemResponse(
                        level=1,
                        text=text,
                        checked=dash_match.group(2) == 'x',
                        file_path=fp.group(1) if fp else None,
                    )
                    current_parent.children.append(child)
                else:
                    # 들여쓰기 없음 → 상위 항목
                    item = PlanItemResponse(
                        level=0,
                        text=text,
                        checked=dash_match.group(2) == 'x',
                        file_path=fp.group(1) if fp else None,
                    )
                    current_items.append(item)
                    current_parent = item

        # 마지막 phase 저장
        if current_items:
            done = sum(1 for i in current_items if i.checked)
            total_children = sum(len(i.children) for i in current_items)
            done_children = sum(1 for i in current_items for c in i.children if c.checked)
            phases.append(PlanPhaseResponse(
                name=current_phase_name,
                items=current_items,
                done_count=done + done_children,
                total_count=len(current_items) + total_children,
            ))

        status = self.get_plan_status(path)
        progress = self.get_plan_progress(parse_path)

        return PlanDetailResponse(
            path=str(path),
            filename=path.name,
            status=status,
            phases=phases,
            progress=progress,
            summary=summary,
        )

    # ========== done 처리 (Python 네이티브) ==========

    COMMIT_PS1 = Path("D:/work/project/tools/common/commit.ps1")
    COMMIT_SH = Path("D:/work/project/tools/common/commit.sh")

    @staticmethod
    def _remove_code_blocks(content: str) -> str:
        """코드블록/인라인 코드 제거 (체크박스 오인식 방지)"""
        content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
        content = re.sub(r'`[^`\n]+`', '', content)
        return content

    @staticmethod
    def _extract_pending_checkboxes(content: str) -> List[str]:
        """문서 전체에서 미완료 체크박스 텍스트 추출 (코드블록 제외)"""
        cleaned = PlanService._remove_code_blocks(content)
        # 멀티레벨 체크박스 지원: "- [ ]", "  - [ ]", "1. - [ ]" 모두 인식
        matches = re.findall(r'^[ \t]*(?:\d+\.\s+)?[-*]\s*\[ \]\s*(.+)$', cleaned, re.MULTILINE)
        return [PlanService._strip_markdown_inline(m) for m in matches]

    @staticmethod
    def _update_manual_tasks(
        project_dir: Path, items: List[str], plan_filename: str
    ) -> None:
        """미완료 체크박스를 MANUAL_TASKS.md로 이관"""
        manual_path = project_dir / "MANUAL_TASKS.md"
        today = date.today().isoformat()

        if manual_path.exists():
            existing = manual_path.read_text(encoding="utf-8")
        else:
            existing = ""

        # 중복 체크: 이미 이 plan에서 이관된 항목이 있으면 스킵
        if f"from: {plan_filename}" in existing:
            return

        # 새 항목 생성
        new_lines = []
        for item in items:
            new_lines.append(f"- [ ] {item} — from: {plan_filename} ({today})")

        if not existing:
            # 파일 신규 생성
            content = (
                "# MANUAL_TASKS\n\n"
                "> 자동화가 어렵거나 사람의 판단이 필요한 수동 작업 목록\n\n"
                "## 미완료\n\n"
                + "\n".join(new_lines) + "\n\n"
                "## 완료\n"
            )
            manual_path.write_text(content, encoding="utf-8")
        else:
            # 기존 파일의 ## 미완료 섹션 직후에 삽입
            lines = existing.splitlines()
            insert_idx = None
            for i, line in enumerate(lines):
                if line.strip() == "## 미완료":
                    insert_idx = i + 1
                    # 빈 줄 건너뜀
                    while insert_idx < len(lines) and lines[insert_idx].strip() == "":
                        insert_idx += 1
                    break
            if insert_idx is not None:
                for j, item_line in enumerate(new_lines):
                    lines.insert(insert_idx + j, item_line)
                manual_path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _extract_plan_title(content: str) -> str:
        """첫 번째 # 헤더에서 제목 추출"""
        match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "Unknown Plan"

    @staticmethod
    def _resolve_project_dir(plan_path: str) -> Optional[Path]:
        """plan 경로에서 프로젝트 디렉토리 추론

        - docs/plan 패턴 감지 → plan 디렉토리의 3단계 위 (file → plan → docs → project_root)
        - 패턴 불일치 시 파일 기준 상위 3단계 fallback
        """
        p = Path(plan_path).resolve()
        parts = p.parts
        for i, part in enumerate(parts):
            if part == "plan" and i > 0 and parts[i - 1] == "docs":
                # .worktrees 포함 시 .worktrees 직전 경로를 project root로 사용
                j = parts.index(".worktrees") if ".worktrees" in parts[:i - 1] else None
                project_root = Path(*parts[:j]) if j is not None else Path(*parts[:i - 1])
                if project_root.exists():
                    return project_root
        # fallback: 파일 기준 상위 3단계
        try:
            candidate = p.parent.parent.parent
            if candidate.exists():
                return candidate
        except Exception:
            pass
        return None

    async def _archive_plan(self, plan_path: str, content: str) -> tuple[Path, Optional[Path]]:
        """공통 archive 로직으로 plan/_todo를 이동한다.

        Returns:
            (archive_path, todo_archive_path) — todo_archive_path는 companion _todo.md가 없으면 None
        """
        try:
            archive_path, todo_archive_path, _ = await archive_plan_bundle(
                plan_path=plan_path,
                content=content,
                find_todo_file=self._find_todo_file,
            )
            return archive_path, todo_archive_path
        except PathRuleError as path_err:
            raise ValueError(str(path_err)) from path_err

    @staticmethod
    def _todo_line_matches_plan(line: str, plan_title: str, plan_path: Path | None = None) -> bool:
        """Return True only for the TODO checkbox item for this completed plan."""
        checkbox_match = re.match(r'^\s*[-*]\s*\[[ xX→]\]\s*(.+?)\s*$', line)
        if not checkbox_match:
            return False

        body = checkbox_match.group(1).strip()
        normalized_body = body.replace("\\", "/")

        if plan_path is not None:
            plan_path_text = str(plan_path).replace("\\", "/")
            path_tokens = {
                plan_path_text,
                plan_path.as_posix(),
                plan_path.name,
            }
            if any(token and token in normalized_body for token in path_tokens):
                return True
            stem_pattern = rf'(?<![A-Za-z0-9_-]){re.escape(plan_path.stem)}(?![A-Za-z0-9_-])'
            if re.search(stem_pattern, normalized_body):
                return True

        title_patterns = [
            rf'^{re.escape(plan_title)}$',
            rf'^{re.escape(plan_title)}\s+\(',
            rf'^{re.escape(plan_title)}\s+\[',
            rf'^\*\*{re.escape(plan_title)}\*\*(?:\s|$)',
        ]
        return any(re.search(pattern, body) for pattern in title_patterns)

    @classmethod
    def _update_todo_done(cls, project_dir: Path, plan_title: str, plan_path: Path | None = None) -> None:
        """plans ledger TODO에서 해당 plan 항목 제거, plans DONE 상단에 추가"""
        today = date.today().isoformat()
        ledger_paths = resolve_plans_ledger_paths(project_dir)

        # TODO.md: completed plan에 해당하는 체크박스 줄만 제거
        todo_path = ledger_paths.todo_path
        if todo_path.exists():
            lines = todo_path.read_text(encoding="utf-8").splitlines(keepends=True)
            filtered = [
                l for l in lines
                if not cls._todo_line_matches_plan(l, plan_title, plan_path)
            ]
            if len(filtered) < len(lines):
                todo_path.write_text("".join(filtered), encoding="utf-8")

        # DONE.md 상단에 추가
        done_path = ledger_paths.done_path
        done_path.parent.mkdir(parents=True, exist_ok=True)
        new_entry = f"- [x] {today}: {plan_title}\n"

        if done_path.exists():
            existing = done_path.read_text(encoding="utf-8")
            header_match = re.match(r'(#[^\n]+\n\n?)', existing)
            if header_match:
                pos = header_match.end()
                done_path.write_text(existing[:pos] + new_entry + existing[pos:], encoding="utf-8")
            else:
                done_path.write_text(new_entry + existing, encoding="utf-8")
        else:
            done_path.write_text(f"# DONE (최근 20개)\n\n{new_entry}", encoding="utf-8")

    @staticmethod
    def _archive_done_if_needed(done_path: Path) -> Optional[Path]:
        """DONE.md 항목 5개 초과 시 월별 아카이브"""
        if not done_path.exists():
            return None

        content = done_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        item_lines = [l for l in lines if re.match(r'^-\s*\[', l)]

        if len(item_lines) <= 5:
            return None

        keep = item_lines[:5]
        overflow = item_lines[5:]

        today = date.today()
        archive_dir = done_path.parent / "history"
        archive_dir.mkdir(parents=True, exist_ok=True)
        week_str = f"{today.year}-W{today.isocalendar()[1]:02d}"
        archive_path = archive_dir / f"DONE-{week_str}.md"

        if archive_path.exists():
            archive_path.write_text(
                archive_path.read_text(encoding="utf-8") + "".join(overflow),
                encoding="utf-8"
            )
        else:
            archive_path.write_text(
                f"# DONE Archive {week_str}\n\n" + "".join(overflow),
                encoding="utf-8"
            )

        # DONE.md 갱신 (최근 5개만 유지)
        header_match = re.match(r'(#[^\n]+\n\n?)', content)
        header = header_match.group(1) if header_match else "# DONE (최근 20개)\n\n"
        done_path.write_text(header + "".join(keep), encoding="utf-8")
        return archive_path

    @staticmethod
    def _ownership_snapshot_dir() -> Path:
        """runner dirty ownership snapshot 저장 디렉토리."""
        return PROJECT_ROOT / "logs" / "dev_runner" / "ownership"

    @classmethod
    def _ownership_snapshot_path(cls, runner_id: str) -> Path:
        return cls._ownership_snapshot_dir() / f"{runner_id}.json"

    @staticmethod
    def _normalize_ownership_key(path: Path, project_dir: Path) -> Optional[str]:
        try:
            rel = path.resolve(strict=False).relative_to(project_dir.resolve(strict=False))
        except Exception:
            return None
        return str(rel).replace("\\", "/").casefold()

    @classmethod
    def _load_runner_dirty_snapshot(cls, runner_id: Optional[str]) -> dict[str, set[str]]:
        if not runner_id:
            return {"dirty_files": set(), "owned_files": set(), "clean_at_start_files": set()}

        snapshot_path = cls._ownership_snapshot_path(runner_id)
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"runner ownership snapshot not found: {runner_id}") from exc
        except Exception as exc:
            raise ValueError(f"runner ownership snapshot unreadable: {snapshot_path}: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"runner ownership snapshot invalid: {snapshot_path}")
        dirty_files = payload.get("dirty_files", [])
        owned_files = payload.get("owned_files", [])
        clean_at_start_files = payload.get("clean_at_start_files", [])
        if not isinstance(dirty_files, list) or not isinstance(owned_files, list) or not isinstance(clean_at_start_files, list):
            raise ValueError(f"runner ownership snapshot invalid: {snapshot_path}")
        capture_error = payload.get("capture_error") if isinstance(payload, dict) else None
        if capture_error:
            raise ValueError(f"runner ownership snapshot capture failed: {capture_error}")
        return {
            "dirty_files": {
                str(item).replace("\\", "/").casefold()
                for item in dirty_files
                if isinstance(item, str) and item.strip()
            },
            "owned_files": {
                str(item).replace("\\", "/").casefold()
                for item in owned_files
                if isinstance(item, str) and item.strip()
            },
            "clean_at_start_files": {
                str(item).replace("\\", "/").casefold()
                for item in clean_at_start_files
                if isinstance(item, str) and item.strip()
            },
        }

    @classmethod
    def _validate_runner_ownership(
        cls,
        project_dir: Optional[Path],
        files_to_check: List[Path],
        runner_id: Optional[str],
    ) -> Optional[str]:
        if not runner_id or not project_dir:
            return None

        snapshot = cls._load_runner_dirty_snapshot(runner_id)
        dirty_files = snapshot["dirty_files"]
        owned_files = snapshot["owned_files"]
        if not dirty_files and not owned_files:
            return None

        normalized_project_dir = project_dir.resolve(strict=False)
        pre_dirty_conflicts: list[str] = []
        unowned_conflicts: list[str] = []
        for target in files_to_check:
            key = cls._normalize_ownership_key(target, normalized_project_dir)
            if not key:
                continue
            if key in dirty_files:
                pre_dirty_conflicts.append(str(target))
                continue
            if owned_files and key not in owned_files:
                unowned_conflicts.append(str(target))

        if pre_dirty_conflicts:
            joined = ", ".join(pre_dirty_conflicts)
            return (
                f"runner ownership guard blocked auto-done: pre-dirty file(s) detected for runner "
                f"{runner_id}: {joined}"
            )
        if unowned_conflicts:
            joined = ", ".join(unowned_conflicts)
            return (
                f"runner ownership guard blocked auto-done: unowned file(s) detected for runner "
                f"{runner_id}: {joined}"
            )
        return None

    @classmethod
    def _collect_current_dirty_keys(cls, project_dir: Path) -> set[str]:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            raise ValueError(f"runner residue guard git status failed: {result.returncode}")

        dirty_keys: set[str] = set()
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            raw = line[3:].strip() if len(line) >= 3 else line.strip()
            if " -> " in raw:
                raw = raw.split(" -> ", 1)[1].strip()
            if raw:
                dirty_keys.add(raw.replace("\\", "/").casefold())
        return dirty_keys

    @classmethod
    def _validate_runner_residue(
        cls,
        project_dir: Optional[Path],
        runner_id: Optional[str],
    ) -> Optional[str]:
        if not runner_id or not project_dir:
            return None
        if not (project_dir / ".git").exists():
            return None

        try:
            snapshot = cls._load_runner_dirty_snapshot(runner_id)
        except ValueError as exc:
            return f"runner residue guard blocked auto-done: {exc}"

        current_dirty = cls._collect_current_dirty_keys(project_dir)
        stray_dirty = sorted(current_dirty - snapshot["dirty_files"] - snapshot["owned_files"])
        if not stray_dirty:
            return None

        return (
            f"runner residue guard blocked auto-done: stray dirty file(s) detected for runner "
            f"{runner_id}: {', '.join(stray_dirty)}"
        )

    async def _git_commit(
        self,
        project_dir: Optional[Path],
        files_to_add: List[Path],
        commit_msg: str,
        runner_id: Optional[str] = None,
    ) -> str:
        """git add + commit script 호출.

        Windows에서는 commit.ps1을 우선 사용하고, 각 subprocess의 non-zero
        종료 코드는 run_done 실패로 전파한다.
        """
        commit_command = self._resolve_commit_command(commit_msg)

        ownership_error = self._validate_runner_ownership(project_dir, files_to_add, runner_id)
        if ownership_error:
            return ownership_error

        return await commit_files_by_git_root(
            files_to_add=files_to_add,
            default_root=project_dir,
            commit_command=commit_command,
            decode_output=self._decode_subprocess_output,
        )

    @classmethod
    def _resolve_commit_command(cls, commit_msg: str) -> list[str]:
        if os.name == "nt" and cls.COMMIT_PS1.exists():
            return [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(cls.COMMIT_PS1),
                commit_msg,
            ]
        if cls.COMMIT_SH.exists():
            return ["bash", str(cls.COMMIT_SH), commit_msg]
        if cls.COMMIT_PS1.exists():
            return [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(cls.COMMIT_PS1),
                commit_msg,
            ]
        raise FileNotFoundError(f"commit script not found: {cls.COMMIT_PS1} or {cls.COMMIT_SH}")

    @staticmethod
    def _decode_subprocess_output(output) -> str:
        if not output:
            return ""
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output)

    async def run_done(self, plan_path: str, runner_id: Optional[str] = None) -> dict:
        """Python 네이티브 plan 완료 처리 (아카이브, TODO→DONE, git commit)"""
        path = Path(plan_path)
        if not path.exists():
            return {"success": False, "message": f"Plan file not found: {plan_path}", "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

        pre_progress = self.get_plan_progress(path)
        pre_status = self.get_plan_status(path)

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            title = self._extract_plan_title(content)
            total = pre_progress.total

            # 0. 사전 검증 (구현완료 설정 전 게이트)
            precondition_errors = validate_done_preconditions(plan_path, content)
            if precondition_errors:
                raise ValueError(f"done 사전 검증 실패: {'; '.join(precondition_errors)}")

            # 1. 헤더/푸터 갱신
            updated_content = update_plan_headers(content, total)

            # 2. 미완료 체크박스 → MANUAL_TASKS.md 이관
            project_dir = self._resolve_project_dir(plan_path)
            pending_items = self._extract_pending_checkboxes(updated_content)
            has_manual = False
            if pending_items and project_dir:
                self._update_manual_tasks(project_dir, pending_items, path.name)
                has_manual = True

            archive_path = resolve_archive_target_or_raise(plan_path)
            todo_file = self._find_todo_file(path)
            todo_archive_path = archive_path.parent / todo_file.name if todo_file and todo_file.exists() else None
            ownership_targets: list[Path] = [path, archive_path]
            if todo_file and todo_file.exists():
                ownership_targets.append(todo_file)
                if todo_archive_path:
                    ownership_targets.append(todo_archive_path)
            if project_dir:
                ledger_paths = resolve_plans_ledger_paths(project_dir)
                ownership_targets.extend([
                    ledger_paths.todo_path,
                    ledger_paths.done_path,
                    ledger_paths.done_history_path,
                ])
                if has_manual:
                    ownership_targets.append(project_dir / "MANUAL_TASKS.md")

            residue_error = self._validate_runner_residue(project_dir, runner_id)
            if residue_error:
                return {
                    "success": False,
                    "message": residue_error,
                    "reason": "residue_guard",
                    "output": None,
                    "remaining_tasks": pre_progress.total - pre_progress.done,
                    "total_tasks": pre_progress.total,
                    "plan_status": pre_status,
                }
            ownership_error = self._validate_runner_ownership(project_dir, ownership_targets, runner_id)
            if ownership_error:
                return {
                    "success": False,
                    "message": ownership_error,
                    "reason": "ownership_guard",
                    "output": None,
                    "remaining_tasks": pre_progress.total - pre_progress.done,
                    "total_tasks": pre_progress.total,
                    "plan_status": pre_status,
                }

            # 3. 아카이브 이동
            archive_path, todo_archive_path = await self._archive_plan(plan_path, updated_content)

            # 4. TODO.md / DONE.md 업데이트
            if project_dir:
                self._update_todo_done(project_dir, title, path)
                ledger_paths = resolve_plans_ledger_paths(project_dir)
                done_path = ledger_paths.done_path
                done_history_path = self._archive_done_if_needed(done_path)

            # 5. git commit
            files_to_commit: List[Path] = [path, archive_path]
            if todo_archive_path:
                files_to_commit.append(path.parent / todo_archive_path.name)
                files_to_commit.append(todo_archive_path)
            if project_dir:
                files_to_commit += [
                    ledger_paths.todo_path,
                    done_path,
                ]
                if done_history_path:
                    files_to_commit.append(done_history_path)
                if has_manual:
                    files_to_commit.append(project_dir / "MANUAL_TASKS.md")
            commit_output = await self._git_commit(
                project_dir, files_to_commit, f"docs: {title} 완료 처리", runner_id=runner_id
            )

            self.sync_plans()

            # DB 기록: plan_records에 archive 완료 기록
            try:
                from app.database import SessionLocal
                from app.modules.dev_runner.services.plan_record_service import PlanRecordService
                with SessionLocal() as db:
                    svc = PlanRecordService(db)
                    svc.update_status(plan_path, "completed")
                    try:
                        _raw = Path(archive_path).read_text(encoding="utf-8")
                    except Exception:
                        _raw = None
                    svc.mark_archived(plan_path, str(archive_path), raw_content=_raw)
                    db.commit()
            except Exception as db_err:
                logger.warning(f"plan_record DB 기록 실패 (무시): {db_err}")

            # Redis pub/sub 트리거: plan:archived 채널에 아카이브 경로 발행
            try:
                _publish_log("plan", f"archived: {archive_path}")
                r = _get_redis()
                if r:
                    r.publish("plan:archived", str(archive_path))
            except Exception as redis_err:
                logger.debug(f"plan:archived publish 실패 (무시): {redis_err}")

            return {
                "success": True,
                "message": "완료 처리 성공",
                "output": f"아카이브: {archive_path}\n{commit_output}",
                "remaining_tasks": pre_progress.total - pre_progress.done,
                "total_tasks": pre_progress.total,
                "plan_status": pre_status,
            }

        except Exception as e:
            logger.error(f"run_done 실패: {e}")
            return {"success": False, "message": str(e), "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

    # ========== 일괄 완료 ==========

    def verify_completion(self, plan_path: Path) -> "VerifyResult":
        """코드베이스와 계획서를 대조하여 완료 여부 판정"""
        from app.modules.dev_runner.schemas import VerifyResult

        # archive 경로이면 즉시 can_done=False
        if "archive" in str(plan_path):
            return VerifyResult(total=0, verified=0, unverified_items=[], percent=0.0, can_done=False)

        detail = self.parse_plan_items(plan_path)

        # 체크박스가 없는 문서(분석서, 보고서 등): 아카이브 허용
        if not detail.phases or all(len(p.items) == 0 for p in detail.phases):
            progress = self.get_plan_progress(plan_path)
            if progress.total == 0:
                return VerifyResult(total=0, verified=0, unverified_items=[], percent=100.0, can_done=True)

        total = 0
        verified = 0
        unverified_items: list[str] = []

        def process_item(item) -> None:
            nonlocal total, verified
            total += 1
            if item.file_path:
                if Path(item.file_path).exists():
                    verified += 1
                else:
                    unverified_items.append(item.text)
            else:
                if item.checked:
                    verified += 1
                else:
                    unverified_items.append(item.text)
            for child in item.children:
                process_item(child)

        for phase in detail.phases:
            for item in phase.items:
                process_item(item)

        percent = round(verified / total * 100, 1) if total > 0 else 0.0
        can_done = total > 0 and verified == total

        return VerifyResult(
            total=total,
            verified=verified,
            unverified_items=unverified_items,
            percent=percent,
            can_done=can_done,
        )

    # _check_branch_exists, _check_worktree_exists → git_utils로 이전 (safe.directory 방어 포함)
    def _check_branch_exists(self, branch: str) -> bool: return check_branch_exists(branch)
    def _check_worktree_exists(self, worktree: str) -> bool: return check_worktree_exists(worktree)

    def _can_done(self, plan: PlanFileResponse) -> bool:
        """plan이 done 처리 가능한지 판단 — 체크박스 전체 완료 OR 상태 헤더 완료 계열 OR 체크박스 없음"""
        if "archive" in plan.path:
            return False

        # worktree/branch 존재 여부 확인 — 살아있으면 done 불가
        try:
            p = Path(plan.path)
            if p.exists():
                top20 = ""
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        if i >= 20:
                            break
                        top20 += line
                        branch_match = re.search(r'^>\s*branch:\s*(.+)', top20, re.MULTILINE)
                        if branch_match and self._check_branch_exists(branch_match.group(1).strip()):
                            return False

                        wt_match = re.search(r'^>\s*worktree:\s*(.+)', top20, re.MULTILINE)
                        if wt_match and self._check_worktree_exists(wt_match.group(1).strip()):
                            return False

                # branch/worktree 없이 worktree-owner만 잔존한 경우 방어
                if not branch_match and not worktree_match:
                    owner_match = re.search(r'^>\s*worktree-owner:\s*(.+)', top20, re.MULTILINE)
                    if owner_match:
                        return False
        except Exception:
            pass  # 파일 읽기 실패 시 기존 로직으로 진행

        progress = plan.progress
        if progress is None:
            progress = self.get_plan_progress(Path(plan.path))
        # 가이드 문서는 done 불가
        if plan.status == "가이드":
            return False
        # 체크박스 없는 문서(분석서, 보고서 등): 아카이브 허용
        if progress.total == 0:
            return True
        if progress.total > 0 and progress.done == progress.total:
            return True
        if plan.status in self._DONE_STATUSES:
            return True
        return False

    async def batch_done(self) -> dict:
        """완료 가능한 plan을 일괄 done 처리"""
        all_plans = self.list_plans(include_ignored=True)
        targets = [p for p in all_plans if self._can_done(p)]

        if not targets:
            return {"total": 0, "success": 0, "failed": 0, "results": []}

        results = []
        success_count = 0
        failed_count = 0

        filenames = ",".join(p.filename for p in targets)
        _publish_log("BATCH", f"PLAN_LIST {filenames}")

        for plan in targets:
            _publish_log("BATCH", f"PLAN_START {plan.filename}")
            result = await self.run_done(plan.path)
            results.append({
                "path": plan.path,
                "filename": plan.filename,
                "success": result["success"],
                "message": result["message"],
            })
            if result["success"]:
                success_count += 1
                _publish_log("BATCH", f"PLAN_DONE {plan.filename}")
            else:
                failed_count += 1
                _publish_log("BATCH", f"PLAN_FAILED {plan.filename}")  # 버그 수정: PLAN_DONE → PLAN_FAILED
                _publish_log("ERROR", f"{plan.filename}: {result['message']}")

        _publish_log("INFO", f"일괄완료 종료: {success_count}개 성공, {failed_count}개 실패")

        return {
            "total": len(targets),
            "success": success_count,
            "failed": failed_count,
            "results": results,
        }

    # ========== 상태 변경 ==========

    def set_plan_status(self, plan_path: str, new_status: str) -> bool:
        """plan 파일의 '> 상태: ...' 줄을 변경 (없으면 제목 아래에 추가)"""
        path = Path(plan_path)
        if not path.exists():
            return False

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        status_pattern = re.compile(r"^>\s*상태:\s*(.+)")
        found = False

        for i, line in enumerate(lines):
            if status_pattern.match(line):
                lines[i] = f"> 상태: {new_status}\n"
                found = True
                break

        if not found:
            # 제목(#) 바로 아래에 삽입
            for i, line in enumerate(lines):
                if line.startswith("#"):
                    lines.insert(i + 1, f"\n> 상태: {new_status}\n")
                    found = True
                    break

        if found:
            path.write_text("".join(lines), encoding="utf-8")
            self.invalidate_plans_cache()
        return found

    # ========== 동기화 ==========

    def sync_plans(self) -> dict:
        """plan 동기화 — 이전 상태와 비교하여 변경 요약 반환"""
        # 이전 상태 스냅샷 (활성 plan만 — archive는 sync 대상 아님)
        old_plans = {p.path: p for p in self.list_plans()}
        old_keys = set(old_plans.keys())
        previous_registered_paths = list(self._registered_paths)

        # 디스크에서 다시 스캔 (캐시 무효화)
        self._load_registered_paths()
        if not self._registered_paths and previous_registered_paths and old_plans:
            # TestClient and long-running API sessions may hold a warm in-memory
            # registry while a temporary/empty config path is patched in later.
            # Preserve the active registry instead of reporting a false zero sync.
            self._registered_paths = previous_registered_paths
        self.invalidate_plans_cache()
        new_plans_list = self.list_plans()
        new_plans = {p.path: p for p in new_plans_list}
        new_keys = set(new_plans.keys())

        added = len(new_keys - old_keys)
        removed = len(old_keys - new_keys)

        updated = 0
        for key in old_keys & new_keys:
            old_p = old_plans[key]
            new_p = new_plans[key]
            old_done = old_p.progress.done if old_p.progress else 0
            old_total = old_p.progress.total if old_p.progress else 0
            new_done = new_p.progress.done if new_p.progress else 0
            new_total = new_p.progress.total if new_p.progress else 0
            if (old_p.status != new_p.status
                    or old_done != new_done
                    or old_total != new_total):
                updated += 1

        return {
            "synced": len(new_plans_list),
            "added": added,
            "removed": removed,
            "updated": updated,
        }

    # ========== 외부 경로 추출 ==========

    def get_ignored_plan_paths(self) -> List[str]:
        """UI와 동일한 기준으로 무시 대상 plan 절대경로 리스트 반환

        수동 목록(ignored_plans.json) + 상태 완료/보류 + 체크박스 전체 완료
        """
        ignored = set(self._ignored_plans)

        for entry in self._registered_paths:
            p = Path(entry["path"])
            if not p.exists():
                continue
            files = p.glob("*.md") if p.is_dir() else [p]
            for plan_file in files:
                if not plan_file.is_file():
                    continue
                resolved = str(plan_file.resolve())
                if resolved in ignored:
                    continue
                status = self.get_plan_status(plan_file)
                progress = self.get_plan_progress(plan_file)
                if self._is_ignored_plan(plan_file, status, progress):
                    ignored.add(resolved)

        return list(ignored)

    def get_extra_plan_dirs(self) -> List[str]:
        """registered_paths 중 WTOOLS_BASE_DIR 하위가 아닌 폴더 경로만 반환"""
        wtools_prefix = str(config.WTOOLS_BASE_DIR.resolve())
        extra_dirs = []
        for entry in self._registered_paths:
            reg_path = entry["path"]
            p = Path(reg_path)
            if not p.is_dir():
                continue
            resolved = str(p.resolve())
            if not resolved.startswith(wtools_prefix):
                extra_dirs.append(resolved)
        return extra_dirs

    # ========== 등록 경로 관리 ==========

    def list_registered_paths(self) -> List[RegisteredPathResponse]:
        """등록된 경로 목록 조회 (타입 + plan_count + path_type 포함)"""
        result = []
        for entry in self._registered_paths:
            reg_path = entry["path"]
            path_type = entry.get("type", "plan")
            p = Path(reg_path)
            if p.is_dir():
                glob_fn = p.rglob if path_type == "archive" else p.glob
                plan_count = sum(
                    1 for f in glob_fn("*.md")
                    if f.stem.endswith("_todo")
                    or not (f.parent / (f.stem + "_todo.md")).exists()
                ) if p.exists() else 0
                result.append(RegisteredPathResponse(path=reg_path, type="folder", plan_count=plan_count, path_type=path_type))
            else:
                result.append(RegisteredPathResponse(path=reg_path, type="file", plan_count=1 if p.exists() else 0, path_type=path_type))
        return result

    def validate_path(self, path: str) -> bool:
        """경로 화이트리스트 검증"""
        path_obj = Path(path).resolve()
        path_str = str(path_obj)

        for allowed in config.ALLOWED_PATHS:
            if path_str.startswith(allowed):
                return True
        return False

    def update_plan_status(self, path: str, new_status: str) -> str:
        """plan 파일의 상태 필드를 업데이트한다.

        - 파일 상단 20줄에서 `> 상태: ...` 라인을 찾아 교체
        - 라인이 없으면 첫 번째 `#` 제목 다음 줄에 삽입
        - 허용 상태: plan lifecycle 표준 상태 및 예약대기
        """
        ALLOWED_STATUSES = [
            "초안", "검토대기", "예약대기", "검토완료", "구현중",
            "검증중", "수정필요", "테스트중", "머지대기",
            "통합테스트중", "구현완료", "완료", "보류",
        ]
        if new_status not in ALLOWED_STATUSES:
            raise ValueError(
                f"허용되지 않은 상태: '{new_status}'. 허용 목록: {ALLOWED_STATUSES}"
            )

        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        import re

        status_pattern = re.compile(r"^> 상태: .+")

        # 상단 20줄에서 `> 상태:` 라인 교체
        found = False
        for i, line in enumerate(lines[:20]):
            if status_pattern.match(line.rstrip("\n\r")):
                lines[i] = f"> 상태: {new_status}\n"
                found = True
                break

        if not found:
            # `> 상태:` 라인 없음 → 첫 번째 `#` 제목 다음 줄에 삽입
            for i, line in enumerate(lines):
                if line.startswith("#"):
                    lines.insert(i + 1, f"> 상태: {new_status}\n")
                    found = True
                    break

        if not found:
            # 제목도 없으면 파일 맨 앞에 삽입
            lines.insert(0, f"> 상태: {new_status}\n")

        file_path.write_text("".join(lines), encoding="utf-8")
        self.invalidate_plans_cache()
        return new_status

    def _insert_summary_to_plan(self, path: Path, summary_text: str) -> None:
        """plan 파일의 헤더 블록쿼트에 `> 요약:` 줄을 삽입(또는 교체)한다."""
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # 기존 `> 요약:` 줄 교체
        for i, line in enumerate(lines):
            if re.match(r'^>\s*요약:', line):
                lines[i] = f"> 요약: {summary_text}"
                path.write_text("\n".join(lines), encoding="utf-8")
                self.invalidate_plans_cache()
                return

        # 없으면 첫 번째 블록쿼트 줄 뒤에 삽입 (없으면 h1 제목 다음에 삽입)
        insert_idx = None
        for i, line in enumerate(lines):
            if line.startswith(">"):
                insert_idx = i + 1
                break
        if insert_idx is None:
            for i, line in enumerate(lines):
                if line.startswith("# "):
                    insert_idx = i + 1
                    break
        if insert_idx is None:
            insert_idx = 0
        lines.insert(insert_idx, f"> 요약: {summary_text}")
        path.write_text("\n".join(lines), encoding="utf-8")
        self.invalidate_plans_cache()

    async def generate_summary(self, path: Path, db) -> int:
        """plan 파일 내용을 LLM으로 요약하여 `> 요약:` 헤더에 삽입한다.

        Returns:
            LLMRequest.id (request_id)
        """
        from app.modules.claude_worker.services.llm_service import LLMService

        content = path.read_text(encoding="utf-8")
        prompt = (
            "다음 plan 문서를 읽고 1-2 문장으로 핵심 목적을 한국어로 요약해줘. "
            "코드블록 없이 일반 텍스트만 출력해.\n\n"
            f"{content[:3000]}"
        )

        llm_svc = LLMService(db)
        request = llm_svc.enqueue(
            caller_type="dev_runner",
            caller_id=str(path),
            prompt=prompt,
            requested_by="api",
            request_source="plan_summary",
            queue_name="utility",
        )
        db.commit()

        # 백그라운드에서 완료 후 plan 파일에 요약 삽입
        plan_path = path
        request_id = request.id
        plan_svc = self

        async def _write_back():
            import asyncio
            from app.database import SessionLocal
            for _ in range(60):  # 최대 5분 대기 (5초 x 60)
                await asyncio.sleep(5)
                with SessionLocal() as bg_db:
                    from app.modules.claude_worker.models.llm_request import LLMRequest
                    req = bg_db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
                    if req and req.status == "completed" and req.raw_response:
                        summary_text = req.raw_response.strip()
                        if summary_text:
                            plan_svc._insert_summary_to_plan(plan_path, summary_text)
                        return
                    if req and req.status in ("failed", "cancelled"):
                        return

        import asyncio
        asyncio.create_task(_write_back())

        return request_id


# 싱글톤 인스턴스
plan_service = PlanService()

__all__ = ['plan_service', 'PlanService']

