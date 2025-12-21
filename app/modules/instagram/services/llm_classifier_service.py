"""Instagram LLM Classifier Service - LLM 기반 이벤트 분류 서비스."""

import json
import logging
import re
import subprocess
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import InstagramPost
from app.models.instagram_llm_request import (
    InstagramLLMClassificationRequest,
    InstagramLLMWorkerStatus,
)

logger = logging.getLogger("instagram.llm_classifier")


# LLM 분류를 트리거하는 태그 목록
LLM_TRIGGER_TAGS = ["event"]

# 프롬프트 템플릿
CLASSIFICATION_PROMPT = """다음 Instagram 게시물을 분석하여 이벤트 정보를 추출해주세요.

## 게시물 내용
{caption}

## 추출할 정보
다음 JSON 형식으로 응답해주세요:
```json
{{
    "is_event": true,
    "organizer": "주최사/브랜드명",
    "event_url": "이벤트 URL (있는 경우, 없으면 null)",
    "event_date": "이벤트 날짜 (YYYY-MM-DD 형식, 여러 날이면 시작일, 없으면 null)",
    "event_time": "이벤트 시간 (HH:MM 형식, 없으면 null)",
    "details": "이벤트 상세 내용 요약 (100자 이내)",
    "confidence": 0.0~1.0 사이의 확신도
}}
```

이벤트가 아닌 경우:
```json
{{
    "is_event": false,
    "reason": "이벤트가 아닌 이유"
}}
```

반드시 JSON 형식으로만 응답하세요."""


