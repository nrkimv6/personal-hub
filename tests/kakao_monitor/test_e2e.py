"""
카카오 모니터 E2E 테스트 (T4) — TestClient 기반
"""
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Windows 전용 모듈 mock
_WIN32_MOCKS = {
    "psutil": MagicMock(), "win32gui": MagicMock(), "win32con": MagicMock(),
    "win32clipboard": MagicMock(), "pyautogui": MagicMock(),
    "paddleocr": MagicMock(), "imagehash": MagicMock(), "win32ui": MagicMock(),
}


@pytest.fixture(scope="module")
def app_client(test_db_engine):
    """TestClient with kakao-monitor routes."""
    with patch.dict(sys.modules, _WIN32_MOCKS):
        from app.database import get_db, Base
        from app.modules.kakao_monitor.routes import router

    test_app = FastAPI()

    def _override_db():
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=test_db_engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = _override_db
    test_app.include_router(router)
    return TestClient(test_app)


@pytest.fixture(autouse=True)
def clean_db(test_db_session: Session):
    """각 테스트 전 kakao 테이블 초기화."""
    from app.models.kakao_monitor import KakaoCollectedPost, KakaoKeyword, KakaoWatchConfig
    test_db_session.query(KakaoCollectedPost).delete()
    test_db_session.query(KakaoKeyword).delete()
    test_db_session.query(KakaoWatchConfig).delete()
    test_db_session.commit()


def test_config_crud_e2e(app_client):
    """T4: 설정 생성→조회→수정→toggle→삭제 전체 흐름."""
    # 생성
    res = app_client.post("/api/v1/kakao-monitor/configs", json={
        "chat_name": "E2E 채팅방", "polling_interval_sec": 5, "keywords": ["예약"]
    })
    assert res.status_code == 201
    config_id = res.json()["id"]
    assert res.json()["keyword_count"] == 1

    # 조회
    res = app_client.get("/api/v1/kakao-monitor/configs")
    assert res.status_code == 200
    assert any(c["id"] == config_id for c in res.json())

    # 수정
    res = app_client.put(f"/api/v1/kakao-monitor/configs/{config_id}", json={
        "chat_name": "수정된방", "polling_interval_sec": 10
    })
    assert res.status_code == 200
    assert res.json()["chat_name"] == "수정된방"

    # Toggle
    is_active_before = res.json()["is_active"]
    res = app_client.patch(f"/api/v1/kakao-monitor/configs/{config_id}/toggle")
    assert res.status_code == 200
    assert res.json()["is_active"] is not is_active_before

    # 삭제
    res = app_client.delete(f"/api/v1/kakao-monitor/configs/{config_id}")
    assert res.status_code == 204

    # 삭제 확인
    res = app_client.get("/api/v1/kakao-monitor/configs")
    assert not any(c["id"] == config_id for c in res.json())


def test_keyword_crud_e2e(app_client):
    """T4: 키워드 추가→목록조회→삭제 전체 흐름."""
    res = app_client.post("/api/v1/kakao-monitor/configs", json={"chat_name": "키워드테스트"})
    config_id = res.json()["id"]

    # 키워드 추가
    res = app_client.post(f"/api/v1/kakao-monitor/configs/{config_id}/keywords",
                           json={"keyword": "오픈", "action_type": "collect"})
    assert res.status_code == 201
    kw_id = res.json()["id"]

    # 목록 조회
    res = app_client.get(f"/api/v1/kakao-monitor/configs/{config_id}/keywords")
    assert res.status_code == 200
    assert any(k["id"] == kw_id for k in res.json())

    # 삭제
    res = app_client.delete(f"/api/v1/kakao-monitor/keywords/{kw_id}")
    assert res.status_code == 204


def test_posts_query_e2e(app_client, test_db_session: Session):
    """T4: post 미리 삽입 → 목록조회(필터+페이지네이션)→상세조회→삭제."""
    from app.models.kakao_monitor import KakaoWatchConfig, KakaoCollectedPost

    cfg = KakaoWatchConfig(chat_name="이력조회방")
    test_db_session.add(cfg)
    test_db_session.flush()

    for i in range(5):
        test_db_session.add(KakaoCollectedPost(
            config_id=cfg.id,
            matched_keyword=f"kw{i}",
            trigger_message="트리거",
            collected_content=f"내용{i}",
            status="success",
        ))
    test_db_session.commit()

    # 목록 조회 (limit=3)
    res = app_client.get(f"/api/v1/kakao-monitor/posts?config_id={cfg.id}&limit=3")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 3
    assert data["total"] >= 5

    post_id = data["items"][0]["id"]

    # 상세 조회
    res = app_client.get(f"/api/v1/kakao-monitor/posts/{post_id}")
    assert res.status_code == 200
    assert "collected_content" in res.json()

    # 삭제
    res = app_client.delete(f"/api/v1/kakao-monitor/posts/{post_id}")
    assert res.status_code == 204


def test_config_delete_cascades_keywords_and_posts(app_client, test_db_session: Session):
    """T4: config 삭제 시 관련 keyword, post 전부 삭제 확인."""
    from app.models.kakao_monitor import KakaoWatchConfig, KakaoKeyword, KakaoCollectedPost

    cfg = KakaoWatchConfig(chat_name="cascade방")
    test_db_session.add(cfg)
    test_db_session.flush()

    kw = KakaoKeyword(config_id=cfg.id, keyword="삭제테스트")
    test_db_session.add(kw)
    test_db_session.flush()

    post = KakaoCollectedPost(config_id=cfg.id, matched_keyword="삭제테스트",
                               trigger_message="t", collected_content="c", status="success")
    test_db_session.add(post)
    test_db_session.commit()
    kw_id, post_id = kw.id, post.id
    config_id = cfg.id

    res = app_client.delete(f"/api/v1/kakao-monitor/configs/{config_id}")
    assert res.status_code == 204

    # HTTP DELETE 후 세션 캐시 만료 → DB에서 재조회
    test_db_session.expire_all()
    assert test_db_session.get(KakaoKeyword, kw_id) is None
    assert test_db_session.get(KakaoCollectedPost, post_id) is None


def test_status_idle_message_when_no_active_config(app_client):
    """T4: active config 0건일 때 status_message 계약 확인."""
    res = app_client.get("/api/v1/kakao-monitor/status")
    assert res.status_code == 200
    data = res.json()
    assert data["active_config_count"] == 0
    assert data["status_message"] in {"idle(no active config)", "kakao process not running"}
