"""
Phase 4: 통합 테스트 및 검증
- 항목 9: 단일 이미지 분류 E2E
- 항목 10: 썸네일 vs 원본 비교
- 항목 11: pHash 그룹 분류 E2E
- 항목 12: 배치 분류 안정성 (10장)
"""
import requests
import time
import sqlite3
import os
import json

API = "http://localhost:8001/api/ic"
DB = "D:/work/project/tools/monitor-page/data/image_classifier.db"
THUMB_DIR = "D:/work/project/tools/monitor-page/data/image_classifier/thumbnails"


def wait_for_completion(timeout=300):
    """분류 완료까지 폴링"""
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{API}/classify/status")
        status = r.json()
        if not status.get("running", False):
            return status
        processed = status.get("processed", 0)
        total = status.get("total", 0)
        current = status.get("current_file", "")
        print(f"  ... {processed}/{total} (current: {current[-40:] if current else ''})")
        time.sleep(5)
    raise TimeoutError(f"Classification did not complete within {timeout}s")


def get_classification(file_id):
    """DB에서 분류 결과 조회"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT fc.id, fc.ai_category_id, cat.full_path, fc.ai_confidence, fc.ai_reasoning, fc.ai_model, fc.status
        FROM file_classifications fc
        LEFT JOIN categories cat ON fc.ai_category_id = cat.id
        WHERE fc.id = ?
    """, (file_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0], "ai_category_id": row[1], "category": row[2],
            "confidence": row[3], "reasoning": row[4], "model": row[5], "status": row[6]
        }
    return None


def reset_classification(file_ids):
    """테스트를 위해 분류 결과 초기화"""
    conn = sqlite3.connect(DB)
    placeholders = ",".join(str(int(i)) for i in file_ids)
    conn.execute(f"""
        UPDATE file_classifications
        SET ai_category_id=NULL, ai_confidence=NULL, ai_reasoning=NULL, ai_model=NULL,
            final_category_id=NULL, status='pending', classified_at=NULL
        WHERE id IN ({placeholders})
    """)
    conn.commit()
    conn.close()


# ============================================================
# 항목 9: 단일 이미지 분류 E2E 테스트
# ============================================================
print("=" * 60)
print("항목 9: 단일 이미지 분류 E2E 테스트")
print("=" * 60)

# 썸네일 있는 미분류 파일 1장 선택
conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute("SELECT id, file_path FROM file_classifications WHERE status='pending' AND ai_category_id IS NULL LIMIT 30")
test_file = None
for fid, fp in c.fetchall():
    if os.path.exists(os.path.join(THUMB_DIR, f"{fid}.jpg")):
        test_file = (fid, fp)
        break
conn.close()

if not test_file:
    print("ERROR: 테스트용 파일 없음")
    exit(1)

file_id, file_path = test_file
print(f"  테스트 파일: id={file_id}, path={file_path}")

start_time = time.time()
r = requests.post(f"{API}/classify/start", json={
    "file_ids": [file_id],
    "model": "claude_cli",
    "batch_size": 1,
})
print(f"  API 응답: {r.status_code} {r.json()}")

if r.status_code == 200:
    status = wait_for_completion(timeout=180)
    elapsed = time.time() - start_time
    print(f"  완료 상태: {json.dumps(status, ensure_ascii=False)}")

    result = get_classification(file_id)
    print(f"  분류 결과: {json.dumps(result, ensure_ascii=False, indent=2)}")
    print(f"  소요 시간: {elapsed:.1f}초")

    if result and result["ai_category_id"]:
        print("  [PASS] 단일 이미지 분류 성공!")
    else:
        print("  [FAIL] 분류 결과 없음")
else:
    print(f"  [FAIL] API 호출 실패: {r.text}")


# ============================================================
# 항목 10: 썸네일 vs 원본 분류 품질 비교
# ============================================================
print("\n" + "=" * 60)
print("항목 10: 썸네일 vs 원본 분류 품질 비교")
print("=" * 60)

# 방금 분류한 파일의 결과를 썸네일 결과로 사용
thumb_result = get_classification(file_id)
if thumb_result and thumb_result["ai_category_id"]:
    thumb_category = thumb_result["category"]
    thumb_confidence = thumb_result["confidence"]
    print(f"  썸네일 분류: category={thumb_category}, confidence={thumb_confidence}")

    # 원본으로 재분류: 썸네일을 임시 이동하여 원본 fallback 유도
    thumb_path = os.path.join(THUMB_DIR, f"{file_id}.jpg")
    thumb_backup = thumb_path + ".bak"

    # 초기화 후 원본으로 재분류
    reset_classification([file_id])
    os.rename(thumb_path, thumb_backup)  # 썸네일 숨김

    try:
        start_time = time.time()
        r = requests.post(f"{API}/classify/start", json={
            "file_ids": [file_id],
            "model": "claude_cli",
            "batch_size": 1,
        })
        if r.status_code == 200:
            status = wait_for_completion(timeout=180)
            elapsed = time.time() - start_time

            orig_result = get_classification(file_id)
            orig_category = orig_result["category"] if orig_result else None
            orig_confidence = orig_result["confidence"] if orig_result else None
            print(f"  원본 분류: category={orig_category}, confidence={orig_confidence}")
            print(f"  소요 시간: {elapsed:.1f}초")

            match = thumb_category == orig_category
            print(f"  결과 일치: {'YES' if match else 'NO'}")
            if match:
                print("  [PASS] 썸네일/원본 분류 결과 동일!")
            else:
                print(f"  [WARN] 불일치 — 썸네일={thumb_category} vs 원본={orig_category}")
        else:
            print(f"  [FAIL] 원본 분류 API 실패: {r.text}")
    finally:
        # 썸네일 복구
        if os.path.exists(thumb_backup):
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            os.rename(thumb_backup, thumb_path)
else:
    print("  [SKIP] 항목 9 실패로 비교 불가")


