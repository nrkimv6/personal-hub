"""
수집 결과 저장 서비스.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.kakao_monitor import KakaoCollectedPost

logger = logging.getLogger(__name__)

_SCREENSHOT_DIR = Path("data/kakao_screenshots")


class KakaoCollectService:
    """수집된 게시물 DB 저장 & 조회."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save_collected_post(
        self,
        config_id: int,
        keyword_id: int | None,
        matched_keyword: str,
        trigger_msg: str,
        content: str,
        screenshot_path: str | None = None,
        status: str = KakaoCollectedPost.STATUS_SUCCESS,
    ) -> KakaoCollectedPost:
        """수집 게시물 저장 후 반환."""
        normalized_status = (status or "").strip().lower()
        if normalized_status not in KakaoCollectedPost.VALID_STATUSES:
            logger.warning(
                "알 수 없는 status=%r - failed로 대체 저장",
                status,
            )
            normalized_status = KakaoCollectedPost.STATUS_FAILED

        post = KakaoCollectedPost(
            config_id=config_id,
            keyword_id=keyword_id,
            matched_keyword=matched_keyword,
            trigger_message=trigger_msg,
            collected_content=content,
            screenshot_path=screenshot_path,
            status=normalized_status,
        )
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)
        logger.info("수집 게시물 저장: id=%d, keyword=%r", post.id, matched_keyword)
        return post

    def get_collected_posts(
        self,
        config_id: int | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[KakaoCollectedPost], int]:
        """수집 이력 페이지네이션 조회.

        Returns:
            (items, total_count)
        """
        q = self.db.query(KakaoCollectedPost)
        if config_id is not None:
            q = q.filter(KakaoCollectedPost.config_id == config_id)
        total = q.count()
        items = (
            q.order_by(KakaoCollectedPost.collected_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    def save_screenshot(self, image: object, config_id: int) -> str:
        """스크린샷 저장 후 경로 반환.

        Args:
            image: PIL.Image
            config_id: 감시 설정 ID

        Returns:
            저장된 파일 경로 (str)
        """
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{config_id}_{ts}.png"
        path = _SCREENSHOT_DIR / filename
        try:
            image.save(str(path))  # type: ignore[union-attr]
            logger.debug("스크린샷 저장: %s", path)
        except Exception as exc:
            logger.exception("스크린샷 저장 실패: %s", exc)
        return str(path)
