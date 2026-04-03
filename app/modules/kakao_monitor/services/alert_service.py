"""
카카오 모니터 알림 서비스 — 수집 완료 시 SSE 채널 발행 + DB 저장.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.models.kakao_monitor import KakaoCollectedPost, KakaoAlertLog, KakaoKeyword

logger = logging.getLogger(__name__)

# Redis pub/sub 알림 채널
KAKAO_ALERT_CHANNEL = "kakao:alerts"


class KakaoAlertService:
    """수집 완료 알림 발행 + 이력 저장."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def send_alert(
        self,
        post: KakaoCollectedPost,
        alert_type: str = "sse",
        action_type: str = KakaoKeyword.ACTION_TYPE_COLLECT,
    ) -> KakaoAlertLog:
        """알림 발행 (Redis pub/sub) + DB 이력 저장.

        Args:
            post: 수집된 게시물
            alert_type: 알림 유형 (기본 "sse")

        Returns:
            저장된 KakaoAlertLog
        """
        result_msg = "ok"
        try:
            self._publish_redis(post, alert_type, action_type=action_type)
        except Exception as exc:
            logger.warning("Redis 알림 발행 실패: %s", exc)
            result_msg = f"redis_error: {exc}"

        log = KakaoAlertLog(
            post_id=post.id,
            alert_type=alert_type,
            result=result_msg,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def _publish_redis(
        self,
        post: KakaoCollectedPost,
        alert_type: str,
        action_type: str = KakaoKeyword.ACTION_TYPE_COLLECT,
    ) -> None:
        """Redis pub/sub 채널에 알림 발행."""
        from app.shared.redis import get_redis_client_sync

        normalized_action = (action_type or "").strip().lower()
        if normalized_action not in KakaoKeyword.VALID_ACTION_TYPES:
            normalized_action = KakaoKeyword.ACTION_TYPE_COLLECT

        redis_client = get_redis_client_sync()
        if redis_client is None:
            logger.debug("Redis 동기 클라이언트 없음 — 알림 스킵")
            return

        payload = json.dumps(
            {
                "type": "kakao_alert",
                "alert_type": alert_type,
                "action_type": normalized_action,
                "post_id": post.id,
                "config_id": post.config_id,
                "matched_keyword": post.matched_keyword,
                "trigger_message": post.trigger_message,
                "content_preview": (post.collected_content or "")[:100],
            },
            ensure_ascii=False,
        )
        redis_client.publish(KAKAO_ALERT_CHANNEL, payload)
        logger.debug("알림 발행 완료: post_id=%d action=%s", post.id, normalized_action)
