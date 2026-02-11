"""plan 문서 관리 서비스"""

import json
import re
from pathlib import Path
from typing import List

from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import PlanFileResponse, PlanProgressResponse


class PlanService:
    """plan 문서 탐색 및 파싱 서비스"""

    def __init__(self):
        self._external_plans: List[str] = []
        self._load_external_plans()

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

        # Step 3: 외부 plan 파일
        for ext_path in self._external_plans:
            p = Path(ext_path)
            if str(p) not in seen and p.exists():
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
    ):
        """plan 디렉토리 스캔"""
        if not plan_dir.exists():
            return

        # source 결정
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
                    )
                )

    def _is_ignored_plan(self, path: Path, status: str, progress: PlanProgressResponse) -> bool:
        """plan이 무시 대상인지 판단"""
        # 완료 상태
        if "완료" in status or "구현완료" in status:
            return True
        # 모든 체크박스 완료
        if progress.total > 0 and progress.done == progress.total:
            return True
        # 체크박스 없음
        if progress.total == 0:
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
