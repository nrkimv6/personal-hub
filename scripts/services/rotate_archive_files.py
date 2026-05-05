"""
rotate_archive_files.py

Plan Archive 파일 retention job (새벽 2시 스케줄러 호출용).

조건:
  - file_removed_at IS NULL (아직 로테이션 안 된 것)
  - llm_processed_at IS NOT NULL
  - raw_content IS NOT NULL (DB-first 전환 완료된 것만)
  - file_delete_after <= now()

사용법:
  python scripts/services/rotate_archive_files.py --dry-run   # 기본: 대상 확인만
  python scripts/services/rotate_archive_files.py --apply     # 실제 git rm + commit
"""
import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RETENTION_DAYS = 7
DEFAULT_MAX_FILES_PER_RUN = 30
COMMIT_SCRIPT = Path(r"D:\work\project\tools\common\commit.ps1")


def _plans_worktree() -> Path:
    direct = PROJECT_ROOT / ".worktrees" / "plans"
    if direct.exists():
        return direct
    sibling = PROJECT_ROOT.parent / "plans"
    if sibling.exists():
        return sibling
    return direct


def get_rotation_targets(db):
    """로테이션 대상 PlanRecord 조회"""
    from app.models.plan_record import PlanRecord
    from app.modules.dev_runner.services.plan_record_service import _exclude_temp_pytest_records

    now = datetime.now()
    query = (
        db.query(PlanRecord)
        .filter(
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.llm_processed_at.isnot(None),
            PlanRecord.raw_content.isnot(None),
            PlanRecord.file_delete_after.isnot(None),
            PlanRecord.file_delete_after <= now,
        )
    )
    query = _exclude_temp_pytest_records(query)
    return query.order_by(PlanRecord.file_delete_after.asc(), PlanRecord.archived_at.asc()).all()


def _archive_relative_path(path: Path, plans_root: Path) -> Path | None:
    try:
        relative = path.resolve().relative_to(plans_root.resolve())
    except ValueError:
        return None
    parts = [part.lower() for part in relative.parts]
    if len(parts) < 3 or parts[0] != "docs" or parts[1] != "archive":
        return None
    return relative


def rotate(apply: bool = False, max_files_per_run: int = DEFAULT_MAX_FILES_PER_RUN) -> dict:
    from app.database import SessionLocal

    plans_root = _plans_worktree()
    max_files = max(1, int(max_files_per_run or DEFAULT_MAX_FILES_PER_RUN))

    with SessionLocal() as db:
        all_targets = get_rotation_targets(db)
        targets = all_targets[:max_files]
        logger.info("retention due 대상: %s건 (batch=%s)", len(all_targets), max_files)

        if not apply:
            for rec in targets[:5]:
                logger.info("  샘플: id=%s, file_delete_after=%s, file_path=%s", rec.id, rec.file_delete_after, rec.file_path)
            return {"due": len(all_targets), "removed": 0, "missing_marked": 0, "skipped_temp": 0, "blocked_no_raw_content": 0, "would_remove": len(targets), "reason": "dry_run"}

        removed = 0
        missing_marked = 0
        skipped_outside_archive = 0
        git_rm_files: list[str] = []
        now = datetime.now()

        for rec in targets:
            fp = Path(rec.file_path)
            relative = _archive_relative_path(fp, plans_root)
            if relative is None:
                logger.warning("archive path 밖 대상 skip: %s", rec.file_path)
                skipped_outside_archive += 1
                continue
            if not fp.exists():
                rec.file_removed_at = now
                missing_marked += 1
                continue
            result = subprocess.run(
                ["git", "rm", "--", str(relative)],
                cwd=str(plans_root),
                capture_output=True,
                text=True,
                shell=False,
            )
            if result.returncode != 0:
                logger.warning("git rm 실패: %s — %s", relative, result.stderr.strip())
                continue
            rec.file_removed_at = now
            git_rm_files.append(str(relative))
            removed += 1

        if git_rm_files:
            commit_result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(COMMIT_SCRIPT),
                    f"chore: rotate {len(git_rm_files)} archive files (DB-first)",
                ],
                cwd=str(plans_root),
                capture_output=True,
                text=True,
                shell=False,
            )
            if commit_result.returncode != 0:
                db.rollback()
                logger.error("commit script 실패: %s", commit_result.stderr.strip() or commit_result.stdout.strip())
                return {"due": len(all_targets), "removed": 0, "missing_marked": 0, "skipped_outside_archive": skipped_outside_archive, "error": "commit_failed"}

        db.commit()
        logger.info("retention 완료: removed=%s, missing_marked=%s", removed, missing_marked)
        return {
            "due": len(all_targets),
            "removed": removed,
            "rotated": removed,
            "missing_marked": missing_marked,
            "skipped_temp": 0,
            "blocked_no_raw_content": 0,
            "skipped_outside_archive": skipped_outside_archive,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Archive 파일 retention")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True, help="대상 확인만 (기본값)")
    group.add_argument("--apply", action="store_true", default=False, help="실제 git rm + commit")
    parser.add_argument("--max-files-per-run", type=int, default=DEFAULT_MAX_FILES_PER_RUN)
    args = parser.parse_args()

    result = rotate(apply=args.apply, max_files_per_run=args.max_files_per_run)
    print(result)
