"""Instagram LLM Classifier Service - LLM 기반 이벤트 분류 서비스.

claude_worker 모듈을 사용하여 LLM 분류를 수행합니다.
Instagram 전용 로직(트리거 태그, 프롬프트)만 포함합니다.
"""

import hashlib
import json
import logging
import os
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import InstagramPost
from app.modules.claude_worker.services.llm_service import LLMService

logger = logging.getLogger("instagram.llm_classifier")

# 이미지 캐시 디렉토리
IMAGE_CACHE_DIR = Path("data/llm_images")
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# LLM 분류를 트리거하는 태그 목록
LLM_TRIGGER_TAGS = ["event"]

# 프롬프트 템플릿
CLASSIFICATION_PROMPT = """다음 Instagram 게시물을 분석하여 정보를 추출해주세요.

**오늘 날짜: {today}**
**게시물 작성일: {posted_at}**

## 게시물 내용
{caption}
{image_section}
## 이벤트가 아닌 것 (중요!)
다음은 "이벤트"가 아니므로 tag를 "기타"로 분류하세요:
- **협찬/광고 게시물**: 제품/서비스를 협찬받아 작성한 광고성 게시물 (예: "협찬", "광고", "유료광고포함")
- **후기 이벤트**: 구매 후기 작성 시 추첨하는 이벤트 (예: "구매 후기 남기면 추첨")
- **당첨자 발표 게시물**: 이벤트 결과 발표, 당첨자 명단 공개 게시물 (예: "당첨자 발표", "당첨 축하", "이벤트 결과")

## 리그램 분류 (중요!)
다른 계정의 게시물을 재공유한 경우 tag를 "리그램"으로 분류하세요:
- **리그램 표시**: 본문에 "repost", "리포스트", "regram", "리그램", "rp @", "📷 @" 등 재공유 표시가 있는 경우
- **리그램은 배타적**: 리그램으로 분류된 게시물은 이벤트, 팝업, 홍보대사, 후기로 분류할 수 없음

## 후기 분류
이벤트/팝업/홍보대사 등에 참여한 경험을 공유하는 게시물은 tag를 "후기"로 분류하세요:
- **행사 후기**: 팝업, 전시회, 페스티벌 등 행사에 참여한 후기
- **이벤트 후기**: 이벤트 당첨 후 상품/경험 후기
- **체험 후기**: 브랜드 체험단, 방문 후기 등
- **후기는 과거형**: 이미 참여/체험한 내용을 공유하는 게시물 (모집 중인 이벤트와 구분)

## 추출할 정보
다음 JSON 형식으로 응답해주세요:
```json
{{
    "tag": "이벤트|팝업|홍보대사|리그램|후기|기타",
    "purchase_required": "예_전부|예_부분|아니오",
    "prizes": ["경품1", "경품2"],
    "winner_count": 100,
    "event_period": {{
        "start": "YYYY-MM-DD",
        "end": "YYYY-MM-DD"
    }},
    "announcement_date": "YYYY-MM-DD",
    "urls": ["https://...", "https://..."],
    "organizer": "주최사/브랜드명",
    "summary": "이벤트 요약 (50자 이내)",
    "location": {{
        "venue_name": "장소명 (예: XXX 플래그십 스토어)",
        "address": "주소 (예: 서울시 강남구 가로수길 123)"
    }}
}}
```

## 필드 설명
- tag: 게시물 유형 (이벤트/팝업/홍보대사/리그램/후기/기타). 리그램은 다른 카테고리와 중복 불가
- purchase_required: 참여에 구매가 필요한지 (예_전부: 구매 필수, 예_부분: 구매 시 추가 혜택, 아니오: 구매 불필요)
- prizes: 경품 목록 (배열)
- winner_count: 당첨자 수 (숫자, 모르면 null)
- event_period: 이벤트 기간 (시작일, 종료일)
- announcement_date: 당첨 발표일
- urls: 본문에 기재된 모든 URL 목록
- organizer: 주최사/브랜드명
- summary: 이벤트 핵심 내용 요약
- location: **팝업 태그인 경우에만** 장소명과 주소 추출 (팝업이 아니면 null)

값을 알 수 없으면 null로 표시하세요.
반드시 JSON 형식으로만 응답하세요."""


