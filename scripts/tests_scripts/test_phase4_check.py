"""Phase 4 테스트 결과 확인"""
import sqlite3, os, json

DB = "D:/work/project/tools/monitor-page/data/image_classifier.db"
THUMB_DIR = "D:/work/project/tools/monitor-page/data/image_classifier/thumbnails"

conn = sqlite3.connect(DB)
c = conn.cursor()

# 최근 분류된 파일 확인
c.execute("""
    SELECT fc.id, fc.status, cat.full_path, fc.ai_confidence, fc.ai_reasoning, fc.ai_model, fc.classified_at
    FROM file_classifications fc
    LEFT JOIN categories cat ON fc.ai_category_id = cat.id
    WHERE fc.ai_category_id IS NOT NULL
    ORDER BY fc.classified_at DESC NULLS LAST
    LIMIT 20
""")
print("== Recently classified files ==")
for row in c.fetchall():
    fid, status, cat, conf, reason, model, at = row
    reason_short = (reason or "")[:60]
    print(f"  id={fid} status={status} cat={cat} conf={conf} model={model} at={at} reason={reason_short}")

# 분류 통계
c.execute("SELECT status, count(*) FROM file_classifications GROUP BY status ORDER BY count(*) DESC")
print("\n== Status counts ==")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 그룹 복사 확인 (reasoning에 '그룹 복사' 포함)
c.execute("""
    SELECT count(*) FROM file_classifications
    WHERE ai_reasoning LIKE '%group copy%' OR ai_reasoning LIKE '%그룹 복사%'
""")
gc = c.fetchone()[0]
print(f"\n== Group-copied classifications: {gc} ==")

conn.close()
