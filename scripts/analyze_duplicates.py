import sqlite3
import sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/monitor.db')
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
