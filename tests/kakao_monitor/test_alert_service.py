"""
KakaoAlertService 단위 테스트
"""
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session


@pytest.fixture
def config_and_post(test_db_session: Session):
    from app.models.kakao_monitor import KakaoWatchConfig, KakaoCollectedPost
    cfg = KakaoWatchConfig(chat_name="알림테스트방", polling_interval_sec=3)
    test_db_session.add(cfg)
    test_db_session.flush()

    post = KakaoCollectedPost(
        config_id=cfg.id,
        matched_keyword="오픈",
        trigger_message="오픈 알림",
        collected_content="게시물 내용",
        status="success",
    )
    test_db_session.add(post)
    test_db_session.commit()
    test_db_session.refresh(post)
    return cfg, post


def test_send_alert_right(test_db_session: Session, config_and_post):
    """R: 알림 발송 → KakaoAlertLog 저장 확인"""
    from app.models.kakao_monitor import KakaoAlertLog
    from app.modules.kakao_monitor.services.alert_service import KakaoAlertService

    _, post = config_and_post

    with patch("app.modules.kakao_monitor.services.alert_service.KakaoAlertService._publish_redis"):
        svc = KakaoAlertService(test_db_session)
        log = svc.send_alert(post, alert_type="sse")

    assert log.id is not None
    db_log = test_db_session.get(KakaoAlertLog, log.id)
    assert db_log is not None
    assert db_log.post_id == post.id


def test_send_alert_log_fields(test_db_session: Session, config_and_post):
    """Co: alert_type, sent_at, result 필드 정확성"""
    from app.modules.kakao_monitor.services.alert_service import KakaoAlertService

    _, post = config_and_post

    with patch("app.modules.kakao_monitor.services.alert_service.KakaoAlertService._publish_redis"):
        svc = KakaoAlertService(test_db_session)
        before = datetime.now()
        log = svc.send_alert(post, alert_type="sse")
        after = datetime.now()

    assert log.alert_type == "sse"
    assert log.sent_at is not None
    assert before <= log.sent_at <= after
    assert log.result == "ok"


def test_publish_redis_uses_shared_sync_client(test_db_session: Session, config_and_post):
    """Re: app.shared.redis.get_redis_client_sync 경로로 publish 호출."""
    from app.modules.kakao_monitor.services.alert_service import KakaoAlertService

    _, post = config_and_post
    mock_sync_client = MagicMock()

    with patch("app.shared.redis.get_redis_client_sync", return_value=mock_sync_client):
        svc = KakaoAlertService(test_db_session)
        svc._publish_redis(post, alert_type="sse", action_type="alert_only")

    mock_sync_client.publish.assert_called_once()
    payload = mock_sync_client.publish.call_args.args[1]
    assert "\"action_type\": \"alert_only\"" in payload
