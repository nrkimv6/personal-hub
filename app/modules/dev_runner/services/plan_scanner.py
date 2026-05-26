"""plan 파일 스캔, 파싱, 체크박스 추출, 캐시, 진행률/상태 조회 서비스"""

import re
import time
from pathlib import Path
from typing import List, Optional

from app.modules.dev_runner.schemas import (
    PlanDetailResponse,
    PlanFileResponse,
    PlanItemResponse,
    PlanPhaseResponse,
    PlanProgressResponse,
)
from app.modules.dev_runner.services.plan_path_helpers import (
    extract_repo_root_from_plan_path,
    dedupe_prefer_worktree,
)
from app.modules.dev_runner.services.plan_item_state import (
    CHECKBOX_MARKER_PATTERN,
    checkbox_state,
    is_done_marker,
    task_key,
    task_text_hash,
)

import logging

logger = logging.getLogger(__name__)


class PlanScanner:
    """plan 파일 스캔/파싱/캐시 관리.

    책임:
    - 등록 경로 대상 파일시스템 스캔 (_scan_all_plans, _scan_plan_dir)
    - plan 파일 파싱 (get_plan_status, get_plan_progress, parse_plan_items)
    - 결과 캐시 (list_plans, invalidate_plans_cache)
    - 무시 대상 판단 (_is_ignored_plan)
    - 유틸리티 (parse_plan_items, _extract_summary, _extract_pending_checkboxes 등)

    의존성:
    - PlanPathRegistry: 등록 경로/무시 목록 조회. __init__에서 mutation 콜백 등록.
    """

    # 자동 무시 대상 상태 (정확히 일치해야 함)
    _IGNORED_STATUSES = {"보류", "가이드"}
    # 완료 계열 상태 (아카이브 허용 + 목록 숨김)
    _DONE_STATUSES = {"구현완료", "완료", "수정 완료", "배포완료", "수정완료"}
    # plans 캐시 TTL (초) — runner 종료 트리거 없이도 stale 캐시가 자동 갱신됨
    _PLANS_CACHE_TTL = 60

    def __init__(self, registry):
        """
        Args:
            registry: PlanPathRegistry 인스턴스 — 등록 경로/무시 목록 제공
        """
        self.registry = registry

        # archive 캐시: {dir_path: {"mtime": float, "results": [PlanFileResponse]}}
        self._archive_cache: dict = {}
        # plan 전체 목록 캐시 (startup 시 빌드, mutation 시 무효화)
        self._plans_cache: Optional[List[PlanFileResponse]] = None
        self._plans_cache_with_ignored: Optional[List[PlanFileResponse]] = None
        self._plans_cache_time: float = 0

        # registry 경로 변경 시 캐시 자동 무효화
        self.registry.register_mutation_callback(self.invalidate_plans_cache)

    # ========== 캐시 관리 ==========

    def invalidate_plans_cache(self):
        """plan 목록 캐시 무효화 — mutation 후 호출"""
        self._plans_cache = None
        self._plans_cache_with_ignored = None
        self._plans_cache_time = 0

    # ========== plan 목록 ==========

    def list_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """
        plan 목록 조회 — 캐시 우선, 미스 시 파일시스템 스캔

        모든 경로를 동등하게 취급 (고정/외부 구분 없음)
        """
        # TTL 만료 시 캐시 무효화 (runner 종료 트리거 없는 경우 fallback)
        if self._plans_cache is not None and time.monotonic() - self._plans_cache_time > self._PLANS_CACHE_TTL:
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

    # ========== 파일시스템 스캔 ==========

    def _scan_all_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """실제 파일시스템 스캔 (캐시 미스 시 호출).

        같은 (repo_root, filename) 조합이 docs와 .worktrees/plans/docs 양쪽에 있으면
        worktree 경로를 우선 노출하고 docs 경로는 제거한다.
        """
        seen: set = set()
        raw_results: List[PlanFileResponse] = []

        for entry in self.registry._registered_paths:
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
                        except Exception:
                            summary = None
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
                            )
                        )

        results = self._dedupe_prefer_worktree(raw_results)
        results.sort(key=lambda x: x.filename, reverse=True)
        return results

    @staticmethod
    def _dedupe_prefer_worktree(results: List[PlanFileResponse]) -> List[PlanFileResponse]:
        """같은 (repo_root, filename)이면 worktree 경로를 남기고 docs 경로를 제거한다."""
        return dedupe_prefer_worktree(results)

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
            except Exception:
                summary = None

            item = PlanFileResponse(
                path=str(plan_file),
                filename=plan_file.name,
                status=status,
                progress=progress,
                source=source,
                ignored=is_ignored,
                path_type=path_type,
                summary=summary,
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

    # ========== 무시 판단 ==========

    def _is_ignored_plan(self, path: Path, status: str, progress: Optional[PlanProgressResponse] = None) -> bool:
        """plan이 무시 대상인지 판단"""
        # 수동 무시 목록
        if str(path.resolve()) in self.registry._ignored_plans:
            return True
        # 보류 상태
        if status in self._IGNORED_STATUSES:
            return True
        # 완료 계열 상태
        if status in self._DONE_STATUSES:
            return True
        # 체크박스 완료 여부는 visibility에 영향 주지 않음
        # — /done 또는 수동 아카이브를 통해서만 목록에서 제거됨
        return False

    # ========== 경로 유틸리티 ==========

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
            checkbox_pattern = rf"^[ \t]*(?:\d+\.\s+(?:[-*]\s*)?|[-*]+\s*)\[{CHECKBOX_MARKER_PATTERN}\]"
            matches = re.findall(checkbox_pattern, content, re.MULTILINE)

            total = len(matches)
            done = sum(1 for m in matches if is_done_marker(m))
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
        top_level_ordinal = 0
        child_ordinals: dict[int, int] = {}

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
                top_level_ordinal = 0
                child_ordinals = {}
                continue

            # 번호 체크박스 (상위): 1. [ ], 1. [/], 1. [x], 1. [→TODO]
            num_match = re.match(rf'^(\d+)\.\s*\[{CHECKBOX_MARKER_PATTERN}\]\s*(.*)', line)
            if num_match:
                text = num_match.group(3).strip()
                marker = num_match.group(2)
                top_level_ordinal += 1
                ordinal = str(top_level_ordinal)
                fp = file_path_pattern.search(text)
                item = PlanItemResponse(
                    level=0,
                    text=text,
                    checked=is_done_marker(marker),
                    marker=marker,
                    state=checkbox_state(marker),
                    phase_name=current_phase_name,
                    item_ordinal=ordinal,
                    text_hash=task_text_hash(text),
                    task_key=task_key(current_phase_name, ordinal, text),
                    file_path=fp.group(1) if fp else None,
                )
                current_items.append(item)
                current_parent = item
                child_ordinals[id(item)] = 0
                continue

            # 대시 체크박스: - [ ], - [/], - [x], - [→TODO] (최상위 + 하위 모두)
            dash_match = re.match(rf'^(\s*)-\s*\[{CHECKBOX_MARKER_PATTERN}\]\s*(.*)', line)
            if dash_match:
                indent = len(dash_match.group(1))
                text = dash_match.group(3).strip()
                marker = dash_match.group(2)
                fp = file_path_pattern.search(text)
                if indent > 0 and current_parent is not None:
                    # 들여쓰기 있음 → 하위 항목
                    child_ordinals[id(current_parent)] = child_ordinals.get(id(current_parent), 0) + 1
                    ordinal = f"{current_parent.item_ordinal}.{child_ordinals[id(current_parent)]}"
                    child = PlanItemResponse(
                        level=1,
                        text=text,
                        checked=is_done_marker(marker),
                        marker=marker,
                        state=checkbox_state(marker),
                        phase_name=current_phase_name,
                        item_ordinal=ordinal,
                        text_hash=task_text_hash(text),
                        task_key=task_key(current_phase_name, ordinal, text),
                        file_path=fp.group(1) if fp else None,
                    )
                    current_parent.children.append(child)
                else:
                    # 들여쓰기 없음 → 상위 항목
                    top_level_ordinal += 1
                    ordinal = str(top_level_ordinal)
                    item = PlanItemResponse(
                        level=0,
                        text=text,
                        checked=is_done_marker(marker),
                        marker=marker,
                        state=checkbox_state(marker),
                        phase_name=current_phase_name,
                        item_ordinal=ordinal,
                        text_hash=task_text_hash(text),
                        task_key=task_key(current_phase_name, ordinal, text),
                        file_path=fp.group(1) if fp else None,
                    )
                    current_items.append(item)
                    current_parent = item
                    child_ordinals[id(item)] = 0

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

    # ========== 코드블록/체크박스 유틸리티 ==========

    @staticmethod
    def _remove_code_blocks(content: str) -> str:
        """코드블록/인라인 코드 제거 (체크박스 오인식 방지)"""
        content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
        content = re.sub(r'`[^`\n]+`', '', content)
        return content

    @staticmethod
    def _extract_pending_checkboxes(content: str) -> List[str]:
        """문서 전체에서 미완료 체크박스 텍스트 추출 (코드블록 제외)"""
        cleaned = PlanScanner._remove_code_blocks(content)
        # 멀티레벨 체크박스 지원: "- [ ]", "  - [ ]", "1. - [ ]" 모두 인식
        matches = re.findall(r'^[ \t]*(?:\d+\.\s+)?[-*]\s*\[[ /]\]\s*(.+)$', cleaned, re.MULTILINE)
        return [PlanScanner._strip_markdown_inline(m) for m in matches]


# 싱글톤 (plan_path_registry 생성 후 참조)
from app.modules.dev_runner.services.plan_path_registry import plan_path_registry  # noqa: E402

plan_scanner = PlanScanner(plan_path_registry)
