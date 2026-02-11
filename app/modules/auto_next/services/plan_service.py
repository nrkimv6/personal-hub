"""plan 문서 관리 서비스"""

import re
from pathlib import Path
from typing import List

from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import PlanFileResponse, PlanProgressResponse


class PlanService:
    """plan 문서 탐색 및 파싱 서비스"""

    def list_plans(self) -> List[PlanFileResponse]:
        """plan 목록 조회"""
        plan_dir = config.WTOOLS_BASE_DIR / config.PLAN_DIR
        if not plan_dir.exists():
            return []

        results = []
        for plan_file in plan_dir.glob("*.md"):
            # _todo.md 파일은 제외
            if plan_file.stem.endswith("_todo"):
                continue

            # 상태 및 진행률 파싱
            status = self.get_plan_status(plan_file)
            progress = self.get_plan_progress(plan_file)

            results.append(
                PlanFileResponse(
                    path=str(plan_file),
                    filename=plan_file.name,
                    status=status,
                    progress=progress,
                )
            )

        # 파일명 역순 정렬 (최신 파일 우선)
        results.sort(key=lambda x: x.filename, reverse=True)
        return results

    def get_plan_progress(self, path: Path) -> PlanProgressResponse:
        """plan 진행률 파싱"""
        if not path.exists():
            return PlanProgressResponse(done=0, total=0, percent=0)

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # 체크박스 패턴: ^\d+\.\s*\[([ x])\] 또는 ^-\s*\[([ x])\]
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
                    # > 상태: 검토완료
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
