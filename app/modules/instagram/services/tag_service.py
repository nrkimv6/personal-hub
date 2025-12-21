"""Instagram Tag Service - 태그 및 키워드 관리 서비스."""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.instagram_post_tag import InstagramPostTag, InstagramTagKeyword

logger = logging.getLogger("instagram.tag_service")


class TagService:
    """태그 및 키워드 관리 서비스."""

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    # ============== 태그 CRUD ==============

    def get_tags(self, include_inactive: bool = False) -> list[InstagramPostTag]:
        """태그 목록 조회.

        Args:
            include_inactive: 비활성 태그 포함 여부

        Returns:
            태그 목록
        """
        query = self.db.query(InstagramPostTag)
        if not include_inactive:
            query = query.filter(InstagramPostTag.is_active == True)
        return query.order_by(InstagramPostTag.id).all()

    def get_tag_by_id(self, tag_id: int) -> Optional[InstagramPostTag]:
        """ID로 태그 조회.

        Args:
            tag_id: 태그 ID

        Returns:
            태그 또는 None
        """
        return (
            self.db.query(InstagramPostTag)
            .filter(InstagramPostTag.id == tag_id)
            .first()
        )

    def get_tag_by_name(self, name: str) -> Optional[InstagramPostTag]:
        """이름으로 태그 조회.

        Args:
            name: 태그 이름

        Returns:
            태그 또는 None
        """
        return (
            self.db.query(InstagramPostTag)
            .filter(InstagramPostTag.name == name)
            .first()
        )

    def create_tag(
        self,
        name: str,
        display_name: str,
        description: Optional[str] = None,
        color: str = "#6b7280",
    ) -> InstagramPostTag:
        """태그 생성.

        Args:
            name: 태그 이름 (고유)
            display_name: 표시 이름
            description: 설명
            color: UI 색상 (hex)

        Returns:
            생성된 태그
        """
        tag = InstagramPostTag(
            name=name,
            display_name=display_name,
            description=description,
            color=color,
        )
        self.db.add(tag)
        self.db.commit()
        self.db.refresh(tag)

        logger.info(f"Created tag: {name}")
        return tag

    def update_tag(self, tag_id: int, **kwargs) -> Optional[InstagramPostTag]:
        """태그 수정.

        Args:
            tag_id: 태그 ID
            **kwargs: 수정할 필드들

        Returns:
            수정된 태그 또는 None
        """
        tag = self.get_tag_by_id(tag_id)
        if not tag:
            return None

        for key, value in kwargs.items():
            if hasattr(tag, key) and value is not None:
                setattr(tag, key, value)

        self.db.commit()
        self.db.refresh(tag)

        logger.info(f"Updated tag: {tag.name}")
        return tag

    def delete_tag(self, tag_id: int) -> bool:
        """태그 삭제.

        Args:
            tag_id: 태그 ID

        Returns:
            삭제 성공 여부
        """
        tag = self.get_tag_by_id(tag_id)
        if not tag:
            return False

        tag_name = tag.name
        self.db.delete(tag)
        self.db.commit()

        logger.info(f"Deleted tag: {tag_name}")
        return True

    # ============== 키워드 CRUD ==============

    def get_keywords_by_tag(
        self, tag_id: int, include_inactive: bool = False
    ) -> list[InstagramTagKeyword]:
        """태그의 키워드 목록 조회.

        Args:
            tag_id: 태그 ID
            include_inactive: 비활성 키워드 포함 여부

        Returns:
            키워드 목록
        """
        query = self.db.query(InstagramTagKeyword).filter(
            InstagramTagKeyword.tag_id == tag_id
        )
        if not include_inactive:
            query = query.filter(InstagramTagKeyword.is_active == True)
        return query.order_by(InstagramTagKeyword.id).all()

    def get_keyword_by_id(self, keyword_id: int) -> Optional[InstagramTagKeyword]:
        """ID로 키워드 조회.

        Args:
            keyword_id: 키워드 ID

        Returns:
            키워드 또는 None
        """
        return (
            self.db.query(InstagramTagKeyword)
            .filter(InstagramTagKeyword.id == keyword_id)
            .first()
        )

    def add_keyword(
        self,
        tag_id: int,
        keyword: str,
        is_regex: bool = False,
        is_case_sensitive: bool = False,
    ) -> Optional[InstagramTagKeyword]:
        """키워드 추가.

        Args:
            tag_id: 태그 ID
            keyword: 키워드
            is_regex: 정규식 여부
            is_case_sensitive: 대소문자 구분 여부

        Returns:
            생성된 키워드 또는 None (중복 시)
        """
        # 태그 존재 확인
        tag = self.get_tag_by_id(tag_id)
        if not tag:
            logger.warning(f"Tag not found: {tag_id}")
            return None

        # 중복 확인
        existing = (
            self.db.query(InstagramTagKeyword)
            .filter(
                InstagramTagKeyword.tag_id == tag_id,
                InstagramTagKeyword.keyword == keyword,
            )
            .first()
        )
        if existing:
            logger.debug(f"Keyword already exists: {keyword}")
            return existing

        kw = InstagramTagKeyword(
            tag_id=tag_id,
            keyword=keyword,
            is_regex=is_regex,
            is_case_sensitive=is_case_sensitive,
        )
        self.db.add(kw)
        self.db.commit()
        self.db.refresh(kw)

        logger.info(f"Added keyword '{keyword}' to tag {tag.name}")
        return kw

    def add_keywords_bulk(self, tag_id: int, keywords: list[str]) -> int:
        """여러 키워드 일괄 추가.

        Args:
            tag_id: 태그 ID
            keywords: 키워드 목록

        Returns:
            추가된 키워드 수
        """
        added = 0
        for keyword in keywords:
            keyword = keyword.strip()
            if keyword:
                result = self.add_keyword(tag_id, keyword)
                if result:
                    # 새로 추가된 경우만 카운트
                    existing = (
                        self.db.query(InstagramTagKeyword)
                        .filter(
                            InstagramTagKeyword.tag_id == tag_id,
                            InstagramTagKeyword.keyword == keyword,
                        )
                        .first()
                    )
                    if existing and existing.id == result.id:
                        added += 1

        logger.info(f"Added {added} keywords to tag {tag_id}")
        return added

    def delete_keyword(self, keyword_id: int) -> bool:
        """키워드 삭제.

        Args:
            keyword_id: 키워드 ID

        Returns:
            삭제 성공 여부
        """
        kw = self.get_keyword_by_id(keyword_id)
        if not kw:
            return False

        keyword_text = kw.keyword
        self.db.delete(kw)
        self.db.commit()

        logger.info(f"Deleted keyword: {keyword_text}")
        return True

    def toggle_keyword(self, keyword_id: int) -> Optional[InstagramTagKeyword]:
        """키워드 활성화/비활성화 토글.

        Args:
            keyword_id: 키워드 ID

        Returns:
            수정된 키워드 또는 None
        """
        kw = self.get_keyword_by_id(keyword_id)
        if not kw:
            return None

        kw.is_active = not kw.is_active
        self.db.commit()
        self.db.refresh(kw)

        logger.info(f"Toggled keyword '{kw.keyword}': is_active={kw.is_active}")
        return kw

    def update_keyword(
        self, keyword_id: int, **kwargs
    ) -> Optional[InstagramTagKeyword]:
        """키워드 수정.

        Args:
            keyword_id: 키워드 ID
            **kwargs: 수정할 필드들

        Returns:
            수정된 키워드 또는 None
        """
        kw = self.get_keyword_by_id(keyword_id)
        if not kw:
            return None

        for key, value in kwargs.items():
            if hasattr(kw, key) and value is not None:
                setattr(kw, key, value)

        self.db.commit()
        self.db.refresh(kw)

        logger.info(f"Updated keyword: {kw.keyword}")
        return kw
