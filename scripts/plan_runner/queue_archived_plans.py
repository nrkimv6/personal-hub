"""
queue_archived_plans.py — 미처리 archived plan 일괄 LLM 큐 등록 스크립트

DB에서 llm_processed_at IS NULL AND archived_at IS NOT NULL 조회 →
날짜순 정렬 → 각각 LLMRequest INSERT

사용법:
    python scripts/queue_archived_plans.py
    python scripts/queue_archived_plans.py --dry-run
    python scripts/queue_archived_plans.py --limit 50
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.plan_analyze_handler import (
    build_plan_analyze_prompt
)
from sqlalchemy import and_


def main():
    parser = argparse.ArgumentParser(description="미처리 archived plan 일괄 LLM 큐 등록")
    parser.add_argument("--dry-run", action="store_true", help="INSERT 없이 대상 건수만 출력")
    parser.add_argument("--limit", type=int, default=0, help="한 번에 등록할 최대 건수 (0=무제한)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # 미처리 레코드 조회
        q = db.query(PlanRecord).filter(
            and_(
                PlanRecord.llm_processed_at.is_(None),
                PlanRecord.archived_at.isnot(None),
            )
        ).order_by(PlanRecord.archived_at.asc())

        if args.limit > 0:
            q = q.limit(args.limit)

        records = q.all()
        print(f"대상 레코드: {len(records)}개")

        if args.dry_run:
            for r in records:
                print(f"  - {r.file_path} (hash={r.filename_hash[:8]}...)")
            print(f"\n[DRY-RUN] 실제 INSERT 없이 종료")
            return

        # 기존 pending 요청의 caller_id 목록 조회 (중복 방지)
        existing_pending = {
            row[0]
            for row in db.query(LLMRequest.caller_id).filter(
                and_(
                    LLMRequest.caller_type == "plan_archive_analyze",
                    LLMRequest.status == "pending",
                )
            ).all()
        }

        inserted = skipped = 0
        for record in records:
            if record.filename_hash in existing_pending:
                skipped += 1
                continue

            # 파일 내용 읽기 (없으면 파일명만 사용)
            file_content = ""
            try:
                fp = Path(record.file_path)
                if fp.exists():
                    file_content = fp.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"  [경고] 파일 읽기 실패 ({record.file_path}): {e}")

            prompt = build_plan_analyze_prompt(
                file_content=file_content,
                filename=Path(record.file_path).name,
            )

            llm_req = LLMRequest(
                caller_type="plan_archive_analyze",
                caller_id=record.filename_hash,
                prompt=prompt,
                queue_name="utility",
                requested_by="scheduler",
            )
            db.add(llm_req)
            inserted += 1

        db.commit()
        print(f"완료 — INSERT: {inserted}개, 중복 스킵: {skipped}개")

    finally:
        db.close()


if __name__ == "__main__":
    main()
