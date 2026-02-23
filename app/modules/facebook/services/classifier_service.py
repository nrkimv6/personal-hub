"""Facebook Post Classifier Service - 게시물 분류 서비스.

Instagram 분류 서비스와 동일한 패턴으로 구현.
Facebook 게시물을 키워드 매칭 방식으로 분류합니다.
"""

import logging
import re
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.facebook_post import FacebookPost

logger = logging.getLogger("facebook.classifier")


class ClassifierService:
    """Facebook 게시물 분류 서비스.

    규칙 기반(키워드 매칭)으로 게시물을 분류합니다.
    현재는 기본 구조만 구현되어 있으며,
    Instagram 분류 서비스와 동일한 방식으로 확장 가능합니다.
    """

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    def classify_post(self, post: FacebookPost) -> Optional[str]:
        """게시물을 분류합니다.

        Args:
            post: 분류할 FacebookPost 인스턴스

        Returns:
            분류 결과 ('event' | 'popup' | 'uncategorized' | None)
        """
        caption = (post.caption or "").lower()

        if not caption:
            return "uncategorized"

        # 이벤트 키워드
        event_keywords = ["이벤트", "event", "행사", "공연", "콘서트", "전시", "축제"]
        for kw in event_keywords:
            if kw in caption:
                return "event"

        # 팝업 키워드
        popup_keywords = ["팝업", "popup", "pop-up", "팝업스토어"]
        for kw in popup_keywords:
            if kw in caption:
                return "popup"

        return "uncategorized"

    def classify_and_save(self, post: FacebookPost) -> Optional[str]:
        """게시물을 분류하고 결과를 DB에 저장합니다.

        Args:
            post: 분류할 FacebookPost 인스턴스

        Returns:
            분류 결과 타입
        """
        result = self.classify_post(post)

        if result:
            post.classified_type = result
            post.classified_at = datetime.now()
            try:
                self.db.commit()
                logger.debug(f"게시물 분류 완료: post_id={post.post_id}, type={result}")
            except Exception as e:
                self.db.rollback()
                logger.error(f"분류 결과 저장 실패: {e}")

        return result

    def classify_unclassified_posts(self, limit: int = 50) -> int:
        """미분류 게시물을 일괄 분류합니다.

        Args:
            limit: 처리할 최대 게시물 수

        Returns:
            분류 완료된 게시물 수
        """
        posts = (
            self.db.query(FacebookPost)
            .filter(
                FacebookPost.classified_type.is_(None),
                FacebookPost.is_active == True,
            )
            .limit(limit)
            .all()
        )

        count = 0
        for post in posts:
            result = self.classify_and_save(post)
            if result:
                count += 1

        logger.info(f"일괄 분류 완료: {count}/{len(posts)}개")
        return count
