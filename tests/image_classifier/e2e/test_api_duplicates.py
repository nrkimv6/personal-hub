"""중복 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text
from PIL import Image


@pytest.fixture
async def seeded_duplicates(client, test_db, tmp_path):
    """중복 그룹이 있는 DB 상태 생성"""
    from app.modules.image_classifier.workers.phash import PHashWorker
    from app.modules.image_classifier.workers.duplicate_detector import DuplicateDetector
    from app.modules.image_classifier.config import ImageClassifierSettings

    # 2개의 동일한 이미지 생성
    img = Image.new("RGB", (200, 200), color="purple")
    path1 = tmp_path / "dup1.jpg"
    path2 = tmp_path / "dup2.jpg"
    img.save(str(path1))
    img.save(str(path2))

    # DB에 파일 등록
    for idx, path in enumerate([path1, path2], start=1):
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, file_size, status)
            VALUES (:id, :path, 'hash123', 10000, 'pending')
        """), {"id": idx, "path": str(path)})

    settings = ImageClassifierSettings()
    phash_worker = PHashWorker(test_db, settings)

    # pHash 계산
    for idx, path in enumerate([path1, path2], start=1):
        phash = phash_worker._compute_phash(path)
        test_db.execute(text("""
            INSERT INTO image_features (file_id, phash) VALUES (:fid, :phash)
        """), {"fid": idx, "phash": phash})

    test_db.commit()

    # 중복 감지 실행
    detector = DuplicateDetector(test_db, settings)
    await detector.detect_duplicates()

    return {"file1_id": 1, "file2_id": 2, "paths": [path1, path2]}


# ================================================
# Right: 기본 CRUD 동작
# ================================================

@pytest.mark.asyncio
async def test_get_duplicate_groups_list(seeded_duplicates, client):
    """7E.1 Right: GET / → 그룹 목록"""
    response = client.get("/api/ic/duplicates")

    assert response.status_code == 200
    data = response.json()

    assert "groups" in data
    assert len(data["groups"]) >= 1

    # 첫 번째 그룹 검증
    group = data["groups"][0]
    assert "group_id" in group
    assert "group_hash" in group
    assert "member_count" in group
    assert "status" in group


@pytest.mark.asyncio
async def test_get_group_detail_with_members(seeded_duplicates, client, test_db):
    """7E.2 Right: GET /{id} → 멤버 포함 상세"""
    # 생성된 그룹 ID 조회
    group_result = test_db.execute(text("""
        SELECT id FROM duplicate_groups LIMIT 1
    """)).fetchone()

    group_id = group_result.id

    # API 호출
    response = client.get(f"/api/ic/duplicates/{group_id}")

    assert response.status_code == 200
    data = response.json()

    assert data["group_id"] == group_id
    assert "members" in data
    assert len(data["members"]) >= 2

    # 멤버 검증
    member = data["members"][0]
    assert "file_id" in member
    assert "file_path" in member
    assert "file_size" in member
    assert "quality_score" in member


@pytest.mark.asyncio
async def test_resolve_keep_best_quality(seeded_duplicates, client, test_db):
    """7E.3 Right: POST /{id}/resolve → 상태 변경"""
    # 그룹 ID 조회
    group_result = test_db.execute(text("""
        SELECT id FROM duplicate_groups LIMIT 1
    """)).fetchone()

    group_id = group_result.id
    keep_file_id = seeded_duplicates["file1_id"]

    # resolve 요청
    response = client.post(f"/api/ic/duplicates/{group_id}/resolve", json={
        "keep_file_id": keep_file_id,
        "delete_others": False  # 테스트에서는 삭제하지 않음
    })

    assert response.status_code == 200

    # 그룹 상태 확인
    updated = test_db.execute(text("""
        SELECT status, kept_file_id FROM duplicate_groups WHERE id = :gid
    """), {"gid": group_id}).fetchone()

    assert updated.status == "resolved"
    assert updated.kept_file_id == keep_file_id


# ================================================
# Boundary: 필터링
# ================================================

@pytest.mark.asyncio
async def test_filter_by_status(seeded_duplicates, client, test_db):
    """7E.4 Boundary: status=pending/resolved/ignored"""
    # pending 필터
    response_pending = client.get("/api/ic/duplicates?status=pending")
    assert response_pending.status_code == 200
    pending_groups = response_pending.json()["groups"]

    # 모든 그룹이 pending 상태여야 함
    for group in pending_groups:
        assert group["status"] == "pending"

    # resolved 필터 (현재는 0개)
    response_resolved = client.get("/api/ic/duplicates?status=resolved")
    assert response_resolved.status_code == 200


# ================================================
# Error: 예외 처리
# ================================================

def test_resolve_nonexistent_group(client):
    """7E.5 Error: 존재하지 않는 그룹 → 404"""
    response = client.post("/api/ic/duplicates/9999/resolve", json={
        "keep_file_id": 1,
        "delete_others": False
    })

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_non_member_file(seeded_duplicates, client, test_db):
    """7E.6 Error: 그룹 멤버가 아닌 파일 → 400"""
    # 그룹 ID 조회
    group_result = test_db.execute(text("""
        SELECT id FROM duplicate_groups LIMIT 1
    """)).fetchone()

    group_id = group_result.id

    # 존재하지 않는 파일 ID로 resolve 시도
    response = client.post(f"/api/ic/duplicates/{group_id}/resolve", json={
        "keep_file_id": 9999,  # 그룹 멤버가 아님
        "delete_others": False
    })

    assert response.status_code == 400
    assert "멤버가 아닙니다" in response.json()["detail"]