class LLMClassifierService:
    """LLM 기반 게시물 분류 서비스.

    Claude CLI를 subprocess로 호출하여 게시물을 분류합니다.
    """

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

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
    ) -> Optional[InstagramLLMClassificationRequest]:
        """LLM 분류 요청 생성.

        Args:
            post_id: 게시물 ID
            trigger_tag: 트리거 태그
            requested_by: 요청자 ('auto' 또는 'manual')

        Returns:
            생성된 요청 또는 None (중복인 경우)
        """
        # 중복 방지: pending 상태인 동일 post_id 요청이 있으면 스킵
        existing = (
            self.db.query(InstagramLLMClassificationRequest)
            .filter(
                InstagramLLMClassificationRequest.post_id == post_id,
                InstagramLLMClassificationRequest.status == "pending",
            )
            .first()
        )

        if existing:
            logger.debug(f"LLM request already exists for post {post_id}")
            return existing

        request = InstagramLLMClassificationRequest(
            post_id=post_id,
            trigger_tag=trigger_tag,
            requested_by=requested_by,
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"LLM classification request created: post_id={post_id}, trigger_tag={trigger_tag}")
        return request

    def create_requests_batch(
        self,
        post_ids: list[int],
        trigger_tag: str = "manual",
        requested_by: str = "manual",
    ) -> list[InstagramLLMClassificationRequest]:
        """여러 게시물에 대해 LLM 분류 요청 생성.

        Args:
            post_ids: 게시물 ID 목록
            trigger_tag: 트리거 태그
            requested_by: 요청자

        Returns:
            생성된 요청 목록
        """
        requests = []
        for post_id in post_ids:
            request = self.create_request(post_id, trigger_tag, requested_by)
            if request:
                requests.append(request)
        return requests

    def get_pending_request(self) -> Optional[InstagramLLMClassificationRequest]:
        """처리 대기 중인 요청 조회 (FIFO).

        Returns:
            가장 오래된 pending 요청 또는 None
        """
        return (
            self.db.query(InstagramLLMClassificationRequest)
            .filter(InstagramLLMClassificationRequest.status == "pending")
            .order_by(InstagramLLMClassificationRequest.requested_at)
            .first()
        )

    def get_pending_count(self) -> int:
        """대기 중인 요청 수 조회.

        Returns:
            pending 상태의 요청 수
        """
        return (
            self.db.query(InstagramLLMClassificationRequest)
            .filter(InstagramLLMClassificationRequest.status == "pending")
            .count()
        )

    def mark_processing(self, request_id: int) -> None:
        """요청을 처리 중으로 표시.

        Args:
            request_id: 요청 ID
        """
        request = self.db.query(InstagramLLMClassificationRequest).get(request_id)
        if request:
            request.status = "processing"
            self.db.commit()
            logger.debug(f"LLM request {request_id} marked as processing")

    def mark_completed(
        self,
        request_id: int,
        result: dict,
        confidence: float,
        prompt: str,
        raw_response: str,
    ) -> None:
        """요청 완료 처리.

        Args:
            request_id: 요청 ID
            result: 분류 결과
            confidence: 확신도
            prompt: 사용된 프롬프트
            raw_response: Claude 원본 응답
        """
        request = self.db.query(InstagramLLMClassificationRequest).get(request_id)
        if request:
            request.status = "completed"
            request.processed_at = datetime.now()
            request.llm_result = json.dumps(result, ensure_ascii=False)
            request.confidence_score = confidence
            request.prompt_used = prompt
            request.raw_response = raw_response
            self.db.commit()
            logger.info(f"LLM request {request_id} completed with confidence {confidence}")

    def mark_failed(self, request_id: int, error_message: str) -> None:
        """요청 실패 처리.

        Args:
            request_id: 요청 ID
            error_message: 에러 메시지
        """
        request = self.db.query(InstagramLLMClassificationRequest).get(request_id)
        if request:
            request.status = "failed"
            request.processed_at = datetime.now()
            request.error_message = error_message
            request.retry_count += 1
            self.db.commit()
            logger.warning(f"LLM request {request_id} failed: {error_message}")

    def reset_to_pending(self, request_id: int) -> bool:
        """실패한 요청을 다시 pending 상태로 변경.

        Args:
            request_id: 요청 ID

        Returns:
            성공 여부
        """
        request = self.db.query(InstagramLLMClassificationRequest).get(request_id)
        if request and request.status == "failed":
            request.status = "pending"
            request.error_message = None
            self.db.commit()
            logger.info(f"LLM request {request_id} reset to pending")
            return True
        return False

    def execute_claude_classification(
        self,
        caption: str,
        timeout: int = 120,
    ) -> dict:
        """Claude CLI로 분류 실행.

        Args:
            caption: 게시물 본문
            timeout: 타임아웃 (초)

        Returns:
            {"success": bool, "result": dict, "raw_response": str, "prompt": str, "error": str}
        """
        prompt = CLASSIFICATION_PROMPT.format(caption=caption)

        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )

            if result.returncode != 0:
                error_msg = result.stderr or f"Exit code: {result.returncode}"
                return {
                    "success": False,
                    "error": f"Claude CLI error: {error_msg}",
                    "prompt": prompt,
                }

            response_text = result.stdout.strip()
            parsed = self._parse_json_response(response_text)

            return {
                "success": True,
                "result": parsed,
                "raw_response": response_text,
                "prompt": prompt,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Timeout: {timeout}초 초과",
                "prompt": prompt,
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Claude CLI not found. Please install claude-code.",
                "prompt": prompt,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "prompt": prompt,
            }

    def _parse_json_response(self, text: str) -> dict:
        """Claude 응답에서 JSON 추출.

        Args:
            text: Claude 응답 텍스트

        Returns:
            파싱된 JSON 객체

        Raises:
            ValueError: JSON 파싱 실패
        """
        # ```json ... ``` 블록 추출
        json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # 직접 JSON 파싱 시도 (응답이 순수 JSON인 경우)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # { ... } 블록 추출 시도
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            return json.loads(brace_match.group(0))

        raise ValueError(f"Could not parse JSON from response: {text[:200]}...")

    # Worker Status Methods

    def get_worker_status(self) -> Optional[InstagramLLMWorkerStatus]:
        """활성 워커 상태 조회.

        Returns:
            활성 워커 상태 또는 None
        """
        return (
            self.db.query(InstagramLLMWorkerStatus)
            .filter(InstagramLLMWorkerStatus.is_alive == True)
            .order_by(InstagramLLMWorkerStatus.last_heartbeat.desc())
            .first()
        )

    def register_worker(self, worker_id: str, pid: int) -> InstagramLLMWorkerStatus:
        """워커 등록.

        Args:
            worker_id: 워커 UUID
            pid: 프로세스 ID

        Returns:
            워커 상태 객체
        """
        now = datetime.now()
        status = InstagramLLMWorkerStatus(
            worker_id=worker_id,
            pid=pid,
            started_at=now,
            last_heartbeat=now,
            current_state="idle",
            is_alive=True,
        )
        self.db.add(status)
        self.db.commit()
        self.db.refresh(status)
        logger.info(f"LLM Worker registered: {worker_id} (PID: {pid})")
        return status

    def update_heartbeat(self, worker_id: str) -> Optional[InstagramLLMWorkerStatus]:
        """워커 하트비트 업데이트.

        Args:
            worker_id: 워커 UUID

        Returns:
            워커 상태 또는 None
        """
        status = (
            self.db.query(InstagramLLMWorkerStatus)
            .filter(InstagramLLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.last_heartbeat = datetime.now()
            self.db.commit()
        return status

    def update_worker_state(
        self,
        worker_id: str,
        state: str,
        current_request_id: Optional[int] = None,
    ) -> None:
        """워커 상태 업데이트.

        Args:
            worker_id: 워커 UUID
            state: 새 상태 ('idle', 'processing')
            current_request_id: 현재 처리 중인 요청 ID
        """
        status = (
            self.db.query(InstagramLLMWorkerStatus)
            .filter(InstagramLLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.current_state = state
            status.current_request_id = current_request_id
            status.last_heartbeat = datetime.now()
            self.db.commit()

    def increment_processed(self, worker_id: str) -> None:
        """처리 카운트 증가.

        Args:
            worker_id: 워커 UUID
        """
        status = (
            self.db.query(InstagramLLMWorkerStatus)
            .filter(InstagramLLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.processed_count += 1
            self.db.commit()

    def increment_error(self, worker_id: str) -> None:
        """에러 카운트 증가.

        Args:
            worker_id: 워커 UUID
        """
        status = (
            self.db.query(InstagramLLMWorkerStatus)
            .filter(InstagramLLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.error_count += 1
            self.db.commit()

    def mark_worker_dead(self, worker_id: str) -> None:
        """워커를 종료 상태로 표시.

        Args:
            worker_id: 워커 UUID
        """
        status = (
            self.db.query(InstagramLLMWorkerStatus)
            .filter(InstagramLLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.is_alive = False
            status.current_state = "stopped"
            self.db.commit()
            logger.info(f"LLM Worker marked as dead: {worker_id}")

    def check_worker_health(self) -> dict:
        """워커 헬스 체크.

        Returns:
            {"status": "healthy/warning/dead/no_worker", "message": str, "worker": Optional[dict]}
        """
        worker = self.get_worker_status()

        if not worker:
            return {
                "status": "no_worker",
                "message": "No active LLM worker found",
                "worker": None,
            }

        now = datetime.now()
        seconds_since_heartbeat = (now - worker.last_heartbeat).total_seconds()

        if seconds_since_heartbeat <= 60:
            status = "healthy"
            message = "Worker is responding normally"
        elif seconds_since_heartbeat <= 120:
            status = "warning"
            message = f"Worker heartbeat delayed ({int(seconds_since_heartbeat)}s ago)"
        else:
            status = "dead"
            message = f"Worker not responding ({int(seconds_since_heartbeat)}s since last heartbeat)"

        return {
            "status": status,
            "message": message,
            "worker": {
                "worker_id": worker.worker_id,
                "pid": worker.pid,
                "state": worker.current_state,
                "started_at": worker.started_at.isoformat(),
                "last_heartbeat": worker.last_heartbeat.isoformat(),
                "processed_count": worker.processed_count,
                "error_count": worker.error_count,
            },
        }

    def get_stats(self) -> dict:
        """LLM 분류 통계 조회.

        Returns:
            통계 정보
        """
        total = self.db.query(InstagramLLMClassificationRequest).count()
        pending = (
            self.db.query(InstagramLLMClassificationRequest)
            .filter(InstagramLLMClassificationRequest.status == "pending")
            .count()
        )
        processing = (
            self.db.query(InstagramLLMClassificationRequest)
            .filter(InstagramLLMClassificationRequest.status == "processing")
            .count()
        )
        completed = (
            self.db.query(InstagramLLMClassificationRequest)
            .filter(InstagramLLMClassificationRequest.status == "completed")
            .count()
        )
        failed = (
            self.db.query(InstagramLLMClassificationRequest)
            .filter(InstagramLLMClassificationRequest.status == "failed")
            .count()
        )

        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
        }
