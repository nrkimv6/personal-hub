"""
Nightly cleanup 로그 파싱 및 통계 집계
"""
import re
from datetime import date, timedelta
from pathlib import Path


class CleanupStatsService:
    """Nightly done-cleanup 로그 파싱 — 프로젝트별 완료 항목 수 통계"""

    async def get_nightly_cleanup_stats(self, days: int = 14) -> dict:
        """Nightly done-cleanup 로그 파일 파싱 — 프로젝트별 완료 항목 수 통계"""
        log_dir = Path("D:/work/project/service/wtools/common/scripts/logs")
        today = date.today()
        runs = []

        for i in range(days):
            target_date = today - timedelta(days=i)
            log_file = log_dir / f"done-cleanup-{target_date.strftime('%Y-%m-%d')}.log"
            if not log_file.exists():
                continue

            try:
                content = log_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            run = {
                "date": target_date.isoformat(),
                "total_items": 0,
                "processed": 0,
                "failed": 0,
                "skipped": 0,
                "duration": None,
                "projects": {}
            }

            # 프로젝트별 item count 파싱
            # "    - activity-hub: 52 items"
            for m in re.finditer(r"- ([a-z0-9_\-]+): (\d+) items", content):
                project_name, count = m.group(1), int(m.group(2))
                run["projects"][project_name] = count

            # Summary 파싱
            m = re.search(r"Total Items Archived: (\d+)", content)
            if m:
                run["total_items"] = int(m.group(1))

            m = re.search(r"Processed: (\d+)", content)
            if m:
                run["processed"] = int(m.group(1))

            m = re.search(r"Failed: (\d+)", content)
            if m:
                run["failed"] = int(m.group(1))

            m = re.search(r"Skipped: (\d+)", content)
            if m:
                run["skipped"] = int(m.group(1))

            m = re.search(r"Duration: ([\d:]+)", content)
            if m:
                run["duration"] = m.group(1)

            runs.append(run)

        # 전체 요약
        total_runs = len(runs)
        total_items_all = sum(r["total_items"] for r in runs)
        all_projects: dict[str, int] = {}
        for r in runs:
            for proj, cnt in r["projects"].items():
                all_projects[proj] = all_projects.get(proj, 0) + cnt

        return {
            "runs": runs,
            "summary": {
                "total_runs": total_runs,
                "total_items_archived": total_items_all,
                "avg_items_per_run": round(total_items_all / total_runs, 1) if total_runs else 0,
                "by_project": all_projects,
            }
        }
