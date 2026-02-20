"""E2E 분류 테스트 스크립트"""
import sqlite3
import requests
import time
import sys

DB = r"D:\work\project\tools\monitor-page\data\image_classifier.db"
API = "http://localhost:8001/api/ic/classify"

def get_unclassified(limit=3):
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT id, file_path FROM file_classifications
        WHERE status = 'pending' OR (status = 'folder_mapped' AND ai_category_id IS NULL)
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows

def start_classify(file_ids):
    resp = requests.post(f"{API}/start", json={"file_ids": file_ids, "model": "claude_cli", "batch_size": 5})
    print(f"Start: {resp.status_code} {resp.json()}")
    return resp.ok

def poll_status(timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{API}/status")
        data = resp.json()
        running = data.get("running", False)
        processed = data.get("processed", 0)
        failed = data.get("failed", 0)
        total = data.get("total", 0)
        print(f"  [{int(time.time()-start)}s] running={running} processed={processed} failed={failed} total={total}")
        if not running:
            return data
        time.sleep(5)
    print("TIMEOUT!")
    return None

def check_results(file_ids):
    conn = sqlite3.connect(DB)
    for fid in file_ids:
        row = conn.execute("""
            SELECT id, status, ai_category_id, ai_confidence, ai_reasoning, ai_model
            FROM file_classifications WHERE id = ?
        """, (fid,)).fetchone()
        print(f"  #{row[0]}: status={row[1]}, cat_id={row[2]}, conf={row[3]}, model={row[5]}")
        if row[4]:
            print(f"    reasoning: {row[4][:100]}")
    conn.close()

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    files = get_unclassified(n)
    if not files:
        print("미분류 파일 없음!")
        sys.exit(1)

    file_ids = [f[0] for f in files]
    print(f"\n=== E2E 테스트: {len(files)}장 ===")
    for fid, fpath in files:
        print(f"  #{fid}: {fpath}")

    print(f"\n--- 분류 시작 ---")
    if not start_classify(file_ids):
        sys.exit(1)

    print(f"\n--- 폴링 (max 180s) ---")
    result = poll_status()

    print(f"\n--- 결과 확인 ---")
    check_results(file_ids)
