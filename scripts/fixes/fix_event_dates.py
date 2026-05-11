"""이벤트 날짜 수정 스크립트 (SQLite 전용 레거시).

2026년에 생성된 이벤트 중 날짜가 2025년으로 잘못 저장된 것들을 수정합니다.

수정 기준:
- created_at이 2026년인 데이터 중
- event_end가 created_at보다 과거 (11개월 이상 차이)
- → event_start, event_end에 1년 추가

⚠️ LEGACY: 이 스크립트는 SQLite data/monitor.db 직접 접근을 사용합니다.
   2026-04-10 PostgreSQL 전환 이후에는 data/monitor.db가 운영 DB가 아닙니다.
   DB 파일이 존재하지 않으면 스크립트가 종료됩니다.
   PostgreSQL 환경에서 동일 작업이 필요하면 SQLAlchemy 세션 기반으로 재작성이 필요합니다.
"""

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def remove_emoji(text):
    """이모지 및 특수 유니코드 문자 제거."""
    if not text:
        return text
    # 이모지 및 특수 문자 패턴 제거
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"  # dingbats
        "\U0000FE00-\U0000FEFF"  # variation selectors
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub("", text)


def get_db_path():
    """DB 경로 반환."""
    script_dir = Path(__file__).parent
    return script_dir.parent / "data" / "monitor.db"


