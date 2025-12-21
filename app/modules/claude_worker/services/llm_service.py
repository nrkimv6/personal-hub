"""LLM Service - 범용 LLM 실행 서비스."""

import json
import logging
import re
import subprocess
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus

logger = logging.getLogger("claude_worker.llm_service")


class LLMService:
    """범용 LLM 서비스.

    Claude CLI를 subprocess로 호출하여 LLM 작업을 처리합니다.
    """

    def __init__(self, db: Session):
        self.db = db

    # ========== 큐 관리 ==========

    def enqueue(
        self,
        caller_type: str,
        caller_id: str,
        prompt: str,
    ) -> LLMRequest:
        """요청을 큐에 추가 (non-blocking).

        Args:
            caller_type: 호출자 타입 (예: 'instagram')
            caller_id: 호출자 측 ID (예: post_id)
            prompt: LLM에 전달할 프롬프트

        Returns:
            생성된 LLMRequest
        """
        # 중복 pending 요청 확인
        existing = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == caller_type,
                LLMRequest.caller_id == caller_id,
                LLMRequest.status == "pending",
            )
            .first()
        )

        if existing:
            logger.debug(f"이미 pending 요청 존재: {caller_type}:{caller_id}")
            return existing

        request = LLMRequest(
            caller_type=caller_type,
            caller_id=caller_id,
            prompt=prompt,
            status="pending",
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"LLM 요청 생성: id={request.id}, caller={caller_type}:{caller_id}")
        return request

    def get_result(
        self,
        caller_type: str,
        caller_id: str,
    ) -> Optional[LLMRequest]:
        """결과 조회.

        Args:
            caller_type: 호출자 타입
            caller_id: 호출자 측 ID

        Returns:
            가장 최근 요청 또는 None
        """
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == caller_type,
                LLMRequest.caller_id == caller_id,
            )
            .order_by(LLMRequest.requested_at.desc())
            .first()
        )

    def get_pending_request(self) -> Optional[LLMRequest]:
        """가장 오래된 pending 요청 조회 (워커용).

        Returns:
            pending 요청 또는 None
        """
        return (
            self.db.query(LLMRequest)
            .filter(LLMRequest.status == "pending")
            .order_by(LLMRequest.requested_at.asc())
            .first()
        )

    def get_pending_count(self) -> int:
        """Pending 요청 수 조회."""
        return (
            self.db.query(LLMRequest)
            .filter(LLMRequest.status == "pending")
            .count()
        )

    # ========== 상태 변경 ==========

    def mark_processing(self, request_id: int) -> None:
        """요청을 processing 상태로 변경."""
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if request:
            request.status = "processing"
            self.db.commit()

    def mark_completed(
        self,
        request_id: int,
        result: dict,
        raw_response: str = "",
    ) -> None:
        """요청을 completed 상태로 변경."""
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if request:
            request.status = "completed"
            request.processed_at = datetime.now()
            request.result = json.dumps(result, ensure_ascii=False)
            request.raw_response = raw_response
            request.error_message = None
            self.db.commit()

    def mark_failed(self, request_id: int, error_message: str) -> None:
        """요청을 failed 상태로 변경."""
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if request:
            request.status = "failed"
            request.processed_at = datetime.now()
            request.error_message = error_message
            request.retry_count += 1
            self.db.commit()

    def reset_to_pending(self, request_id: int) -> bool:
        """요청을 pending으로 리셋 (재시도용)."""
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if request and request.status == "failed":
            request.status = "pending"
            request.error_message = None
            self.db.commit()
            return True
        return False

    # ========== Claude 실행 ==========

    def execute_claude(self, prompt: str, timeout: int = 120) -> dict:
        """Claude CLI 실행 (동기).

        Args:
            prompt: LLM 프롬프트
            timeout: 타임아웃 (초)

        Returns:
            {"success": True, "result": {...}, "raw_response": "..."}
            또는
            {"success": False, "error": "..."}
        """
        try:
            import sys
            # Windows에서는 shell=True 필요 (.cmd 파일 실행)
            use_shell = sys.platform == "win32"

            result = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                shell=use_shell,
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Claude CLI error: {result.stderr or 'Unknown error'}",
                }

            raw_response = result.stdout.strip()

            # JSON 파싱
            try:
                parsed = self._parse_json_response(raw_response)
                return {
                    "success": True,
                    "result": parsed,
                    "raw_response": raw_response,
                }
            except ValueError as e:
                return {
                    "success": False,
                    "error": f"JSON 파싱 실패: {e}",
                    "raw_response": raw_response,
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Timeout ({timeout}s)",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _parse_json_response(self, text: str) -> dict:
        """Claude 응답에서 JSON 추출.

        Args:
            text: Claude 응답 텍스트

        Returns:
            파싱된 JSON dict

        Raises:
            ValueError: JSON 파싱 실패
        """
        # ```json ... ``` 블록 추출
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if json_match:
            return json.loads(json_match.group(1))

        # 순수 JSON 시도
        text = text.strip()
        if text.startswith("{"):
            return json.loads(text)

        # { } 블록 추출
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            return json.loads(brace_match.group())

        raise ValueError("No valid JSON found in response")

    # ========== 워커 상태 관리 ==========

    def register_worker(self, worker_id: str, pid: int) -> LLMWorkerStatus:
        """워커 등록."""
        # 기존 워커 비활성화
        self.db.query(LLMWorkerStatus).filter(
            LLMWorkerStatus.is_alive == True
        ).update({"is_alive": False})

        now = datetime.now()
        status = LLMWorkerStatus(
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
        return status

    def update_heartbeat(self, worker_id: str) -> None:
        """하트비트 업데이트."""
        status = (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.last_heartbeat = datetime.now()
            self.db.commit()

    def update_worker_state(
        self, worker_id: str, state: str, request_id: int = None
    ) -> None:
        """워커 상태 업데이트."""
        status = (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.current_state = state
            status.current_request_id = request_id
            self.db.commit()

    def increment_processed(self, worker_id: str) -> None:
        """처리 카운트 증가."""
        status = (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.processed_count += 1
            self.db.commit()

    def increment_error(self, worker_id: str) -> None:
        """에러 카운트 증가."""
        status = (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.error_count += 1
            self.db.commit()

    def mark_worker_dead(self, worker_id: str) -> None:
        """워커 종료 표시."""
        status = (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.worker_id == worker_id)
            .first()
        )
        if status:
            status.is_alive = False
            status.current_state = "stopped"
            self.db.commit()

    def get_worker_status(self) -> Optional[LLMWorkerStatus]:
        """활성 워커 상태 조회."""
        return (
            self.db.query(LLMWorkerStatus)
            .filter(LLMWorkerStatus.is_alive == True)
            .first()
        )

    def check_worker_health(self) -> dict:
        """워커 건강 상태 확인."""
        status = self.get_worker_status()
        if not status:
            return {"status": "no_worker", "message": "No active worker"}

        now = datetime.now()
        if status.last_heartbeat:
            seconds_since = (now - status.last_heartbeat).total_seconds()
            if seconds_since > 60:
                return {
                    "status": "unhealthy",
                    "message": f"Last heartbeat {seconds_since:.0f}s ago",
                    "worker_id": status.worker_id,
                }

        return {
            "status": "healthy",
            "worker_id": status.worker_id,
            "state": status.current_state,
            "processed_count": status.processed_count,
        }

    # ========== 통계 ==========

    def get_stats(self) -> dict:
        """통계 조회."""
        total = self.db.query(LLMRequest).count()
        pending = self.db.query(LLMRequest).filter(LLMRequest.status == "pending").count()
        processing = self.db.query(LLMRequest).filter(LLMRequest.status == "processing").count()
        completed = self.db.query(LLMRequest).filter(LLMRequest.status == "completed").count()
        failed = self.db.query(LLMRequest).filter(LLMRequest.status == "failed").count()

        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
        }
