"""크롤 테이블 마이그레이션 검증 스크립트.

069_migrate_crawl_data.sql 실행 후 데이터 정합성을 확인합니다.
071_drop_legacy_crawl_tables.sql 실행 전에 반드시 이 스크립트로 검증하세요.

실행 방법:
    python scripts/verify_crawl_migration.py
"""

import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal


def verify_migration():
    """마이그레이션 데이터 정합성 검증."""
    db = SessionLocal()

    print("=" * 60)
    print("크롤 테이블 마이그레이션 검증")
    print("=" * 60)

    errors = []
    warnings = []

    try:
        # 1. Instagram 스케줄 설정 → crawl_schedules
        print("\n[1] instagram_schedule_config → crawl_schedules")

        legacy_schedules = db.execute(
            "SELECT COUNT(*) FROM instagram_schedule_config"
        ).scalar()

        new_schedules = db.execute(
            "SELECT COUNT(*) FROM crawl_schedules WHERE target_type = 'instagram_feed'"
        ).scalar()

        print(f"    레거시 instagram_schedule_config: {legacy_schedules}개")
        print(f"    새 crawl_schedules (instagram_feed): {new_schedules}개")

        if legacy_schedules != new_schedules:
            errors.append(f"스케줄 수 불일치: 레거시 {legacy_schedules} vs 신규 {new_schedules}")
        else:
            print("    ✓ 일치")

        # 2. Instagram 크롤 실행 → crawl_schedule_runs
        print("\n[2] instagram_crawl_runs → crawl_schedule_runs")

        legacy_runs = db.execute(
            "SELECT COUNT(*) FROM instagram_crawl_runs"
        ).scalar()

        new_runs = db.execute(
            "SELECT COUNT(*) FROM crawl_schedule_runs"
        ).scalar()

        print(f"    레거시 instagram_crawl_runs: {legacy_runs}개")
        print(f"    새 crawl_schedule_runs: {new_runs}개")

        if legacy_runs != new_runs:
            warnings.append(f"실행 이력 수 불일치: 레거시 {legacy_runs} vs 신규 {new_runs} (스케줄 매핑 실패 가능)")
        else:
            print("    ✓ 일치")

        # 3. Instagram 단건 요청 → crawl_requests
        print("\n[3] instagram_crawl_requests (single_post) → crawl_requests")

        legacy_single = db.execute(
            "SELECT COUNT(*) FROM instagram_crawl_requests WHERE request_type IN ('single_post', 'single_post_url')"
        ).scalar()

        new_instagram_requests = db.execute(
            "SELECT COUNT(*) FROM crawl_requests WHERE url_type = 'instagram'"
        ).scalar()

        print(f"    레거시 instagram_crawl_requests (single): {legacy_single}개")
        print(f"    새 crawl_requests (instagram): {new_instagram_requests}개")

        if legacy_single != new_instagram_requests:
            warnings.append(f"Instagram 요청 수 불일치: 레거시 {legacy_single} vs 신규 {new_instagram_requests}")
        else:
            print("    ✓ 일치")

        # 4. Universal 크롤 요청 → crawl_requests
        print("\n[4] universal_crawl_requests → crawl_requests")

        legacy_universal = db.execute(
            "SELECT COUNT(*) FROM universal_crawl_requests"
        ).scalar()

        new_universal = db.execute(
            "SELECT COUNT(*) FROM crawl_requests WHERE url_type != 'instagram'"
        ).scalar()

        print(f"    레거시 universal_crawl_requests: {legacy_universal}개")
        print(f"    새 crawl_requests (non-instagram): {new_universal}개")

        if legacy_universal != new_universal:
            warnings.append(f"Universal 요청 수 불일치: 레거시 {legacy_universal} vs 신규 {new_universal}")
        else:
            print("    ✓ 일치")

        # 5. instagram_posts.schedule_run_id 매핑 확인
        print("\n[5] instagram_posts.schedule_run_id 매핑")

        posts_with_crawl_run = db.execute(
            "SELECT COUNT(*) FROM instagram_posts WHERE crawl_run_id IS NOT NULL"
        ).scalar()

        posts_with_schedule_run = db.execute(
            "SELECT COUNT(*) FROM instagram_posts WHERE schedule_run_id IS NOT NULL"
        ).scalar()

        print(f"    crawl_run_id 있는 게시물: {posts_with_crawl_run}개")
        print(f"    schedule_run_id 있는 게시물: {posts_with_schedule_run}개")

        if posts_with_crawl_run != posts_with_schedule_run:
            warnings.append(f"게시물 run_id 매핑 불일치: {posts_with_crawl_run} vs {posts_with_schedule_run}")
        else:
            print("    ✓ 일치")

        # 결과 출력
        print("\n" + "=" * 60)
        print("검증 결과")
        print("=" * 60)

        if errors:
            print("\n❌ 오류:")
            for e in errors:
                print(f"   - {e}")

        if warnings:
            print("\n⚠️ 경고:")
            for w in warnings:
                print(f"   - {w}")

        if not errors and not warnings:
            print("\n✓ 모든 검증 통과! 레거시 테이블 삭제 가능")
            print("\n다음 명령으로 레거시 테이블을 삭제할 수 있습니다:")
            print("   sqlite3 data/monitor.db < app/migrations/071_drop_legacy_crawl_tables.sql")
        elif not errors:
            print("\n⚠️ 경고 있음. 확인 후 레거시 테이블 삭제 진행")
        else:
            print("\n❌ 오류 있음! 레거시 테이블 삭제 전 문제 해결 필요")

        return len(errors) == 0

    except Exception as e:
        print(f"\n❌ 검증 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = verify_migration()
    sys.exit(0 if success else 1)
