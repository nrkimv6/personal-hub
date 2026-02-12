"""파일 API 엔드포인트 테스트"""
import pytest
from datetime import datetime
from sqlalchemy import text
from PIL import Image


@pytest.fixture
def seeded_files(test_db, tmp_path):
    """테스트용 파일 데이터 생성"""
    # 카테고리 먼저 생성
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (1, 'Category 1', 'Category 1')
    """))
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (2, 'Category 2', 'Category 2')
    """))

    # 여러 상태/카테고리의 파일 생성
    files_data = [
        (1, "pending", None, "2023-01-01", "high"),
        (2, "ai_classified", 1, "2023-02-15", "medium"),
        (3, "approved", 1, "2023-03-20", "high"),
        (4, "pending", 2, "2023-04-10", "low"),
        (5, "ai_classified", None, "2023-05-05", "medium"),
    ]

    for file_id, status, cat_id, date, importance in files_data:
        test_db.execute(text("""
            INSERT INTO file_classifications (
                id, file_path, file_hash, file_size, status,
                final_category_id, extracted_date, importance
            ) VALUES (
                :id, :path, 'hash', 10000, :status,
                :cat_id, :date, :importance
            )
        """), {
            "id": file_id,
            "path": f"/test/file{file_id}.jpg",
            "status": status,
            "cat_id": cat_id,
            "date": date,
            "importance": importance
        })

    test_db.commit()
    return files_data


# ================================================
# Right: 기본 조회 및 필터
# ================================================

def test_get_file_list_default(seeded_files, client):
    """8E.1 Right: GET / → 기본 페이지네이션"""
    response = client.get("/api/ic/files")

    assert response.status_code == 200
    data = response.json()

    assert "files" in data
    assert len(data["files"]) == 5  # 전체 5개
    assert "skip" in data
    assert "limit" in data


def test_filter_by_status(seeded_files, client):
    """8E.2 Right: status=pending/ai_classified/approved"""
    # pending 필터
    response = client.get("/api/ic/files?status=pending")
    assert response.status_code == 200
    files = response.json()["files"]

    # 모든 파일이 pending 상태
    assert len(files) == 2  # file 1, 4
    for file in files:
        assert file["status"] == "pending"


def test_filter_by_category(seeded_files, client):
    """8E.3 Right: category_id 필터"""
    response = client.get("/api/ic/files?category_id=1")

    assert response.status_code == 200
    files = response.json()["files"]

    # category_id=1인 파일만
    assert len(files) == 2  # file 2, 3
    for file in files:
        assert file["final_category_id"] == 1


def test_filter_by_date_range(seeded_files, client):
    """8E.4 Right: date_from, date_to"""
    # 2023-02-01 ~ 2023-04-15 범위
    response = client.get("/api/ic/files?date_from=2023-02-01&date_to=2023-04-15")

    assert response.status_code == 200
    files = response.json()["files"]

    # file 2, 3, 4
    assert len(files) == 3

    # 날짜 확인
    for file in files:
        date_str = file["extracted_date"]
        if date_str:
            file_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            assert datetime(2023, 2, 1) <= file_date <= datetime(2023, 4, 15)


def test_filter_by_importance(seeded_files, client):
    """8E.5 Right: importance=high/medium/low"""
    response = client.get("/api/ic/files?importance=high")

    assert response.status_code == 200
    files = response.json()["files"]

    # high 파일만 (file 1, 3)
    assert len(files) == 2
    for file in files:
        assert file["importance"] == "high"


def test_order_by_and_direction(seeded_files, client):
    """8E.6 Right: order_by=id/extracted_date, order_dir=asc/desc"""
    # ID 내림차순
    response_desc = client.get("/api/ic/files?order_by=id&order_dir=desc")
    assert response_desc.status_code == 200
    files_desc = response_desc.json()["files"]

    # 첫 번째가 file 5
    assert files_desc[0]["id"] == 5
    assert files_desc[-1]["id"] == 1

    # ID 오름차순
    response_asc = client.get("/api/ic/files?order_by=id&order_dir=asc")
    assert response_asc.status_code == 200
    files_asc = response_asc.json()["files"]

    # 첫 번째가 file 1
    assert files_asc[0]["id"] == 1
    assert files_asc[-1]["id"] == 5


# ================================================
# Boundary: 페이지네이션
# ================================================

def test_pagination_skip_limit(seeded_files, client):
    """8E.7 Boundary: skip=0,limit=10 → skip=10,limit=10"""
    # 첫 페이지: skip=0, limit=2
    response_page1 = client.get("/api/ic/files?skip=0&limit=2")
    assert response_page1.status_code == 200
    page1 = response_page1.json()["files"]
    assert len(page1) == 2

    # 두 번째 페이지: skip=2, limit=2
    response_page2 = client.get("/api/ic/files?skip=2&limit=2")
    assert response_page2.status_code == 200
    page2 = response_page2.json()["files"]
    assert len(page2) == 2

    # 첫 페이지와 두 번째 페이지 파일이 달라야 함
    page1_ids = {file["id"] for file in page1}
    page2_ids = {file["id"] for file in page2}
    assert len(page1_ids & page2_ids) == 0  # 교집합 없음


def test_empty_result(seeded_files, client):
    """8E.8 Boundary: 필터 조건에 맞는 결과 없음 → 빈 배열"""
    # 존재하지 않는 카테고리
    response = client.get("/api/ic/files?category_id=9999")

    assert response.status_code == 200
    files = response.json()["files"]

    assert len(files) == 0
    assert files == []


# ================================================
# Right: 썸네일 서빙
# ================================================

def test_get_thumbnail_image(seeded_files, client, test_db, tmp_path):
    """8E.9 Right: GET /{id}/thumbnail → JPEG 바이너리"""
    from app.modules.image_classifier.workers.thumbnail import ThumbnailWorker
    from app.modules.image_classifier.config import ImageClassifierSettings

    # 원본 이미지 생성
    img = Image.new("RGB", (400, 400), color="lime")
    original = tmp_path / "original.jpg"
    img.save(str(original))

    # file 1의 경로 업데이트
    test_db.execute(text("""
        UPDATE file_classifications SET file_path = :path WHERE id = 1
    """), {"path": str(original)})
    test_db.commit()

    # 썸네일 생성
    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)
    worker._create_thumbnail(1, original)

    # API 호출 (실제 settings.THUMBNAIL_DIR 사용)
    # 테스트에서는 monkeypatch로 settings를 변경해야 하는데,
    # 간단하게 파일을 실제 경로에 복사
    import shutil
    from app.modules.image_classifier.workers.thumbnail import get_thumbnail_path

    real_thumb_path = get_thumbnail_path(1, ImageClassifierSettings())
    real_thumb_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(settings.THUMBNAIL_DIR / "1.jpg"), str(real_thumb_path))

    # API 호출
    response = client.get("/api/ic/files/1/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0  # 바이너리 데이터 존재


# ================================================
# Error: 썸네일 없음
# ================================================

def test_thumbnail_not_found(seeded_files, client):
    """8E.10 Error: 썸네일 없음 → 404"""
    # 썸네일이 생성되지 않은 파일
    response = client.get("/api/ic/files/999/thumbnail")

    assert response.status_code == 404
    assert "썸네일이 생성되지 않았습니다" in response.json()["detail"]