def analyze_events(conn):
    """수정이 필요한 이벤트 분석."""
    cursor = conn.cursor()

    # 2026년에 생성되었는데 event_end가 2025-01~03인 데이터
    # Instagram 포스트의 display_time이 "n일전", "n주전" 형태인 경우만 대상
    cursor.execute("""
        SELECT e.id, e.title, e.event_start, e.event_end, e.created_at,
               p.display_time, p.posted_at
        FROM events e
        LEFT JOIN instagram_posts p ON e.source_instagram_post_id = p.id
        WHERE e.created_at >= '2026-01-01'
          AND e.event_end IS NOT NULL
          AND e.event_end < date(e.created_at, '-30 days')
        ORDER BY e.id
    """)

    results = []
    for row in cursor.fetchall():
        event_id, title, start, end, created, display_time, posted_at = row

        # display_time이 상대 날짜인지 확인 ("1일", "3시간", "2주" 등)
        is_relative_date = False
        if display_time:
            # "n일", "n시간", "n주", "n달" 또는 "n일전", "n시간전" 등
            relative_keywords = ["일", "주", "시간", "분", "초", "달", "월", "개월"]
            is_relative_date = any(kw in display_time for kw in relative_keywords)

        if not is_relative_date:
            continue  # 상대 날짜가 아니면 스킵

        # event_end가 created_at보다 30일 이상 과거면 수정 대상
        created_date = datetime.strptime(created[:10], "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()

        diff_days = (created_date - end_date).days

        if diff_days > 30:  # 30일 이상 차이나면 잘못된 연도
            results.append({
                "id": event_id,
                "title": title[:40] if title else "N/A",
                "event_start": start,
                "event_end": end,
                "created_at": created[:10],
                "diff_days": diff_days,
                "display_time": display_time,
                "posted_at": posted_at[:10] if posted_at else None
            })

    return results


def fix_events(conn, dry_run=True):
    """이벤트 날짜 수정."""
    cursor = conn.cursor()

    # 수정 대상 조회
    targets = analyze_events(conn)

    if not targets:
        print("수정할 데이터가 없습니다.")
        return 0

    print(f"\n{'='*80}")
    print(f"수정 대상: {len(targets)}건")
    print(f"{'='*80}\n")

    for t in targets:
        old_start = t["event_start"]
        old_end = t["event_end"]

        # 1년 추가
        new_start = add_year(old_start) if old_start else None
        new_end = add_year(old_end) if old_end else None

        # 이모지 제거 (cp949 인코딩 문제 방지)
        title_clean = remove_emoji(t['title'][:30]) if t['title'] else 'N/A'
        print(f"ID={t['id']:4d} | {title_clean:30s}")
        print(f"  start: {old_start} -> {new_start}")
        print(f"  end:   {old_end} -> {new_end}")
        print(f"  created: {t['created_at']}, diff: {t['diff_days']}d")
        print(f"  display_time: {t.get('display_time', 'N/A')}, posted_at: {t.get('posted_at', 'N/A')}")
        print()

        if not dry_run:
            cursor.execute("""
                UPDATE events
                SET event_start = ?, event_end = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (new_start, new_end, t["id"]))

    if not dry_run:
        conn.commit()
        print(f"\n{len(targets)}건 수정 완료!")
    else:
        print(f"\n[DRY RUN] 실제 수정하려면 --apply 옵션을 추가하세요.")

    return len(targets)


def add_year(date_str):
    """날짜 문자열에 1년 추가."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        new_dt = dt.replace(year=dt.year + 1)
        return new_dt.strftime("%Y-%m-%d")
    except ValueError:
        return date_str


def analyze_popups(conn):
    """수정이 필요한 팝업 분석."""
    cursor = conn.cursor()

    # 팝업도 동일한 기준으로 분석 (Instagram 포스트 연결)
    cursor.execute("""
        SELECT pp.id, pp.title, pp.start_date, pp.end_date, pp.created_at,
               p.display_time, p.posted_at
        FROM popups pp
        LEFT JOIN instagram_posts p ON pp.source_instagram_post_id = p.id
        WHERE pp.created_at >= '2026-01-01'
          AND pp.end_date IS NOT NULL
          AND pp.end_date < date(pp.created_at, '-30 days')
        ORDER BY pp.id
    """)

    results = []
    for row in cursor.fetchall():
        popup_id, title, start, end, created, display_time, posted_at = row

        # display_time이 상대 날짜인지 확인 ("1일", "3시간", "2주" 등)
        is_relative_date = False
        if display_time:
            # "n일", "n시간", "n주", "n달" 또는 "n일전", "n시간전" 등
            relative_keywords = ["일", "주", "시간", "분", "초", "달", "월", "개월"]
            is_relative_date = any(kw in display_time for kw in relative_keywords)

        if not is_relative_date:
            continue  # 상대 날짜가 아니면 스킵

        created_date = datetime.strptime(created[:10], "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()

        diff_days = (created_date - end_date).days

        if diff_days > 30:
            results.append({
                "id": popup_id,
                "title": title[:40] if title else "N/A",
                "start_date": start,
                "end_date": end,
                "created_at": created[:10],
                "diff_days": diff_days,
                "display_time": display_time,
                "posted_at": posted_at[:10] if posted_at else None
            })

    return results


def fix_popups(conn, dry_run=True):
    """팝업 날짜 수정."""
    cursor = conn.cursor()

    targets = analyze_popups(conn)

    if not targets:
        print("수정할 팝업 데이터가 없습니다.")
        return 0

    print(f"\n{'='*80}")
    print(f"팝업 수정 대상: {len(targets)}건")
    print(f"{'='*80}\n")

    for t in targets:
        old_start = t["start_date"]
        old_end = t["end_date"]

        new_start = add_year(old_start) if old_start else None
        new_end = add_year(old_end) if old_end else None

        # 이모지 제거 (cp949 인코딩 문제 방지)
        title_clean = remove_emoji(t['title'][:30]) if t['title'] else 'N/A'
        print(f"ID={t['id']:4d} | {title_clean:30s}")
        print(f"  start: {old_start} -> {new_start}")
        print(f"  end:   {old_end} -> {new_end}")
        print(f"  created: {t['created_at']}, diff: {t['diff_days']}d")
        print(f"  display_time: {t.get('display_time', 'N/A')}, posted_at: {t.get('posted_at', 'N/A')}")
        print()

        if not dry_run:
            cursor.execute("""
                UPDATE popups
                SET start_date = ?, end_date = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (new_start, new_end, t["id"]))

    if not dry_run:
        conn.commit()
        print(f"\n팝업 {len(targets)}건 수정 완료!")
    else:
        print(f"\n[DRY RUN] 실제 수정하려면 --apply 옵션을 추가하세요.")

    return len(targets)


def main():
    import sys

    dry_run = "--apply" not in sys.argv

    db_path = get_db_path()
    print(f"DB 경로: {db_path}")

    if not db_path.exists():
        print(f"DB 파일을 찾을 수 없습니다: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))

    try:
        # Events 수정
        print("\n" + "="*80)
        print("EVENTS 테이블 분석")
        print("="*80)
        event_count = fix_events(conn, dry_run)

        # Popups 수정
        print("\n" + "="*80)
        print("POPUPS 테이블 분석")
        print("="*80)
        popup_count = fix_popups(conn, dry_run)

        # 요약
        print("\n" + "="*80)
        print("요약")
        print("="*80)
        print(f"Events: {event_count}건")
        print(f"Popups: {popup_count}건")
        print(f"Total: {event_count + popup_count}건")

        if dry_run:
            print("\n[DRY RUN] 실제 수정하려면: python fix_event_dates.py --apply")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
