"""Instagram Post Classifier Service - 게시물 분류 서비스."""

import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models import InstagramPost
from app.models.instagram_post_tag import (
    InstagramPostTag,
    InstagramTagKeyword,
    InstagramPostTagRelation,
)

logger = logging.getLogger("instagram.classifier")


class ClassifierService:
    """게시물 분류 서비스.

    규칙 기반(키워드 매칭)으로 게시물을 분류합니다.
    """

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db
        self._keyword_cache: dict[int, list[InstagramTagKeyword]] = {}

    def _load_keywords(self, tag_id: int) -> list[InstagramTagKeyword]:
        """태그별 키워드 로드 (캐시 활용).

        Args:
            tag_id: 태그 ID

        Returns:
            활성화된 키워드 목록
        """
        if tag_id not in self._keyword_cache:
            keywords = (
                self.db.query(InstagramTagKeyword)
                .filter(
                    InstagramTagKeyword.tag_id == tag_id,
                    InstagramTagKeyword.is_active == True,
                )
                .all()
            )
            self._keyword_cache[tag_id] = keywords
        return self._keyword_cache[tag_id]

    def _get_active_tags(self) -> list[InstagramPostTag]:
        """활성화된 태그 목록 조회.

        Returns:
            활성화된 태그 목록
        """
        return (
            self.db.query(InstagramPostTag)
            .filter(InstagramPostTag.is_active == True)
            .all()
        )

    def _match_keywords(
        self, text: str, keywords: list[InstagramTagKeyword]
    ) -> list[str]:
        """텍스트에서 키워드 매칭.

        Args:
            text: 검색할 텍스트
            keywords: 키워드 목록

        Returns:
            매칭된 키워드 목록
        """
        if not text:
            return []

        matched = []
        text_lower = text.lower()

        for kw in keywords:
            keyword = kw.keyword

            if kw.is_regex:
                # 정규식 매칭
                flags = 0 if kw.is_case_sensitive else re.IGNORECASE
                try:
                    if re.search(keyword, text, flags):
                        matched.append(keyword)
                except re.error:
                    logger.warning(f"Invalid regex pattern: {keyword}")
            else:
                # 일반 키워드 매칭
                compare_text = text if kw.is_case_sensitive else text_lower
                compare_keyword = keyword if kw.is_case_sensitive else keyword.lower()
                if compare_keyword in compare_text:
                    matched.append(keyword)

        return matched

    def classify_post(self, post: InstagramPost) -> list[dict]:
        """게시물을 분류하고 태그 관계를 저장.

        Args:
            post: 분류할 게시물

        Returns:
            분류 결과 목록: [{"tag": "event", "display_name": "이벤트", "keywords": ["이벤트", "추첨"]}]
        """
        if not post.caption:
            return []

        results = []
        tags = self._get_active_tags()

        for tag in tags:
            keywords = self._load_keywords(tag.id)
            matched = self._match_keywords(post.caption, keywords)

            if matched:
                # 기존 관계 확인
                existing = (
                    self.db.query(InstagramPostTagRelation)
                    .filter(
                        InstagramPostTagRelation.post_id == post.id,
                        InstagramPostTagRelation.tag_id == tag.id,
                    )
                    .first()
                )

                if existing:
                    # 업데이트
                    existing.matched_keywords = json.dumps(matched, ensure_ascii=False)
                else:
                    # 새로 생성
                    relation = InstagramPostTagRelation(
                        post_id=post.id,
                        tag_id=tag.id,
                        matched_keywords=json.dumps(matched, ensure_ascii=False),
                        confidence=1.0,
                    )
                    self.db.add(relation)

                results.append(
                    {
                        "tag": tag.name,
                        "display_name": tag.display_name,
                        "keywords": matched,
                    }
                )

        self.db.commit()

        # LLM 분류 트리거 확인
        if results:
            self._trigger_llm_classification_if_needed(post.id, [r["tag"] for r in results])

        return results

    def classify_posts_batch(self, post_ids: list[int]) -> dict:
        """여러 게시물 일괄 분류.

        Args:
            post_ids: 분류할 게시물 ID 목록

        Returns:
            분류 결과: {"total": 10, "classified": 5, "details": [...]}
        """
        posts = (
            self.db.query(InstagramPost).filter(InstagramPost.id.in_(post_ids)).all()
        )

        results = {"total": len(posts), "classified": 0, "details": []}

        for post in posts:
            post_result = self.classify_post(post)
            if post_result:
                results["classified"] += 1
                results["details"].append({"post_id": post.id, "tags": post_result})

        return results

    def reclassify_all(self) -> dict:
        """전체 게시물 재분류.

        기존 분류 결과를 삭제하고 전체 게시물을 재분류합니다.

        Returns:
            분류 결과: {"total": 100, "classified": 30, "details": [...]}
        """
        # 기존 분류 결과 삭제
        self.db.query(InstagramPostTagRelation).delete()
        self.db.commit()

        # 캐시 초기화
        self.clear_cache()

        # 전체 게시물 조회
        posts = self.db.query(InstagramPost).all()
        post_ids = [p.id for p in posts]

        return self.classify_posts_batch(post_ids)

    def clear_cache(self):
        """캐시 초기화 (키워드 변경 시 호출)."""
        self._keyword_cache.clear()

    def _trigger_llm_classification_if_needed(self, post_id: int, matched_tags: list[str]) -> None:
        """LLM 분류가 필요하면 큐에 추가.

        Args:
            post_id: 게시물 ID
            matched_tags: 매칭된 태그 이름 목록
        """
        from app.modules.instagram.services.llm_classifier_service import LLMClassifierService
        from app.models.task_schedule import TaskSchedule

        llm_service = LLMClassifierService(self.db)
        if llm_service.should_trigger_llm(matched_tags):
            trigger_tag = llm_service.get_trigger_tag(matched_tags)
            if trigger_tag:
                # instagram_feed 스케줄에서 LLM provider/model 설정 읽기
                schedule = (
                    self.db.query(TaskSchedule)
                    .filter_by(target_type="instagram_feed", enabled=True)
                    .first()
                )
                provider = "claude"
                model = ""
                if schedule:
                    config = schedule.get_target_config()
                    provider = config.get("llm_provider", "claude")
                    model = config.get("llm_model", "")

                llm_service.create_request(post_id, trigger_tag, provider=provider, model=model)
                logger.info(f"LLM classification queued for post {post_id} (trigger: {trigger_tag}, provider: {provider})")

    def get_post_tags(self, post_id: int) -> list[dict]:
        """게시물의 태그 목록 조회.

        Args:
            post_id: 게시물 ID

        Returns:
            태그 정보 목록
        """
        relations = (
            self.db.query(InstagramPostTagRelation)
            .filter(InstagramPostTagRelation.post_id == post_id)
            .all()
        )

        return [
            {
                "tag": rel.tag.name,
                "display_name": rel.tag.display_name,
                "color": rel.tag.color,
                "matched_keywords": (
                    json.loads(rel.matched_keywords) if rel.matched_keywords else []
                ),
                "confidence": rel.confidence,
            }
            for rel in relations
            if rel.tag
        ]
