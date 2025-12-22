"""LLM Service - 범용 LLM 실행 서비스."""

import json
import logging
import re
import subprocess
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import func
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
        requested_by: str = "unknown",
        request_source: str = None,
    ) -> LLMRequest:
        """요청을 큐에 추가 (non-blocking).

        Args:
            caller_type: 호출자 타입 (예: 'instagram')
            caller_id: 호출자 측 ID (예: post_id)
            prompt: LLM에 전달할 프롬프트
            requested_by: 요청자 (예: 'api', 'scheduler', 'manual')
            request_source: 요청 출처 (예: 'instagram_crawl', 'manual_test')

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
                LLMRequest.deleted_at.is_(None),
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
            requested_by=requested_by,
            request_source=request_source,
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"LLM 요청 생성: id={request.id}, caller={caller_type}:{caller_id}, by={requested_by}")
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
            .filter(
                LLMRequest.status == "pending",
                LLMRequest.deleted_at.is_(None),
            )
            .order_by(LLMRequest.requested_at.asc())
            .first()
        )

    def get_pending_count(self) -> int:
        """Pending 요청 수 조회."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "pending",
                LLMRequest.deleted_at.is_(None),
            )
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
            import tempfile
            import os

            # 프롬프트를 임시 파일에 저장하여 전달 (긴 프롬프트 및 특수문자 처리)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            # PATH에 npm bin 경로 추가 (Windows)
            env = os.environ.copy()
            if sys.platform == "win32":
                npm_path = os.path.expanduser("~/AppData/Roaming/npm")
                if npm_path not in env.get("PATH", ""):
                    env["PATH"] = npm_path + ";" + env.get("PATH", "")

            try:
                # 파일에서 프롬프트 읽어서 실행
                # --tools "Read" 추가하여 이미지 파일 읽기 가능
                tools_opt = '--tools "Read"'
                if sys.platform == "win32":
                    # Windows: shell=True 필요
                    cmd = f'type "{prompt_file}" | claude -p {tools_opt}'
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        encoding="utf-8",
                        shell=True,
                        env=env,
                    )
                else:
                    # Unix: cat으로 파이프
                    cmd = f'cat "{prompt_file}" | claude -p {tools_opt}'
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        encoding="utf-8",
                        shell=True,
                        env=env,
                    )
            finally:
                # 임시 파일 삭제
                os.unlink(prompt_file)

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

    # ========== 요청 관리 ==========

    def list_requests(
        self,
        status: str = None,
        caller_type: str = None,
        requested_by: str = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """요청 목록 조회 (페이지네이션).

        Args:
            status: 상태 필터 (pending, processing, completed, failed, cancelled)
            caller_type: 호출자 타입 필터
            requested_by: 요청자 필터
            include_deleted: 삭제된 요청 포함 여부
            page: 페이지 번호 (1부터 시작)
            page_size: 페이지 크기

        Returns:
            {"items": [...], "total": n, "page": n, "page_size": n, "pages": n}
        """
        query = self.db.query(LLMRequest)

        if not include_deleted:
            query = query.filter(LLMRequest.deleted_at.is_(None))
        if status:
            query = query.filter(LLMRequest.status == status)
        if caller_type:
            query = query.filter(LLMRequest.caller_type == caller_type)
        if requested_by:
            query = query.filter(LLMRequest.requested_by == requested_by)

        total = query.count()
        pages = (total + page_size - 1) // page_size

        items = (
            query.order_by(LLMRequest.requested_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_request_by_id(self, request_id: int) -> Optional[LLMRequest]:
        """단일 요청 조회."""
        return self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()

    def cancel_request(self, request_id: int) -> bool:
        """pending 요청 취소.

        Returns:
            True if cancelled, False if not found or not pending
        """
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if request and request.status == "pending":
            request.status = "cancelled"
            request.processed_at = datetime.now()
            self.db.commit()
            logger.info(f"LLM 요청 취소: id={request_id}")
            return True
        return False

    def delete_request(self, request_id: int, hard_delete: bool = False) -> bool:
        """요청 삭제.

        Args:
            request_id: 요청 ID
            hard_delete: True면 물리 삭제, False면 soft delete

        Returns:
            True if deleted, False if not found
        """
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if not request:
            return False

        if hard_delete:
            self.db.delete(request)
        else:
            request.deleted_at = datetime.now()
        self.db.commit()
        logger.info(f"LLM 요청 삭제: id={request_id}, hard={hard_delete}")
        return True

    def batch_retry(self, request_ids: List[int]) -> dict:
        """일괄 재시도.

        Args:
            request_ids: 재시도할 요청 ID 목록

        Returns:
            {"success": n, "failed": n, "skipped": n}
        """
        success = 0
        failed = 0
        skipped = 0

        for request_id in request_ids:
            request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
            if not request:
                skipped += 1
                continue
            if request.status != "failed":
                skipped += 1
                continue

            request.status = "pending"
            request.error_message = None
            success += 1

        self.db.commit()
        return {"success": success, "failed": failed, "skipped": skipped}

    def batch_delete(self, request_ids: List[int], hard_delete: bool = False) -> dict:
        """일괄 삭제.

        Args:
            request_ids: 삭제할 요청 ID 목록
            hard_delete: True면 물리 삭제

        Returns:
            {"deleted": n, "skipped": n}
        """
        deleted = 0
        skipped = 0

        for request_id in request_ids:
            if self.delete_request(request_id, hard_delete):
                deleted += 1
            else:
                skipped += 1

        return {"deleted": deleted, "skipped": skipped}

    # ========== 이력 및 통계 ==========

    def get_history_stats(
        self,
        start_date: date = None,
        end_date: date = None,
        group_by: str = "day",
    ) -> dict:
        """기간별 통계.

        Args:
            start_date: 시작일 (기본: 7일 전)
            end_date: 종료일 (기본: 오늘)
            group_by: 그룹 단위 (day, week, month)

        Returns:
            {"data": [...], "summary": {...}}
        """
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date - timedelta(days=7)

        # 날짜 범위 필터
        query = self.db.query(LLMRequest).filter(
            LLMRequest.requested_at >= datetime.combine(start_date, datetime.min.time()),
            LLMRequest.requested_at <= datetime.combine(end_date, datetime.max.time()),
            LLMRequest.deleted_at.is_(None),
        )

        all_requests = query.all()

        # 일별 그룹화
        daily_data = {}
        for req in all_requests:
            day_key = req.requested_at.date().isoformat()
            if day_key not in daily_data:
                daily_data[day_key] = {"date": day_key, "total": 0, "completed": 0, "failed": 0, "pending": 0}
            daily_data[day_key]["total"] += 1
            if req.status == "completed":
                daily_data[day_key]["completed"] += 1
            elif req.status == "failed":
                daily_data[day_key]["failed"] += 1
            elif req.status in ("pending", "processing"):
                daily_data[day_key]["pending"] += 1

        # 정렬
        data = sorted(daily_data.values(), key=lambda x: x["date"])

        # 요약 통계
        total = len(all_requests)
        completed = sum(1 for r in all_requests if r.status == "completed")
        failed = sum(1 for r in all_requests if r.status == "failed")

        # 평균 처리 시간 (완료된 요청만)
        processing_times = []
        for req in all_requests:
            if req.status == "completed" and req.processed_at and req.requested_at:
                seconds = (req.processed_at - req.requested_at).total_seconds()
                processing_times.append(seconds)

        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0

        return {
            "data": data,
            "summary": {
                "total": total,
                "completed": completed,
                "failed": failed,
                "success_rate": round(completed / total * 100, 1) if total > 0 else 0,
                "avg_processing_time_seconds": round(avg_processing_time, 1),
            },
        }

    def get_caller_stats(self) -> dict:
        """호출자별 통계."""
        results = (
            self.db.query(
                LLMRequest.caller_type,
                LLMRequest.status,
                func.count(LLMRequest.id).label("count"),
            )
            .filter(LLMRequest.deleted_at.is_(None))
            .group_by(LLMRequest.caller_type, LLMRequest.status)
            .all()
        )

        stats = {}
        for caller_type, status, count in results:
            if caller_type not in stats:
                stats[caller_type] = {"total": 0, "pending": 0, "processing": 0, "completed": 0, "failed": 0}
            stats[caller_type][status] = count
            stats[caller_type]["total"] += count

        return stats

    # ========== 기본 통계 ==========

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
