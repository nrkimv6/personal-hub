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
    with patch("app.modules.image_classifier.routers.classify.run_classification",
               new=AsyncMock(return_value=None)):
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


# ================================================
# E2E 추가 케이스 (Bug #1~#6 수정 검증)
# ================================================

def test_e2e_classify_start_enqueue_success(client, seeded_files_for_classify, test_db):
    """14.16 Right: LLM 큐 enqueue 성공 → 분류 시작."""
    from app.modules.image_classifier.routers.classify import classification_status

    classification_status["running"] = False

    with patch("app.modules.image_classifier.routers.classify.run_classification",
               new=AsyncMock(return_value=None)):
        response = client.post("/api/ic/classify/start", json={
            "model": "claude_cli",
            "batch_size": 10,
        })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["total"] == 5


def test_e2e_classify_status_running(client, seeded_files_for_classify):
    """14.17 Right: 진행 중 상태 조회 → running=True + 수치 정확."""
    from app.modules.image_classifier.routers.classify import classification_status

    classification_status["running"] = True
    classification_status["total"] = 5
    classification_status["processed"] = 2
    classification_status["failed"] = 0

    response = client.get("/api/ic/classify/status")

    assert response.status_code == 200
    data = response.json()
    assert data["running"] is True
    assert data["total"] == 5
    assert data["processed"] == 2

    # 정리
    classification_status["running"] = False


def test_e2e_classify_stop_success(client):
    """14.18 Right: 실행 중 정상 중지 → 200."""
    from app.modules.image_classifier.routers.classify import classification_status
    classification_status["running"] = True

    response = client.post("/api/ic/classify/stop")

    assert response.status_code == 200
    data = response.json()
    assert "stopped" in data["message"].lower() or "stop" in data["message"].lower()
    assert classification_status["running"] is False


def test_e2e_classify_stop_not_running(client):
    """14.19 Error: 실행 중 아닌데 중지 → 400."""
    from app.modules.image_classifier.routers.classify import classification_status
    classification_status["running"] = False

    response = client.post("/api/ic/classify/stop")

    assert response.status_code == 400
    assert "no classification running" in response.json()["detail"].lower()


def test_e2e_classify_file_ids_filter(client, test_db):
    """14.20 CORRECT: file_ids 지정 시 해당 파일만 분류 대상."""
    from PIL import Image
    import tempfile, os
    from app.modules.image_classifier.routers.classify import classification_status
    from sqlalchemy import text

    classification_status["running"] = False

    # 카테고리 추가
    test_db.execute(text("INSERT OR IGNORE INTO categories (id, name, full_path) VALUES (1, 'Test', 'Test')"))

    # 파일 10개 추가
    tmpdir = tempfile.mkdtemp()
    for i in range(1, 11):
        img = Image.new("RGB", (50, 50), color=(i * 20, 0, 0))
        path = os.path.join(tmpdir, f"f{i}.jpg")
        img.save(path)
        test_db.execute(text("""
            INSERT OR REPLACE INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, :hash, 'pending')
        """), {"id": i, "path": path, "hash": f"h{i}"})
    test_db.commit()

    with patch("app.modules.image_classifier.routers.classify.run_classification",
               new=AsyncMock(return_value=None)):
        response = client.post("/api/ic/classify/start", json={
            "model": "claude_cli",
            "file_ids": [1, 2, 3],
        })

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3, "file_ids=[1,2,3] → total은 3이어야 함"

    classification_status["running"] = False


def test_e2e_classify_single_file(client, test_db):
    """14.21 Boundary: 파일 1건만 분류 → total=1."""
    from PIL import Image
    import tempfile, os
    from app.modules.image_classifier.routers.classify import classification_status
    from sqlalchemy import text

    classification_status["running"] = False

    # 기존 파일 모두 삭제 후 1건만
    test_db.execute(text("DELETE FROM file_classifications"))
    test_db.execute(text("INSERT OR IGNORE INTO categories (id, name, full_path) VALUES (1, 'Test', 'Test')"))

    tmpdir = tempfile.mkdtemp()
    img = Image.new("RGB", (50, 50))
    path = os.path.join(tmpdir, "single.jpg")
    img.save(path)
    test_db.execute(text("""
        INSERT INTO file_classifications (file_path, file_hash, status)
        VALUES (:path, 'singlehash', 'pending')
    """), {"path": path})
    test_db.commit()

    with patch("app.modules.image_classifier.routers.classify.run_classification",
               new=AsyncMock(return_value=None)):
        response = client.post("/api/ic/classify/start", json={"model": "claude_cli"})

    assert response.status_code == 200
    assert response.json()["total"] == 1

    classification_status["running"] = False


def test_e2e_classify_gemini_model(client, seeded_files_for_classify):
    """14.22 Right: gemini_cli 모델 선택 → run_classification에 model=gemini_cli 전달."""
    from app.modules.image_classifier.routers.classify import classification_status

    classification_status["running"] = False

    captured_model = {}

    async def mock_run_classification(files, model, batch_size, gap_minutes, max_workers=1, **kwargs):
        captured_model["model"] = model
        classification_status["running"] = False

    with patch("app.modules.image_classifier.routers.classify.run_classification",
               side_effect=mock_run_classification):
        response = client.post("/api/ic/classify/start", json={
            "model": "gemini_cli",
        })

    assert response.status_code == 200
    assert captured_model.get("model") == "gemini_cli"

    classification_status["running"] = False


def test_e2e_classify_no_categories(client, test_db):
    """14.23 Boundary: 카테고리 없음 → 분류 시작 직후 조기 종료."""
    from PIL import Image
    import tempfile, os
    from app.modules.image_classifier.routers.classify import classification_status
    from sqlalchemy import text

    classification_status["running"] = False

    # 카테고리 없이 파일만
    test_db.execute(text("DELETE FROM categories"))
    test_db.execute(text("DELETE FROM file_classifications"))

    tmpdir = tempfile.mkdtemp()
    img = Image.new("RGB", (50, 50))
    path = os.path.join(tmpdir, "no_cat.jpg")
    img.save(path)
    test_db.execute(text("""
        INSERT INTO file_classifications (file_path, file_hash, status)
        VALUES (:path, 'nochash', 'pending')
    """), {"path": path})
    test_db.commit()

    with patch("app.modules.image_classifier.routers.classify.run_classification",
               new=AsyncMock(return_value=None)):
        response = client.post("/api/ic/classify/start", json={"model": "claude_cli"})

    # 파일은 있으므로 200 시작 (카테고리 없으면 BackgroundTask 내부에서 조기 종료)
    assert response.status_code == 200
    assert response.json()["status"] == "running"

    classification_status["running"] = False
