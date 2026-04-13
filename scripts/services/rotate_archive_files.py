"""
rotate_archive_files.py

30건 축적 트리거 archive 파일 로테이션 (새벽 2시 스케줄러 호출용).

조건:
  - file_removed_at IS NULL (아직 로테이션 안 된 것)
  - archived_at < now() - 90일
  - raw_content IS NOT NULL (DB-first 전환 완료된 것만)

트리거: 미로테이션 건수 >= 30이면 실행 (30의 배수 단위)
  총 60건 → 30건 로테이션
  총 29건 → 스킵

사용법:
  python scripts/services/rotate_archive_files.py --dry-run   # 기본: 대상 확인만
  python scripts/services/rotate_archive_files.py --apply     # 실제 git rm + commit
"""
import argparse
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROTATE_THRESHOLD = 30
RETENTION_DAYS = 90


def get_rotation_targets(db):
    """로테이션 대상 PlanRecord 조회"""
    from app.models.plan_record import PlanRecord
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    return (
        db.query(PlanRecord)
        .filter(
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.archived_at < cutoff,
            PlanRecord.raw_content.isnot(None),
        )
        .order_by(PlanRecord.archived_at.asc())
        .all()
    )


def rotate(apply: bool = False) -> dict:
    from app.database import SessionLocal
    from app.models.plan_record import PlanRecord

    with SessionLocal() as db:
        all_targets = get_rotation_targets(db)
        total_unrotated = len(all_targets)
        logger.info(f"미로테이션 대상: {total_unrotated}건 (임계값={ROTATE_THRESHOLD})")

        if total_unrotated < ROTATE_THRESHOLD:
            logger.info("임계값 미달 — 로테이션 스킵")
            return {"rotated": 0, "skipped_records": 0, "reason": "below_threshold"}

        n = (total_unrotated // ROTATE_THRESHOLD) * ROTATE_THRESHOLD
        targets = all_targets[:n]
        logger.info(f"로테이션 대상: {n}건")

        if not apply:
            for rec in targets[:5]:
                logger.info(f"  샘플: id={rec.id}, file_path={rec.file_path}")
            logger.info(f"--dry-run 모드: 실제 변경 없음. --apply로 실행하면 {n}건 로테이션.")
            return {"rotated": 0, "would_rotate": n, "reason": "dry_run"}

        # 실제 로테이션
        git_rm_files = []
        skipped = 0
        now = datetime.now()

        for rec in targets:
            fp = Path(rec.file_path)
            if not fp.exists():
                logger.warning(f"파일 없음 (skip): {rec.file_path}")
                rec.file_removed_at = now  # 이미 없으므로 마킹만
                skipped += 1
                continue
            try:
                result = subprocess.run(
                    ["git", "rm", str(fp)],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    logger.warning(f"git rm 실패 (skip): {rec.file_path} — {result.stderr.strip()}")
                    skipped += 1
                    continue
                rec.file_removed_at = now
                git_rm_files.append(str(fp))
            except Exception as e:
                logger.warning(f"git rm 예외 (skip): {rec.file_path} — {e}")
                skipped += 1

        if git_rm_files:
            commit_result = subprocess.run(
                ["git", "commit", "-m", f"chore: rotate {len(git_rm_files)} archive files (DB-first)"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )
            if commit_result.returncode != 0:
                logger.error(f"git commit 실패: {commit_result.stderr.strip()}")
            else:
                logger.info(f"git commit 완료: {len(git_rm_files)}건")

        db.commit()
        rotated = len(git_rm_files)
        logger.info(f"로테이션 완료: rotated={rotated}, skipped={skipped}")
        return {"rotated": rotated, "skipped_records": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Archive 파일 로테이션 (30건 트리거)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True, help="대상 확인만 (기본값)")
    group.add_argument("--apply", action="store_true", default=False, help="실제 git rm + commit")
    args = parser.parse_args()

    result = rotate(apply=args.apply)
    print(result)
