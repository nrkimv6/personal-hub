"""AI 분류 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text
from unittest.mock import patch, AsyncMock


@pytest.fixture
def seeded_files_for_classify(test_db, tmp_path):
    """AI 분류 테스트용 파일 데이터"""
    from PIL import Image

    # 카테고리 생성
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'Travel')
    """))

    # 5개 미분류 파일 생성
    for i in range(1, 6):
        # 이미지 파일 생성
        img = Image.new("RGB", (100, 100), color=(i*50 % 256, 0, 0))
        path = tmp_path / f"img{i}.jpg"
        img.save(str(path))

        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, 'hash', 'pending')
        """), {"id": i, "path": str(path)})

    test_db.commit()


# ================================================
# Right: 기본 CRUD 동작
# ================================================

def test_start_classification(client, seeded_files_for_classify, test_db):
    """14.11 Right: POST /start → 백그라운드 시작"""
    # Mock adapter to prevent actual CLI execution
    with patch("app.modules.image_classifier.routers.classify.ClaudeCLIAdapter") as MockAdapter:
        mock_instance = AsyncMock()
        mock_instance.classify_image = AsyncMock(return_value=None)
        MockAdapter.return_value = mock_instance

        response = client.post("/api/ic/classify/start", json={
            "model": "claude_cli",
            "batch_size": 10,
            "gap_minutes": 60
        })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "running"
    assert data["total"] == 5
    assert "started" in data["message"].lower()


def test_get_status(client, seeded_files_for_classify):
    """14.12 Right: GET /status → 진행 상태 조회"""
    # Reset status first
    from app.modules.image_classifier.routers.classify import classification_status
    classification_status["running"] = False
    classification_status["total"] = 10
    classification_status["processed"] = 3
    classification_status["failed"] = 1

    response = client.get("/api/ic/classify/status")

    assert response.status_code == 200
    data = response.json()

    assert "running" in data
    assert "total" in data
    assert "processed" in data
    assert data["total"] == 10
    assert data["processed"] == 3


def test_stop_classification(client, seeded_files_for_classify):
    """14.13 Right: POST /stop → 분류 중지"""
    # Set status to running first
    from app.modules.image_classifier.routers.classify import classification_status
    classification_status["running"] = True

    response = client.post("/api/ic/classify/stop")

    assert response.status_code == 200
    data = response.json()

    assert "stopped" in data["message"].lower()


# ================================================
# Error: 예외 처리
# ================================================

def test_start_duplicate_classification(client, seeded_files_for_classify):
    """14.14 Error: 이미 실행 중 → 400"""
    # Set status to running
    from app.modules.image_classifier.routers.classify import classification_status
    classification_status["running"] = True

    response = client.post("/api/ic/classify/start", json={
        "model": "claude_cli"
    })

    assert response.status_code == 400
    assert "already running" in response.json()["detail"].lower()


def test_start_no_files(client, test_db):
    """14.15 Error: 분류할 파일 없음 → 400"""
    # Reset status first
    from app.modules.image_classifier.routers.classify import classification_status
    classification_status["running"] = False

    # No files in DB
    response = client.post("/api/ic/classify/start", json={
        "model": "claude_cli"
    })

    assert response.status_code == 400
    assert "no files" in response.json()["detail"].lower()
