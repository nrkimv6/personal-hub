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


# ===========================================================================
# 폴더 쌍 분석 e2e 테스트
# ===========================================================================

def _insert_e2e_file(test_db, file_id: int, file_path: str):
    """e2e 테스트용 파일 레코드 삽입"""
    import hashlib
    file_hash = hashlib.md5(file_path.encode()).hexdigest()
    test_db.execute(text("""
        INSERT OR IGNORE INTO file_classifications (id, file_path, file_hash, status)
        VALUES (:id, :fp, :fh, 'pending')
    """), {"id": file_id, "fp": file_path, "fh": file_hash})
    test_db.commit()


def _setup_e2e_pair_data(test_db, base_id=100):
    """폴더 쌍 테스트 데이터 셋업 (ID 충돌 방지용 base_id)"""
    files = [
        (base_id + 0, "D:\folderA\img1.jpg"),
        (base_id + 1, "D:\folderA\img2.jpg"),
        (base_id + 2, "D:\folderB\img1.jpg"),
        (base_id + 3, "D:\folderB\img2.jpg"),
    ]
    for fid, fp in files:
        _insert_e2e_file(test_db, fid, fp)

    # A-B 쌍 그룹 2개
    for i in range(2):
        test_db.execute(text("INSERT INTO duplicate_groups (group_hash, status, member_count) VALUES (:h, 'pending', 2)"),
                        {"h": f"e2e_ab_hash_{i}"})
        test_db.commit()
        gid = test_db.execute(text("SELECT id FROM duplicate_groups ORDER BY id DESC LIMIT 1")).scalar()
        test_db.execute(text("INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:g, :f, 0)"),
                        {"g": gid, "f": base_id + i})
        test_db.execute(text("INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:g, :f, 0)"),
                        {"g": gid, "f": base_id + 2 + i})
        test_db.commit()

    return [gid - 1, gid]


@pytest.mark.asyncio
async def test_get_folder_pair_analysis_http(client, test_db):
    """GET /folder-pair-analysis → 200 응답 + pairs 구조 확인"""
    _setup_e2e_pair_data(test_db)

    response = client.get("/api/ic/duplicates/folder-pair-analysis")

    assert response.status_code == 200
    data = response.json()
    assert "pairs" in data
    pairs = data["pairs"]
    assert len(pairs) >= 1

    pair = pairs[0]
    assert "folder_a" in pair
    assert "folder_b" in pair
    assert "group_count" in pair
    assert "file_count" in pair
    assert "group_ids" in pair
    assert isinstance(pair["group_ids"], list)


@pytest.mark.asyncio
async def test_resolve_by_folder_pair_http(client, test_db):
    """POST /resolve-by-folder-pair → 정상 해결 + file_path_aliases 저장 확인"""
    group_ids = _setup_e2e_pair_data(test_db, base_id=200)

    response = client.post("/api/ic/duplicates/resolve-by-folder-pair", json={
        "keep_folder": "D:\folderA",
        "other_folder": "D:\folderB",
        "group_ids": group_ids,
    })

    assert response.status_code == 200
    data = response.json()
    assert data["resolved_count"] > 0

    # file_path_aliases가 저장됐는지 확인
    alias_count = test_db.execute(text(
        "SELECT COUNT(*) FROM file_path_aliases WHERE source = 'duplicate_merge'"
    )).scalar()
    assert alias_count > 0


@pytest.mark.asyncio
async def test_resolve_by_folder_pair_empty_groups(client):
    """POST /resolve-by-folder-pair with empty group_ids → 400 에러 응답"""
    response = client.post("/api/ic/duplicates/resolve-by-folder-pair", json={
        "keep_folder": "D:\folderA",
        "other_folder": "D:\folderB",
        "group_ids": [],
    })

    assert response.status_code == 400
    assert "group_ids" in response.json()["detail"].lower() or "비어있" in response.json()["detail"]
