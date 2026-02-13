"""헬스 체크 API 엔드포인트 테스트"""
import pytest


# ================================================
# Right: 기본 동작
# ================================================

def test_health_check(client):
    """19.1 Right: GET /health → 모듈 상태 조회"""
    response = client.get("/api/ic/health")

    assert response.status_code == 200
    data = response.json()

    # 기본 필드 확인
    assert data["status"] == "ok"
    assert data["module"] == "image_classifier"
    assert "version" in data
    assert "database" in data
    assert "ai_adapters" in data
    assert "settings" in data


def test_health_check_database_status(client):
    """19.2 Right: health → DB 연결 상태 확인"""
    response = client.get("/api/ic/health")

    assert response.status_code == 200
    data = response.json()

    # DB 상태 확인
    assert data["database"] == "ok"


def test_health_check_ai_adapters(client):
    """19.3 Right: health → AI 어댑터 상태"""
    response = client.get("/api/ic/health")

    assert response.status_code == 200
    data = response.json()

    adapters = data["ai_adapters"]

    # Claude CLI 정보
    assert "claude_cli" in adapters
    assert "available" in adapters["claude_cli"]
    assert "path" in adapters["claude_cli"]

    # Gemini CLI 정보
    assert "gemini_cli" in adapters
    assert "available" in adapters["gemini_cli"]
    assert "path" in adapters["gemini_cli"]

    # AI mode
    assert "mode" in adapters


def test_health_check_settings(client):
    """19.4 Right: health → 설정 정보 포함"""
    response = client.get("/api/ic/health")

    assert response.status_code == 200
    data = response.json()

    settings = data["settings"]

    # 설정 필드 확인
    assert "scan_roots" in settings
    assert "clip_model" in settings
    assert "clip_gpu" in settings
    assert "cluster_gap_minutes" in settings


def test_health_check_multiple_calls(client):
    """19.5 Right: health → 멱등성 (여러 번 호출)"""
    # 헬스 체크는 여러 번 호출해도 항상 동일한 구조 반환
    response1 = client.get("/api/ic/health")
    response2 = client.get("/api/ic/health")

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    # 기본 구조는 동일해야 함
    assert data1["status"] == data2["status"]
    assert data1["module"] == data2["module"]


def test_health_check_performance(client):
    """19.6 Performance: health 응답 시간 확인"""
    import time

    start = time.time()
    response = client.get("/api/ic/health")
    elapsed = time.time() - start

    assert response.status_code == 200

    # 헬스 체크는 빠르게 응답해야 함 (1초 이내)
    assert elapsed < 1.0


def test_health_check_no_params(client):
    """19.7 Boundary: health?param=value → param 무시"""
    # 헬스 체크는 파라미터를 받지 않음
    response = client.get("/api/ic/health?foo=bar")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"


def test_health_check_all_keys_present(client):
    """19.8 Right: health → 모든 필수 키 존재"""
    response = client.get("/api/ic/health")

    assert response.status_code == 200
    data = response.json()

    # 최상위 필수 키
    required_keys = ["status", "module", "version", "database", "ai_adapters", "settings"]
    for key in required_keys:
        assert key in data, f"Missing key: {key}"

    # ai_adapters 하위 키
    assert "claude_cli" in data["ai_adapters"]
    assert "gemini_cli" in data["ai_adapters"]
    assert "mode" in data["ai_adapters"]

    # settings 하위 키
    assert "scan_roots" in data["settings"]
    assert "clip_model" in data["settings"]
