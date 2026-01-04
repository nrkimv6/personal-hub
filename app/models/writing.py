"""Writing SQLAlchemy Models - 글쓰기 소스 및 생성된 글."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from .base import Base


class WritingSource(Base):
    """글쓰기 소스 (원본 글)."""

    __tablename__ = "writing_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)  # 글 본문
    category = Column(String(50), nullable=True)  # 분류 (선택)
    source_info = Column(String(200), nullable=True)  # 출처 정보

    # RSS/API 수집용 필드 (077 마이그레이션)
    source_url = Column(String(500), nullable=True)  # 원본 URL
    source_type = Column(String(50), default="manual")  # 'rss', 'api', 'manual'
    content_hash = Column(String(64), nullable=True)  # 중복 체크용 SHA256

    created_at = Column(DateTime, default=datetime.now)

    # 소재 추출
    topic_extracted_at = Column(DateTime, nullable=True)  # 소재 추출 완료 시각

    # 상수
    SOURCE_TYPE_RSS = "rss"
    SOURCE_TYPE_API = "api"
    SOURCE_TYPE_MANUAL = "manual"

    def __repr__(self):
        return f"<WritingSource(id={self.id}, category={self.category})>"


class WritingRssFeed(Base):
    """RSS 피드 관리."""

    __tablename__ = "writing_rss_feeds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # 피드 이름
    url = Column(String(500), nullable=False, unique=True)  # RSS URL
    source_type = Column(String(50), nullable=False, default="tistory")  # 플랫폼 유형
    enabled = Column(Integer, nullable=False, default=1)  # 활성화 여부
    last_fetched_at = Column(DateTime, nullable=True)  # 마지막 수집 시간
    fetch_count = Column(Integer, nullable=False, default=0)  # 총 수집 횟수
    error_count = Column(Integer, nullable=False, default=0)  # 에러 횟수
    last_error = Column(Text, nullable=True)  # 마지막 에러 메시지
    created_at = Column(DateTime, default=datetime.now)

    # 상수
    SOURCE_TYPE_TISTORY = "tistory"
    SOURCE_TYPE_NAVER_BLOG = "naver_blog"
    SOURCE_TYPE_MEDIUM = "medium"
    SOURCE_TYPE_OTHER = "other"

    def __repr__(self):
        return f"<WritingRssFeed(id={self.id}, name={self.name})>"


class WritingSearchQuery(Base):
    """검색 쿼리 관리."""

    __tablename__ = "writing_search_queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(200), nullable=False)  # 검색어
    source_type = Column(String(50), nullable=False, default="naver")  # 검색 엔진
    search_target = Column(String(50), nullable=False, default="blog")  # 검색 대상
    enabled = Column(Integer, nullable=False, default=1)  # 활성화 여부
    priority = Column(Integer, nullable=False, default=0)  # 우선순위
    last_searched_at = Column(DateTime, nullable=True)  # 마지막 검색 시간
    result_count = Column(Integer, nullable=False, default=0)  # 누적 결과 수
    success_count = Column(Integer, nullable=False, default=0)  # 성공 횟수
    error_count = Column(Integer, nullable=False, default=0)  # 실패 횟수
    last_error = Column(Text, nullable=True)  # 마지막 에러
    created_at = Column(DateTime, default=datetime.now)

    # 검색 엔진 상수
    SOURCE_TYPE_NAVER = "naver"
    SOURCE_TYPE_KAKAO = "kakao"
    SOURCE_TYPE_GOOGLE = "google"

    # 검색 대상 상수
    TARGET_BLOG = "blog"
    TARGET_CAFE = "cafe"
    TARGET_NEWS = "news"

    def __repr__(self):
        return f"<WritingSearchQuery(id={self.id}, query={self.query})>"


class GeneratedWriting(Base):
    """생성된 글."""

    __tablename__ = "generated_writings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 생성 정보
    task_type = Column(String(20), nullable=False)  # 'mix' or 'random'
    prompt_used = Column(Text, nullable=True)  # 사용된 프롬프트
    source_ids = Column(String(100), nullable=True)  # 사용된 소스 ID들 (예: "1,5,23")

    # 결과
    content = Column(Text, nullable=False)  # 생성된 글
    raw_response = Column(Text, nullable=True)  # LLM 전체 응답
    selected_elements = Column(Text, nullable=True)  # 선택된 요소 JSON

    # 평가
    rating = Column(Integer, nullable=True)  # 1: 추천, -1: 비추천, NULL: 미평가

    # 메타
    schedule_run_id = Column(
        Integer, ForeignKey("task_schedule_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    deleted_at = Column(DateTime, nullable=True, index=True)  # soft delete

    # 상수
    TASK_TYPE_MIX = "mix"  # 3개 글 믹스
    TASK_TYPE_RANDOM = "random"  # 랜덤 프롬프트 (소재+키워드)
    TASK_TYPE_KEYWORD = "keyword"  # 키워드 전용 (소재 없음)

    RATING_LIKE = 1
    RATING_DISLIKE = -1

    def __repr__(self):
        return f"<GeneratedWriting(id={self.id}, task_type={self.task_type})>"

    def get_source_id_list(self) -> list[int]:
        """source_ids를 int 리스트로 반환."""
        if not self.source_ids:
            return []
        return [int(x) for x in self.source_ids.split(",") if x]
