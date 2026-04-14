"""
backfill_plan_record_raw_content.py

raw_content IS NULL인 PlanRecord에 파일 본문을 채운다.

사용법:
  python scripts/migrations/backfill_plan_record_raw_content.py --dry-run   # 기본: 대상 건수 + 샘플 출력
  python scripts/migrations/backfill_plan_record_raw_content.py --apply      # 실제 DB에 저장
"""
import argparse
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run(apply: bool = False):
    from app.database import SessionLocal
    from app.models.plan_record import PlanRecord

    with SessionLocal() as db:
        targets = db.query(PlanRecord).filter(PlanRecord.raw_content.is_(None)).all()
        total = len(targets)
        logger.info(f"raw_content IS NULL 레코드: {total}건")

        if total == 0:
            logger.info("백필 대상 없음. 종료.")
            return

        # 샘플 5건 출력 (dry-run 포함)
        for rec in targets[:5]:
            logger.info(f"  샘플: id={rec.id}, file_path={rec.file_path}")

        if not apply:
            logger.info(f"--dry-run 모드: 실제 변경 없음. --apply로 실행하면 {total}건 백필.")
            return

        filled = skipped = 0
        for rec in targets:
            fp = Path(rec.file_path)
            if not fp.exists():
                logger.warning(f"파일 없음 (skip): {rec.file_path}")
                skipped += 1
                continue
            try:
                rec.raw_content = fp.read_text(encoding="utf-8")
                filled += 1
            except Exception as e:
                logger.warning(f"읽기 실패 (skip): {rec.file_path} — {e}")
                skipped += 1

        db.commit()
        logger.info(f"백필 완료: filled={filled}, skipped={skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PlanRecord raw_content 백필")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True, help="대상 건수 출력 (기본값)")
    group.add_argument("--apply", action="store_true", default=False, help="실제 DB에 저장")
    args = parser.parse_args()

    run(apply=args.apply)
