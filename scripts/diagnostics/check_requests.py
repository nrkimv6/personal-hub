import sqlite3

conn = sqlite3.connect(r'D:\work\project\tools\monitor-page\data\monitor.db')
cur = conn.cursor()

print("=== 피드가 아닌 요청들 ===")
cur.execute("""
    SELECT id, request_type, target_url, target_post_id, status, requested_by
    FROM instagram_crawl_requests
    WHERE request_type != 'feed'
    ORDER BY id DESC
    LIMIT 20
""")
for row in cur.fetchall():
    print(row)

print("\n=== URL이 없는 single_post_url 요청 ===")
cur.execute("""
    SELECT id, request_type, target_url, target_post_id, status
    FROM instagram_crawl_requests
    WHERE request_type = 'single_post_url' AND (target_url IS NULL OR target_url = '')
""")
rows = cur.fetchall()
print(f"총 {len(rows)}건")
for row in rows:
    print(row)

conn.close()
