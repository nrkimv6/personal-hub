"""
카카오 모니터 HTTP 통합 테스트 (T5)
"""
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

_WIN32_MOCKS = {
    "psutil": MagicMock(), "win32gui": MagicMock(), "win32con": MagicMock(),
    "win32clipboard": MagicMock(), "pyautogui": MagicMock(),
    "paddleocr": MagicMock(), "imagehash": MagicMock(), "win32ui": MagicMock(),
}


@pytest.fixture(scope="module")
def client(test_db_engine):
    with patch.dict(sys.modules, _WIN32_MOCKS):
        from app.database import get_db
        from app.modules.kakao_monitor.routes import router

    test_app = FastAPI()

    def _override():
        from sqlalchemy.orm import sessionmaker
        S = sessionmaker(bind=test_db_engine)
        db = S()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = _override
    test_app.include_router(router)
    return TestClient(test_app)


@pytest.fixture(autouse=True)
def clean(test_db_session: Session):
    from app.models.kakao_monitor import KakaoCollectedPost, KakaoKeyword, KakaoWatchConfig
    test_db_session.query(KakaoCollectedPost).delete()
    test_db_session.query(KakaoKeyword).delete()
    test_db_session.query(KakaoWatchConfig).delete()
    test_db_session.commit()


def test_post_configs_201(client):
    """POST /configs — 201 + 생성된 config 반환"""
    res = client.post("/api/v1/kakao-monitor/configs", json={"chat_name": "HTTP테스트방"})
    assert res.status_code == 201
    assert res.json()["chat_name"] == "HTTP테스트방"
    assert res.json()["id"] > 0


def test_post_configs_empty_name_422(client):
    """POST /configs (빈 chat_name) — 422"""
    res = client.post("/api/v1/kakao-monitor/configs", json={})
    assert res.status_code == 422