# ============================================================
# 항목 11: pHash 그룹 분류 E2E 테스트
# ============================================================
print("\n" + "=" * 60)
print("항목 11: pHash 그룹 분류 E2E 테스트")
print("=" * 60)

conn = sqlite3.connect(DB)
c = conn.cursor()

# 멤버 3~5개인 미분류 그룹 찾기
c.execute("""
    SELECT dg.id, dg.member_count
    FROM duplicate_groups dg
    WHERE dg.member_count BETWEEN 3 AND 5
    LIMIT 5
""")
test_group = None
for gid, mc in c.fetchall():
    c.execute("""
        SELECT dm.file_id FROM duplicate_members dm
        JOIN file_classifications fc ON dm.file_id = fc.id
        WHERE dm.group_id = ? AND fc.ai_category_id IS NULL
        ORDER BY dm.quality_score DESC
    """, (gid,))
    member_ids = [r[0] for r in c.fetchall()]
    if len(member_ids) >= 3:
        # 대표(첫번째)에 썸네일 있는지 확인
        if os.path.exists(os.path.join(THUMB_DIR, f"{member_ids[0]}.jpg")):
            test_group = (gid, member_ids)
            break

conn.close()

if test_group:
    gid, member_ids = test_group
    print(f"  테스트 그룹: id={gid}, 멤버={member_ids}")

    # 초기화
    reset_classification(member_ids)

    start_time = time.time()
    r = requests.post(f"{API}/classify/start", json={
        "file_ids": member_ids,
        "model": "claude_cli",
        "batch_size": len(member_ids),
    })
    print(f"  API 응답: {r.status_code} {r.json()}")

    if r.status_code == 200:
        status = wait_for_completion(timeout=300)
        elapsed = time.time() - start_time
        print(f"  완료 상태: {json.dumps(status, ensure_ascii=False)}")

        # 전체 멤버의 분류 결과 확인
        results = {}
        for mid in member_ids:
            results[mid] = get_classification(mid)

        categories = set()
        all_classified = True
        for mid, res in results.items():
            cat = res["category"] if res else None
            conf = res["confidence"] if res else None
            reasoning = (res["reasoning"] or "")[:50] if res else ""
            print(f"    file_id={mid}: category={cat}, confidence={conf}, reasoning={reasoning}")
            if cat:
                categories.add(cat)
            else:
                all_classified = False

        print(f"  소요 시간: {elapsed:.1f}초")
        print(f"  고유 카테고리 수: {len(categories)}")

        if all_classified and len(categories) == 1:
            print("  [PASS] 그룹 전체 동일 카테고리 분류 성공!")
        elif all_classified:
            print(f"  [WARN] 분류 완료되었으나 카테고리 불일치: {categories}")
        else:
            print("  [FAIL] 일부 멤버 미분류")
    else:
        print(f"  [FAIL] API 호출 실패: {r.text}")
else:
    print("  [SKIP] 적합한 테스트 그룹 없음")


# ============================================================
# 항목 12: 배치 분류 안정성 (10장)
# ============================================================
print("\n" + "=" * 60)
print("항목 12: 배치 분류 안정성 테스트 (10장)")
print("=" * 60)

conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute("SELECT id FROM file_classifications WHERE status='pending' AND ai_category_id IS NULL LIMIT 100")
batch_candidates = []
for (fid,) in c.fetchall():
    if os.path.exists(os.path.join(THUMB_DIR, f"{fid}.jpg")):
        batch_candidates.append(fid)
        if len(batch_candidates) >= 10:
            break
conn.close()

if len(batch_candidates) >= 10:
    print(f"  배치 파일 IDs: {batch_candidates}")

    # 초기화
    reset_classification(batch_candidates)

    start_time = time.time()
    r = requests.post(f"{API}/classify/start", json={
        "file_ids": batch_candidates,
        "model": "claude_cli",
        "batch_size": 10,
    })
    print(f"  API 응답: {r.status_code} {r.json()}")

    if r.status_code == 200:
        status = wait_for_completion(timeout=600)
        elapsed = time.time() - start_time

        # 결과 집계
        success = 0
        fail = 0
        for fid in batch_candidates:
            res = get_classification(fid)
            if res and res["ai_category_id"]:
                success += 1
            else:
                fail += 1

        print(f"  완료: 성공={success}, 실패={fail}, 소요={elapsed:.1f}초")
        print(f"  평균 소요: {elapsed/10:.1f}초/장")

        if success >= 8:  # 80% 이상 성공
            print("  [PASS] 배치 분류 안정성 확인!")
        else:
            print(f"  [FAIL] 성공률 {success}/10 < 80%")
    else:
        print(f"  [FAIL] API 호출 실패: {r.text}")
else:
    print(f"  [SKIP] 썸네일 있는 파일 부족 ({len(batch_candidates)}/10)")


print("\n" + "=" * 60)
print("Phase 4 테스트 완료")
print("=" * 60)
