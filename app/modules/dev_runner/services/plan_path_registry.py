"""plan 경로 등록/제거, 무시 목록, JSON 저장/로드, 경로 검증 서비스"""

import json
import logging
import re
from pathlib import Path
from typing import Callable, List, Optional

from app.core.config import PROJECT_ROOT
from app.modules.dev_runner.config import config
from app.modules.dev_runner.schemas import RegisteredPathResponse
from app.modules.dev_runner.services.plan_path_helpers import (
    load_wtools_project_roots,
    iter_repo_plan_path_candidates,
    extract_repo_root_from_plan_path,
    backfill_dual_paths,
    canonicalize_wtools_legacy_common_path,
)
from app.shared.io import write_json_atomic

logger = logging.getLogger(__name__)


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


class PlanPathRegistry:
    """등록 경로 / 무시 목록 관리.

    책임:
    - registered_paths.json 로드/저장/마이그레이션
    - ignored_plans.json 로드/저장
    - 경로 추가/제거 (add_path, remove_path)
    - 무시 목록 추가/제거 (add_to_ignore, remove_from_ignore)
    - executor_service용 조회 (get_extra_plan_dirs, get_ignored_plan_paths)
    - 경로 화이트리스트 검증 (validate_path)

    캐시 무효화:
    - 경로 변경 시 _notify_mutation()으로 등록된 콜백 호출.
    - PlanScanner는 생성 후 register_mutation_callback(self.invalidate_plans_cache) 로 등록.
    """

    # 무시 기준 상태값 (plan_service에서 이전)
    _IGNORED_STATUSES = {"보류", "가이드"}
    _DONE_STATUSES = {"구현완료", "완료", "수정 완료", "배포완료", "수정완료"}

    def __init__(self):
        self._registered_paths: List[dict] = []  # {"path": str, "type": "plan"|"archive"}
        self._ignored_plans: List[str] = []
        self._mutation_callbacks: List[Callable] = []  # scanner cache 무효화 등
        self._migrate_to_registered_paths()
        self._load_registered_paths()
        self._load_ignored_plans()

    # ========== 콜백 (캐시 무효화) ==========

    def register_mutation_callback(self, cb: Callable) -> None:
        """경로 변경 시 호출할 콜백 등록.

        PlanScanner가 생성 후 ``register_mutation_callback(self.invalidate_plans_cache)``
        로 등록하면, add_path / remove_path / add_to_ignore / remove_from_ignore 시
        자동으로 scanner 캐시가 무효화된다.
        """
        if cb not in self._mutation_callbacks:
            self._mutation_callbacks.append(cb)

    def _notify_mutation(self) -> None:
        """등록된 콜백 전체 호출 (경로 변경 후 내부 호출)"""
        for cb in self._mutation_callbacks:
            try:
                cb()
            except Exception:
                pass  # 콜백 실패가 경로 변경 자체를 막아선 안 됨

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
        """기존 등록 목록에서 docs <-> worktree 상호 보완 경로를 backfill한다."""
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

    # ========== 무시 목록 관리 ==========

    def add_to_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에 추가"""
        resolved = str(Path(plan_path).resolve())
        if resolved not in self._ignored_plans:
            self._ignored_plans.append(resolved)
            self._save_ignored_plans()
            self._notify_mutation()
            return True
        return False

    def remove_from_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에서 제거"""
        resolved = str(Path(plan_path).resolve())
        if resolved in self._ignored_plans:
            self._ignored_plans.remove(resolved)
            self._save_ignored_plans()
            self._notify_mutation()
            return True
        return False

    # ========== 등록 경로 관리 ==========

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
            self._notify_mutation()
            return True
        return False

    def remove_path(self, plan_path: str) -> bool:
        """등록 경로 제거"""
        resolved = str(Path(plan_path).resolve())
        for i, entry in enumerate(self._registered_paths):
            if entry["path"] == resolved:
                self._registered_paths.pop(i)
                self._save_registered_paths()
                self._notify_mutation()
                return True
        return False

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

    # ========== 외부 경로 추출 ==========

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

    def get_ignored_plan_paths(self) -> List[str]:
        """UI와 동일한 기준으로 무시 대상 plan 절대경로 리스트 반환.

        수동 목록(ignored_plans.json) + 상태 완료/보류
        (체크박스 완료 여부는 visibility에 영향 없음 — _is_ignored_plan 참고)

        Note:
            Phase 2에서 PlanScanner 추출 후, get_plan_status / _is_ignored_plan 을
            scanner 메서드로 교체 예정. 현재는 경량 inline 파싱으로 대체.
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
                status = self._read_plan_status(plan_file)
                if self._is_ignored_by_status(resolved, status):
                    ignored.add(resolved)

        return list(ignored)

    # ========== 경로 검증 ==========

    def validate_path(self, path: str) -> bool:
        """경로 화이트리스트 검증"""
        path_obj = Path(path).resolve()
        path_str = str(path_obj)

        for allowed in config.ALLOWED_PATHS:
            if path_str.startswith(allowed):
                return True
        return False

    # ========== 내부 헬퍼 (get_ignored_plan_paths 전용) ==========

    def _is_ignored_by_status(self, resolved_path: str, status: str) -> bool:
        """상태/무시목록 기준으로 plan 무시 여부 판단.

        plan_service._is_ignored_plan 과 동일 로직.
        Phase 2에서 PlanScanner._is_ignored_plan 으로 교체 예정.
        """
        if resolved_path in self._ignored_plans:
            return True
        if status in self._IGNORED_STATUSES:
            return True
        if status in self._DONE_STATUSES:
            return True
        return False

    @staticmethod
    def _strip_markdown_inline(text: str) -> str:
        """마크다운 인라인 스타일 제거 (**굵게**, *기울임*, ~~취소선~~, `코드`)"""
        return re.sub(r'[*_~`]+', '', text).strip()

    def _read_plan_status(self, path: Path) -> str:
        """plan 상태 파싱 (> 상태: ...) — get_ignored_plan_paths 전용.

        plan_service.get_plan_status 와 동일 로직.
        Phase 2에서 PlanScanner.get_plan_status 로 교체 예정.
        """
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


# 싱글톤
plan_path_registry = PlanPathRegistry()
