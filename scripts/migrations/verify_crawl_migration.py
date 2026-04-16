#!/usr/bin/env python3
"""크롤 테이블 마이그레이션 검증 스크립트.

이 스크립트는 legacy crawl 테이블이 아직 남아있을 때만 의미가 있다.
운영 환경에서 레거시 테이블이 이미 제거된 경우에는 historical verifier로 간주하고
안내만 출력한 뒤 정상 종료한다.
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal


LEGACY_TABLES = {
    "instagram_schedule_config",
    "instagram_crawl_runs",
    "instagram_crawl_requests",
    "universal_crawl_requests",
}

NEW_TABLES = {
    "crawl_schedules",
    "crawl_schedule_runs",
    "crawl_requests",
}


def _scalar(db, sql: str):
    return db.execute(text(sql)).scalar()


def verify_migration():
    """마이그레이션 데이터 정합성 검증."""
    db = SessionLocal()

    print("=" * 60)
    print("크롤 테이블 마이그레이션 검증")
    print("=" * 60)

    errors = []
    warnings = []

    try:
        inspector = inspect(db.get_bind())
        tables = set(inspector.get_table_names())

        missing_legacy = sorted(LEGACY_TABLES - tables)
        missing_new = sorted(NEW_TABLES - tables)

        if missing_legacy:
            print("\n[LEGACY GUARD]")
            print("레거시 crawl 테이블이 이미 제거되었거나 이행이 완료되었습니다.")
            print(f"누락된 legacy 테이블: {', '.join(missing_legacy)}")
            print("이 스크립트는 historical verifier로만 유지됩니다.")
            return True

        if missing_new:
            print("\n[LEGACY GUARD]")
            print("신규 crawl 테이블이 모두 준비되지 않아 검증을 진행할 수 없습니다.")
            print(f"누락된 신규 테이블: {', '.join(missing_new)}")
            return False

        print("\n[1] instagram_schedule_config → crawl_schedules")
        legacy_schedules = _scalar(db, "SELECT COUNT(*) FROM instagram_schedule_config")
        new_schedules = _scalar(
            db,
            "SELECT COUNT(*) FROM crawl_schedules WHERE target_type = 'instagram_feed'",
        )
        print(f"    레거시 instagram_schedule_config: {legacy_schedules}개")
        print(f"    새 crawl_schedules (instagram_feed): {new_schedules}개")
        if legacy_schedules != new_schedules:
            errors.append(f"스케줄 수 불일치: 레거시 {legacy_schedules} vs 신규 {new_schedules}")
        else:
            print("    ✓ 일치")

        print("\n[2] instagram_crawl_runs → crawl_schedule_runs")
        legacy_runs = _scalar(db, "SELECT COUNT(*) FROM instagram_crawl_runs")
        new_runs = _scalar(db, "SELECT COUNT(*) FROM crawl_schedule_runs")
        print(f"    레거시 instagram_crawl_runs: {legacy_runs}개")
        print(f"    새 crawl_schedule_runs: {new_runs}개")
        if legacy_runs != new_runs:
            warnings.append(
                f"실행 이력 수 불일치: 레거시 {legacy_runs} vs 신규 {new_runs} (스케줄 매핑 실패 가능)"
            )
        else:
            print("    ✓ 일치")

        print("\n[3] instagram_crawl_requests (single_post) → crawl_requests")
        legacy_single = _scalar(
            db,
            """
            SELECT COUNT(*) FROM instagram_crawl_requests
            WHERE request_type IN ('single_post', 'single_post_url')
            """,
        )
        new_instagram_requests = _scalar(
            db,
            "SELECT COUNT(*) FROM crawl_requests WHERE url_type = 'instagram'",
        )
        print(f"    레거시 instagram_crawl_requests (single): {legacy_single}개")
        print(f"    새 crawl_requests (instagram): {new_instagram_requests}개")
        if legacy_single != new_instagram_requests:
            warnings.append(
                f"Instagram 요청 수 불일치: 레거시 {legacy_single} vs 신규 {new_instagram_requests}"
            )
        else:
            print("    ✓ 일치")

        print("\n[4] universal_crawl_requests → crawl_requests")
        legacy_universal = _scalar(db, "SELECT COUNT(*) FROM universal_crawl_requests")
        new_universal = _scalar(
            db,
            "SELECT COUNT(*) FROM crawl_requests WHERE url_type != 'instagram'",
        )
        print(f"    레거시 universal_crawl_requests: {legacy_universal}개")
        print(f"    새 crawl_requests (non-instagram): {new_universal}개")
        if legacy_universal != new_universal:
            warnings.append(
                f"Universal 요청 수 불일치: 레거시 {legacy_universal} vs 신규 {new_universal}"
            )
        else:
            print("    ✓ 일치")

        print("\n[5] instagram_posts.schedule_run_id 매핑")
        posts_with_crawl_run = _scalar(
            db,
            "SELECT COUNT(*) FROM instagram_posts WHERE crawl_run_id IS NOT NULL",
        )
        posts_with_schedule_run = _scalar(
            db,
            "SELECT COUNT(*) FROM instagram_posts WHERE schedule_run_id IS NOT NULL",
        )
        print(f"    crawl_run_id 있는 게시물: {posts_with_crawl_run}개")
        print(f"    schedule_run_id 있는 게시물: {posts_with_schedule_run}개")
        if posts_with_crawl_run != posts_with_schedule_run:
            warnings.append(
                f"게시물 run_id 매핑 불일치: {posts_with_crawl_run} vs {posts_with_schedule_run}"
            )
        else:
            print("    ✓ 일치")

        print("\n" + "=" * 60)
        print("검증 결과")
        print("=" * 60)

        if errors:
            print("\n오류:")
            for error in errors:
                print(f"  - {error}")

        if warnings:
            print("\n경고:")
            for warning in warnings:
                print(f"  - {warning}")

        if not errors and not warnings:
            print("\n모든 검증 통과. 당시 기준으로 레거시 테이블 삭제 가능 상태입니다.")
        elif not errors:
            print("\n경고가 있습니다. 당시 마이그레이션 로그와 함께 확인하세요.")
        else:
            print("\n오류가 있습니다. 레거시 삭제 전 문제 해결이 필요합니다.")

        return len(errors) == 0

    except Exception as e:
        print(f"\n검증 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = verify_migration()
    sys.exit(0 if success else 1)
