"""Instagram 게시물 중복 URL 진단 스크립트 (SQLite 전용 레거시 read-only).

⚠️ LEGACY: 이 스크립트는 SQLite data/monitor.db 직접 접근을 사용합니다.
   2026-04-10 PostgreSQL 전환 이후에는 data/monitor.db가 운영 DB가 아닙니다.
   DB 파일이 존재하지 않으면 스크립트가 종료됩니다.
   현재 운영 DB 조회는 Admin API 또는 SQLAlchemy 세션 기반으로 수행하세요.
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "monitor.db"
if not _DB_PATH.exists():
    print(f"❌ SQLite DB를 찾을 수 없습니다: {_DB_PATH}")
    print("이 스크립트는 SQLite 전용 레거시입니다. 운영 DB 조회는 Admin API를 사용하세요.")
    sys.exit(1)

conn = sqlite3.connect(str(_DB_PATH))
cur = conn.cursor()

print('=== 같은 크롤링 세션(crawl_run_id)에서 URL NULL 개수 ===')
cur.execute('''
    SELECT crawl_run_id, COUNT(*) as total,
           SUM(CASE WHEN url IS NULL THEN 1 ELSE 0 END) as null_urls
    FROM instagram_posts
    GROUP BY crawl_run_id
    ORDER BY crawl_run_id DESC
    LIMIT 10
''')
for row in cur.fetchall():
    print(f'  run {row[0]}: total={row[1]}, null_url={row[2]}')

print()
print('=== URL NULL 게시물의 광고 여부 ===')
cur.execute('''
    SELECT is_ad, COUNT(*)
    FROM instagram_posts
    WHERE url IS NULL
    GROUP BY is_ad
''')
for row in cur.fetchall():
    print(f'  is_ad={row[0]}: {row[1]}')

print()
print('=== 같은 caption이 여러번 저장된 경우 (진짜 중복) ===')
cur.execute('''
    SELECT COUNT(*) as cnt, substr(caption, 1, 50) as caption_prefix, account
    FROM instagram_posts
    WHERE caption IS NOT NULL AND length(caption) > 20
    GROUP BY substr(caption, 1, 100), account
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC
    LIMIT 10
''')
rows = cur.fetchall()
print(f'중복 caption 그룹: {len(rows)}개')
for row in rows[:5]:
    print(f'  {row[0]}x: @{row[2]} - {row[1][:40]}...')

conn.close()