def test_get_configs_200(client):
    """GET /configs — 200 + 목록"""
    res = client.get("/api/v1/kakao-monitor/configs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_put_config_200(client):
    """PUT /configs/{id} — 200 + 수정 반영"""
    cfg_id = client.post("/api/v1/kakao-monitor/configs",
                          json={"chat_name": "수정전"}).json()["id"]
    res = client.put(f"/api/v1/kakao-monitor/configs/{cfg_id}",
                     json={"chat_name": "수정후"})
    assert res.status_code == 200
    assert res.json()["chat_name"] == "수정후"


def test_put_config_404(client):
    """PUT /configs/999 (미존재) — 404"""
    res = client.put("/api/v1/kakao-monitor/configs/999", json={"chat_name": "x"})
    assert res.status_code == 404


def test_delete_config_204(client):
    """DELETE /configs/{id} — 204"""
    cfg_id = client.post("/api/v1/kakao-monitor/configs",
                          json={"chat_name": "삭제방"}).json()["id"]
    res = client.delete(f"/api/v1/kakao-monitor/configs/{cfg_id}")
    assert res.status_code == 204


def test_patch_toggle_200(client):
    """PATCH /configs/{id}/toggle — 200 + is_active 반전"""
    cfg_id = client.post("/api/v1/kakao-monitor/configs",
                          json={"chat_name": "토글방"}).json()["id"]
    before = client.get("/api/v1/kakao-monitor/configs").json()
    is_active_before = next(c["is_active"] for c in before if c["id"] == cfg_id)

    res = client.patch(f"/api/v1/kakao-monitor/configs/{cfg_id}/toggle")
    assert res.status_code == 200
    assert res.json()["is_active"] is not is_active_before


def test_post_keyword_201(client):
    """POST /configs/{id}/keywords — 201 + 키워드 반환"""
    cfg_id = client.post("/api/v1/kakao-monitor/configs",
                          json={"chat_name": "키워드방"}).json()["id"]
    res = client.post(f"/api/v1/kakao-monitor/configs/{cfg_id}/keywords",
                      json={"keyword": "공지", "action_type": "collect"})
    assert res.status_code == 201
    assert res.json()["keyword"] == "공지"


def test_get_keywords_200(client):
    """GET /configs/{id}/keywords — 200 + 목록"""
    cfg_id = client.post("/api/v1/kakao-monitor/configs",
                          json={"chat_name": "키워드목록방"}).json()["id"]
    client.post(f"/api/v1/kakao-monitor/configs/{cfg_id}/keywords",
                json={"keyword": "테스트"})
    res = client.get(f"/api/v1/kakao-monitor/configs/{cfg_id}/keywords")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_delete_keyword_204(client):
    """DELETE /keywords/{id} — 204"""
    cfg_id = client.post("/api/v1/kakao-monitor/configs",
                          json={"chat_name": "키워드삭제방"}).json()["id"]
    kw_id = client.post(f"/api/v1/kakao-monitor/configs/{cfg_id}/keywords",
                         json={"keyword": "삭제키워드"}).json()["id"]
    res = client.delete(f"/api/v1/kakao-monitor/keywords/{kw_id}")
    assert res.status_code == 204


def test_get_posts_200(client, test_db_session):
    """GET /posts — 200 + 페이지네이션"""
    from app.models.kakao_monitor import KakaoWatchConfig, KakaoCollectedPost
    cfg = KakaoWatchConfig(chat_name="이력방")
    test_db_session.add(cfg)
    test_db_session.flush()
    for i in range(3):
        test_db_session.add(KakaoCollectedPost(
            config_id=cfg.id, matched_keyword=f"k{i}",
            trigger_message="t", collected_content="c", status="success"
        ))
    test_db_session.commit()

    res = client.get(f"/api/v1/kakao-monitor/posts?config_id={cfg.id}&limit=2")
    assert res.status_code == 200
    assert len(res.json()["items"]) == 2
    assert res.json()["total"] >= 3


def test_get_post_detail_200(client, test_db_session):
    """GET /posts/{id} — 200 + collected_content 포함"""
    from app.models.kakao_monitor import KakaoWatchConfig, KakaoCollectedPost
    cfg = KakaoWatchConfig(chat_name="상세방")
    test_db_session.add(cfg)
    test_db_session.flush()
    post = KakaoCollectedPost(config_id=cfg.id, matched_keyword="k",
                               trigger_message="t", collected_content="상세내용", status="success")
    test_db_session.add(post)
    test_db_session.commit()

    res = client.get(f"/api/v1/kakao-monitor/posts/{post.id}")
    assert res.status_code == 200
    assert res.json()["collected_content"] == "상세내용"


def test_get_post_not_found_404(client):
    """GET /posts/999 (미존재) — 404"""
    res = client.get("/api/v1/kakao-monitor/posts/999")
    assert res.status_code == 404


def test_delete_post_204(client, test_db_session):
    """DELETE /posts/{id} — 204"""
    from app.models.kakao_monitor import KakaoWatchConfig, KakaoCollectedPost
    cfg = KakaoWatchConfig(chat_name="삭제이력방")
    test_db_session.add(cfg)
    test_db_session.flush()
    post = KakaoCollectedPost(config_id=cfg.id, matched_keyword="k",
                               trigger_message="t", collected_content="c", status="success")
    test_db_session.add(post)
    test_db_session.commit()

    res = client.delete(f"/api/v1/kakao-monitor/posts/{post.id}")
    assert res.status_code == 204


def test_get_status_200(client):
    """GET /status — 200 + 필수 필드 포함"""
    with patch.dict(sys.modules, _WIN32_MOCKS):
        res = client.get("/api/v1/kakao-monitor/status")
    assert res.status_code == 200
    data = res.json()
    assert "is_kakao_running" in data
    assert "main_window_found" in data
    assert "active_config_count" in data


def test_get_windows_200(client):
    """GET /windows — 200 + 빈 리스트도 OK"""
    with patch.dict(sys.modules, _WIN32_MOCKS):
        # win32gui.EnumWindows를 빈 결과로
        _WIN32_MOCKS["win32gui"].EnumWindows = MagicMock()
        res = client.get("/api/v1/kakao-monitor/windows")
    assert res.status_code in (200, 503)  # win32gui 미설치 환경에서는 503 가능


def test_post_scan_200(client):
    """POST /scan — 200 또는 202"""
    with patch("app.modules.kakao_monitor.routes.worker_routes.get_redis_client",
               return_value=None):
        res = client.post("/api/v1/kakao-monitor/scan")
    assert res.status_code == 200
    assert "queued" in res.json()
