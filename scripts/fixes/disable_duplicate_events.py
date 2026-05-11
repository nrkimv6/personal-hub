"""
기존 중복 이벤트 URL 정리 스크립트

같은 URL을 가진 이벤트 레코드들 중 최신 레코드(created_at 기준)를 status='disabled' 처리
가장 오래된 레코드만 활성 유지

실행:
    python D:\work\project\tools\monitor-page\scripts\fixes\disable_duplicate_events.py

⚠️ 2026-04-10 PostgreSQL 전환 이후에는 settings.DATABASE_URL을 사용한다.
   data/monitor.db는 더 이상 운영 DB가 아니다.
"""
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings


def find_duplicate_urls(session) -> dict:
    """중복 URL을 가진 이벤트 그룹 찾기"""
    query = text("""
        SELECT event_url, COUNT(*) as cnt
        FROM events
        WHERE event_url IS NOT NULL
          AND event_url != ''
          AND status != 'disabled'
        GROUP BY event_url
        HAVING cnt > 1
        ORDER BY cnt DESC
    """)

    result = session.execute(query)
    duplicates = {}
    for row in result:
        duplicates[row[0]] = row[1]

    return duplicates


def get_events_by_url(session, url: str) -> list:
    """특정 URL을 가진 이벤트 목록 조회 (created_at 오름차순)"""
    query = text("""
        SELECT id, title, status, created_at
        FROM events
        WHERE event_url = :url
          AND status != 'disabled'
        ORDER BY created_at ASC
    """)

    result = session.execute(query, {"url": url})
    return [dict(row._mapping) for row in result]


def disable_duplicate_events(session, url: str, events: list) -> int:
    """중복 이벤트 중 최신 것들을 disabled 처리 (가장 오래된 것만 유지)"""
    if len(events) <= 1:
        return 0

    # 첫 번째(가장 오래된 것)는 유지, 나머지 disabled 처리
    events_to_disable = events[1:]
    ids_to_disable = [e["id"] for e in events_to_disable]

    update_query = text("""
        UPDATE events
        SET status = 'disabled'
        WHERE id IN :ids
    """)

    session.execute(update_query, {"ids": tuple(ids_to_disable)})
    return len(ids_to_disable)


def main():
    db_url = settings.DATABASE_URL
    print(f"DB: {db_url}")
    print("-" * 60)

    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # 1. 중복 URL 찾기
        duplicates = find_duplicate_urls(session)

        if not duplicates:
            print("✓ 중복 URL이 없습니다.")
            return

        print(f"총 {len(duplicates)}개의 중복 URL 발견:\n")

        total_disabled = 0

        for url, count in duplicates.items():
            print(f"URL: {url[:80]}...")
            print(f"  중복 개수: {count}")

            events = get_events_by_url(session, url)

            # 유지할 이벤트 (가장 오래된 것)
            keep = events[0]
            print(f"  유지: ID={keep['id']} | {keep['title'][:40]} | {keep['created_at']}")

            # disabled 처리할 이벤트들
            for e in events[1:]:
                print(f"  비활성화: ID={e['id']} | {e['title'][:40]} | {e['created_at']}")

            disabled_count = disable_duplicate_events(session, url, events)
            total_disabled += disabled_count
            print()

        # 커밋
        session.commit()
        print("-" * 60)
        print(f"✓ 완료: {total_disabled}개 이벤트를 disabled 처리했습니다.")

    except Exception as e:
        session.rollback()
        print(f"✗ 오류 발생: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
