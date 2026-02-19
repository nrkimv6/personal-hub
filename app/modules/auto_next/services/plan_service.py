"""plan 문서 관리 서비스"""

import json
import re
from pathlib import Path
from typing import List, Optional

from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import (
    PlanFileResponse, PlanProgressResponse,
    PlanDetailResponse, PlanPhaseResponse, PlanItemResponse,
    ExternalPathResponse,
)


class PlanService:
    """plan 문서 탐색 및 파싱 서비스"""

    def __init__(self):
        self._external_plans: List[str] = []
        self._ignored_plans: List[str] = []
        self._load_external_plans()
        self._load_ignored_plans()

    def _load_external_plans(self):
        """외부 plan 목록 로드 (JSON 파일)"""
        path = config.EXTERNAL_PLANS_FILE
        if path.exists():
            try:
                self._external_plans = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._external_plans = []

    def _save_external_plans(self):
        """외부 plan 목록 저장"""
        path = config.EXTERNAL_PLANS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._external_plans, ensure_ascii=False, indent=2), encoding="utf-8")

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._ignored_plans, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_to_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에 추가"""
        resolved = str(Path(plan_path).resolve())
        if resolved not in self._ignored_plans:
            self._ignored_plans.append(resolved)
            self._save_ignored_plans()
            return True
        return False

    def remove_from_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에서 제거"""
        resolved = str(Path(plan_path).resolve())
        if resolved in self._ignored_plans:
            self._ignored_plans.remove(resolved)
            self._save_ignored_plans()
            return True
        return False

    def add_external_plan(self, plan_path: str) -> bool:
        """외부 plan 경로 추가 (영구 저장)"""
        resolved = str(Path(plan_path).resolve())
        if resolved not in self._external_plans:
            self._external_plans.append(resolved)
            self._save_external_plans()
            return True
        return False

    def remove_external_plan(self, plan_path: str) -> bool:
        """외부 plan 경로 제거"""
        resolved = str(Path(plan_path).resolve())
        if resolved in self._external_plans:
            self._external_plans.remove(resolved)
            self._save_external_plans()
            return True
        return False

    def list_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """
        plan 목록 조회 (프로젝트별 탐색 포함)

        탐색 범위:
        1. common/docs/plan/*.md
        2. 각 프로젝트의 docs/plan/*.md
        3. 외부 추가된 plan 파일
        """
        seen: set[str] = set()
        results: List[PlanFileResponse] = []

        # Step 1: common/docs/plan
        common_plan_dir = config.WTOOLS_BASE_DIR / config.PLAN_DIR
        self._scan_plan_dir(common_plan_dir, seen, results, include_ignored)

        # Step 2: 각 프로젝트의 docs/plan
        for project in config.PROJECT_DIRS:
            project_plan_dir = config.WTOOLS_BASE_DIR / project / "docs" / "plan"
            self._scan_plan_dir(project_plan_dir, seen, results, include_ignored)

        # Step 3: 외부 plan 파일/폴더
        for ext_path in self._external_plans:
            p = Path(ext_path)
            if not p.exists():
                continue
            if p.is_dir():
                # 폴더이면 내부 *.md 전체 스캔 (source_override="external", external_type="folder")
                self._scan_plan_dir(p, seen, results, include_ignored,
                                    source_override="external", external_type="folder")
            else:
                # 파일이면 기존 로직 유지
                if str(p) not in seen:
                    seen.add(str(p))
                    status = self.get_plan_status(p)
                    progress = self.get_plan_progress(p)
                    is_ignored = self._is_ignored_plan(p, status, progress)
                    if include_ignored or not is_ignored:
                        results.append(
                            PlanFileResponse(
                                path=str(p),
                                filename=p.name,
                                status=status,
                                progress=progress,
                                source="external",
                                ignored=is_ignored,
                                external_type="file",
                            )
                        )

        results.sort(key=lambda x: x.filename, reverse=True)
        return results

    def list_ignored_plans(self) -> List[PlanFileResponse]:
        """무시된(완료/빈) plan 목록만 조회"""
        all_plans = self.list_plans(include_ignored=True)
        return [p for p in all_plans if p.ignored]

    def _scan_plan_dir(
        self,
        plan_dir: Path,
        seen: set,
        results: List[PlanFileResponse],
        include_ignored: bool,
        source_override: Optional[str] = None,
        external_type: Optional[str] = None,
    ):
        """plan 디렉토리 스캔

        Args:
            plan_dir: 스캔할 디렉토리
            seen: 이미 처리된 경로 집합 (중복 방지)
            results: 결과 목록 (append)
            include_ignored: True이면 무시된 plan도 포함
            source_override: None이면 자동 결정, 문자열이면 해당 값 사용
                (외부 폴더는 WTOOLS_BASE_DIR 바깥이라 relative_to 실패 → "external" 강제 지정)
            external_type: "folder" | None — PlanFileResponse.external_type에 설정할 값
        """
        if not plan_dir.exists():
            return

        # source 결정: override가 없으면 WTOOLS_BASE_DIR 상대경로에서 추출
        if source_override is not None:
            source = source_override
        else:
            base = config.WTOOLS_BASE_DIR
            rel = ""
            try:
                rel = str(plan_dir.relative_to(base))
            except ValueError:
                pass
            source = rel.split("\\")[0] if "\\" in rel else rel.split("/")[0] if "/" in rel else "common"

        for plan_file in plan_dir.glob("*.md"):
            if plan_file.stem.endswith("_todo"):
                continue
            key = str(plan_file)
            if key in seen:
                continue
            seen.add(key)

            status = self.get_plan_status(plan_file)
            progress = self.get_plan_progress(plan_file)
            is_ignored = self._is_ignored_plan(plan_file, status, progress)

            if include_ignored or not is_ignored:
                results.append(
                    PlanFileResponse(
                        path=str(plan_file),
                        filename=plan_file.name,
                        status=status,
                        progress=progress,
                        source=source,
                        ignored=is_ignored,
                        external_type=external_type,
                    )
                )

    def _is_ignored_plan(self, path: Path, status: str, progress: PlanProgressResponse) -> bool:
        """plan이 무시 대상인지 판단"""
        # 수동 무시 목록
        if str(path.resolve()) in self._ignored_plans:
            return True
        # 완료 상태
        if "완료" in status or "구현완료" in status:
            return True
        # 모든 체크박스 완료
        if progress.total > 0 and progress.done == progress.total:
            return True
        return False

    def get_plan_progress(self, path: Path) -> PlanProgressResponse:
        """plan 진행률 파싱"""
        if not path.exists():
            return PlanProgressResponse(done=0, total=0, percent=0)

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            checkbox_pattern = r"^(?:\d+\.|-)\s*\[([ x→])\]"
            matches = re.findall(checkbox_pattern, content, re.MULTILINE)

            total = len(matches)
            done = sum(1 for m in matches if m == "x")
            percent = int(done / total * 100) if total > 0 else 0

            return PlanProgressResponse(done=done, total=total, percent=percent)
        except Exception:
            return PlanProgressResponse(done=0, total=0, percent=0)

    def get_plan_status(self, path: Path) -> str:
        """plan 상태 파싱 (> 상태: ...)"""
        if not path.exists():
            return "unknown"

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    match = re.match(r">\s*상태:\s*(.+)", line)
                    if match:
                        return match.group(1).strip()
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

    def parse_plan_items(self, path: Path) -> PlanDetailResponse:
        """plan 파일을 Phase별 항목으로 파싱"""
        # _todo 파일이 있으면 우선 사용
        todo_file = self._find_todo_file(path)
        parse_path = todo_file if todo_file else path

        content = parse_path.read_text(encoding="utf-8", errors="ignore")
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

            # 대시 체크박스 (하위): - [ ] or - [x]
            dash_match = re.match(r'^\s+-\s*\[([ x→])\]\s*(.*)', line)
            if dash_match and current_parent is not None:
                text = dash_match.group(2).strip()
                fp = file_path_pattern.search(text)
                child = PlanItemResponse(
                    level=1,
                    text=text,
                    checked=dash_match.group(1) == 'x',
                    file_path=fp.group(1) if fp else None,
                )
                current_parent.children.append(child)

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
        )

    def list_external_paths(self) -> List[ExternalPathResponse]:
        """등록된 외부 경로 목록 조회 (타입 + plan_count 포함)"""
        result = []
        for ext_path in self._external_plans:
            p = Path(ext_path)
            if p.is_dir():
                # 폴더: _todo 제외 *.md 개수
                plan_count = sum(
                    1 for f in p.glob("*.md") if not f.stem.endswith("_todo")
                ) if p.exists() else 0
                result.append(ExternalPathResponse(path=ext_path, type="folder", plan_count=plan_count))
            else:
                result.append(ExternalPathResponse(path=ext_path, type="file", plan_count=1 if p.exists() else 0))
        return result

    def validate_external_path(self, path: str) -> bool:
        """외부 경로 화이트리스트 검증"""
        path_obj = Path(path).resolve()
        path_str = str(path_obj)

        for allowed in config.ALLOWED_EXTERNAL_PATHS:
            if path_str.startswith(allowed):
                return True
        return False


# 싱글톤 인스턴스
plan_service = PlanService()

__all__ = ['plan_service', 'PlanService']