def download_image(url: str, post_id: str) -> Tuple[Optional[str], float]:
    """이미지 URL을 로컬 파일로 다운로드.

    Args:
        url: 이미지 URL
        post_id: 게시물 ID (캐시 키로 사용)

    Returns:
        (로컬 파일 경로 또는 None, 다운로드 시간 초)
    """
    start_time = time.time()
    try:
        # URL 해시로 파일명 생성
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = url.split("?")[0].split(".")[-1]
        if ext not in ["jpg", "jpeg", "png", "gif", "webp"]:
            ext = "jpg"

        filename = f"{post_id}_{url_hash}.{ext}"
        filepath = IMAGE_CACHE_DIR / filename

        # 이미 다운로드된 경우 스킵
        if filepath.exists():
            elapsed = time.time() - start_time
            logger.debug(f"Image cache hit: {filepath} ({elapsed:.2f}s)")
            return str(filepath.absolute()), elapsed

        # 다운로드
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(filepath, "wb") as f:
                f.write(response.read())

        elapsed = time.time() - start_time
        logger.info(f"Downloaded image: {url} -> {filepath} ({elapsed:.2f}s)")
        return str(filepath.absolute()), elapsed

    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning(f"Failed to download image {url}: {e} ({elapsed:.2f}s)")
        return None, elapsed


def download_post_images(post: "InstagramPost", max_images: int = 3) -> Tuple[list[str], float]:
    """게시물의 이미지들을 다운로드.

    Args:
        post: Instagram 게시물
        max_images: 최대 다운로드할 이미지 수

    Returns:
        (다운로드된 이미지 경로 목록, 총 다운로드 시간 초)
    """
    if not post.images:
        return [], 0.0

    downloaded = []
    total_time = 0.0
    for i, img in enumerate(post.images[:max_images]):
        src = img.get("src") if isinstance(img, dict) else img
        if src:
            path, elapsed = download_image(src, f"{post.id}_{i}")
            total_time += elapsed
            if path:
                downloaded.append(path)

    if downloaded:
        logger.info(f"Downloaded {len(downloaded)} images for post {post.id} (total: {total_time:.2f}s)")

    return downloaded, total_time


