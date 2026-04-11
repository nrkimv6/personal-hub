"""Phase 4 테스트 데이터 조회 스크립트"""
import sqlite3
import os

DB = "D:/work/project/tools/monitor-page/data/image_classifier.db"
THUMB_DIR = "D:/work/project/tools/monitor-page/data/image_classifier/thumbnails"

conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. 미분류 + 썸네일 있는 파일
c.execute("SELECT id, file_path FROM file_classifications WHERE status='pending' AND ai_category_id IS NULL LIMIT 50")
found = []
for fid, fp in c.fetchall():
    thumb = os.path.join(THUMB_DIR, f"{fid}.jpg")
    if os.path.exists(thumb):
        sz = os.path.getsize(thumb)
        found.append((fid, fp, sz))
        if len(found) >= 5:
            break

print("== Pending files with thumbnails ==")
for fid, fp, sz in found:
    print(f"  id={fid} thumb_kb={sz/1024:.1f} path={fp}")

# 2. 중복그룹 (멤버3+) 중 미분류
c.execute("""
    SELECT dg.id, dg.member_count
    FROM duplicate_groups dg
    WHERE dg.member_count >= 3
    ORDER BY dg.member_count DESC LIMIT 5
""")
groups = c.fetchall()
print(f"\n== Dup groups (3+ members, top 5) ==")
for gid, mc in groups:
    c.execute("""
        SELECT dm.file_id, fc.ai_category_id, fc.status, dm.quality_score
        FROM duplicate_members dm
        JOIN file_classifications fc ON dm.file_id = fc.id
        WHERE dm.group_id = ?
        ORDER BY dm.quality_score DESC
    """, (gid,))
    members = c.fetchall()
    repr_id = members[0][0] if members else None
    has_thumb = os.path.exists(os.path.join(THUMB_DIR, f"{repr_id}.jpg")) if repr_id else False
    unclassified = sum(1 for m in members if m[1] is None)
    print(f"  group={gid} members={mc} repr_id={repr_id} has_thumb={has_thumb} unclassified={unclassified}/{len(members)}")

# 3. 카테고리
c.execute("SELECT id, full_path FROM categories ORDER BY id")
print("\n== Categories ==")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 4. 이미 분류된 파일 샘플 (원본 비교용)
c.execute("""
    SELECT fc.id, fc.file_path, fc.ai_category_id, cat.full_path, fc.ai_confidence
    FROM file_classifications fc
    LEFT JOIN categories cat ON fc.ai_category_id = cat.id
    WHERE fc.ai_category_id IS NOT NULL LIMIT 3
""")
print("\n== Already classified ==")
for row in c.fetchall():
    print(f"  id={row[0]} cat={row[3]} conf={row[4]} path={row[1]}")

# 5. 썸네일 디렉토리 통계
if os.path.exists(THUMB_DIR):
    files = os.listdir(THUMB_DIR)
    print(f"\n== Thumbnails: {len(files)} files ==")

conn.close()