class LLMClassifierService:
    """LLM 기반 게시물 분류 서비스.

    claude_worker 모듈의 LLMService를 사용하여 분류를 수행합니다.
    """

    CALLER_TYPE = "instagram"

    def __init__(self, db: Session):
        self.db = db
        self._llm_service = LLMService(db)

    def should_trigger_llm(self, matched_tags: list[str]) -> bool:
        """LLM 분류가 필요한지 확인.

        Args:
            matched_tags: 키워드 분류로 매칭된 태그 이름 목록

        Returns:
            LLM 분류가 필요하면 True
        """
        return any(tag in LLM_TRIGGER_TAGS for tag in matched_tags)

    def get_trigger_tag(self, matched_tags: list[str]) -> Optional[str]:
        """LLM 분류를 트리거한 태그 반환.

        Args:
            matched_tags: 매칭된 태그 이름 목록

        Returns:
            트리거 태그 이름 또는 None
        """
        for tag in matched_tags:
            if tag in LLM_TRIGGER_TAGS:
                return tag
        return None

    def create_request(
        self,
        post_id: int,
        trigger_tag: str,
        requested_by: str = "auto",
        provider: str = "claude",
        model: str = "",
    ) -> Optional[object]:
        """LLM 분류 요청 생성 (claude_worker에 위임).

        Args:
            post_id: 게시물 ID
            trigger_tag: 트리거 태그
            requested_by: 요청자 ('auto' 또는 'manual')

        Returns:
            생성된 LLMRequest 또는 None
        """
        # 게시물 조회
        post = self.db.query(InstagramPost).filter(InstagramPost.id == post_id).first()
        if not post or not post.caption:
            logger.warning(f"Post {post_id} not found or has no caption")
            return None

        # 이미지 다운로드 (최대 3장)
        image_paths, download_time = download_post_images(post, max_images=3)

        # 이미지 섹션 생성
        if image_paths:
            image_lines = "\n".join(
                f"- 이미지 {i+1}: {path}" for i, path in enumerate(image_paths)
            )
            image_section = f"\n## 첨부 이미지\n다음 이미지 파일들을 읽고 분석에 참고하세요:\n{image_lines}\n"
        else:
            image_section = ""

        # 프롬프트 생성
        today_str = date.today().strftime("%Y-%m-%d")
        posted_at_str = post.posted_at.strftime("%Y-%m-%d") if post.posted_at else "알 수 없음"
        prompt = CLASSIFICATION_PROMPT.format(
            today=today_str,
            posted_at=posted_at_str,
            caption=post.caption,
            image_section=image_section,
        )

        # claude_worker에 요청 생성
        request = self._llm_service.enqueue(
            caller_type=self.CALLER_TYPE,
            caller_id=str(post_id),
            prompt=prompt,
            requested_by=requested_by,
            request_source=f"instagram_{trigger_tag}",
            provider=provider,
            model=model,
        )

        logger.info(
            f"LLM classification request created: post_id={post_id}, "
            f"trigger_tag={trigger_tag}, images={len(image_paths)}, download_time={download_time:.2f}s"
        )
        return request

    def create_requests_batch(
        self,
        post_ids: list[int],
        trigger_tag: str = "manual",
        requested_by: str = "manual",
        provider: str = "claude",
        model: str = "",
    ) -> list:
        """여러 게시물에 대해 LLM 분류 요청 생성."""
        requests = []
        for post_id in post_ids:
            request = self.create_request(post_id, trigger_tag, requested_by, provider=provider, model=model)
            if request:
                requests.append(request)
        return requests

    def get_result(self, post_id: int) -> Optional[dict]:
        """게시물의 LLM 분류 결과 조회.

        Args:
            post_id: 게시물 ID

        Returns:
            분류 결과 또는 None
        """
        request = self._llm_service.get_result(self.CALLER_TYPE, str(post_id))
        if not request:
            return None

        result = None
        if request.result:
            try:
                result = json.loads(request.result)
            except json.JSONDecodeError:
                pass

        return {
            "id": request.id,
            "post_id": post_id,
            "status": request.status,
            "result": result,
            "error_message": request.error_message,
            "requested_at": request.requested_at,
            "processed_at": request.processed_at,
        }

    def get_pending_count(self) -> int:
        """Instagram 관련 대기 중인 요청 수."""
        from app.modules.claude_worker.models.llm_request import LLMRequest
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.status == "pending",
            )
            .count()
        )

    def reset_to_pending(self, request_id: int) -> bool:
        """완료되었거나 실패한 요청을 다시 pending 상태로 변경."""
        from app.modules.claude_worker.models.llm_request import LLMRequest

        # 요청 조회
        request = (
            self.db.query(LLMRequest)
            .filter(LLMRequest.id == request_id)
            .first()
        )
        if not request:
            return False

        # LLMRequest reset
        success = self._llm_service.reset_to_pending(request_id)
        return success

    # Worker status는 claude_worker 모듈에 위임
    def get_worker_status(self):
        """워커 상태 조회 (claude_worker에 위임)."""
        return self._llm_service.get_worker_status()

    def check_worker_health(self) -> dict:
        """워커 헬스 체크 (claude_worker에 위임)."""
        return self._llm_service.check_worker_health()

    def get_stats(self) -> dict:
        """Instagram LLM 분류 통계 조회."""
        from app.modules.claude_worker.models.llm_request import LLMRequest

        base_query = self.db.query(LLMRequest).filter(
            LLMRequest.caller_type == self.CALLER_TYPE
        )

        total = base_query.count()
        pending = base_query.filter(LLMRequest.status == "pending").count()
        processing = base_query.filter(LLMRequest.status == "processing").count()
        completed = base_query.filter(LLMRequest.status == "completed").count()
        failed = base_query.filter(LLMRequest.status == "failed").count()

        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
        }

