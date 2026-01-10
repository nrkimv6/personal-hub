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

# 워커 헬스체크 임계값 (초)
HEARTBEAT_WARNING_THRESHOLD = 120  # 2분: warning 상태
HEARTBEAT_UNHEALTHY_THRESHOLD = 600  # 10분: unhealthy 상태


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
        """요청을 pending으로 리셋 (재시도용).

        failed 상태인 요청만 pending으로 변경할 수 있습니다.
        completed 상태는 이미 처리 완료되었으므로 리셋 불가.
        """
        request = self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        if request and request.status == "failed":
            request.status = "pending"
            request.error_message = None
            request.result = None
            request.raw_response = None
            request.processed_at = None
            self.db.commit()
            return True
        return False

    # ========== Claude 실행 ==========

    def execute_claude(self, prompt: str, timeout: int = 120, parse_json: bool = True, enable_tools: bool = False) -> dict:
        """Claude CLI 실행 (동기).

        Args:
            prompt: LLM 프롬프트
            timeout: 타임아웃 (초)
            parse_json: True면 JSON 파싱 시도, False면 raw_response만 반환
            enable_tools: True면 Read 도구 활성화 (이미지 분석 등), False면 도구 없이 실행

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

                # HOME/USERPROFILE 환경 변수 확인 및 설정
                # 시작프로그램에서 실행 시 HOME이 설정되지 않을 수 있음
                userprofile = env.get("USERPROFILE", "")
                home = env.get("HOME", "")
                if not home and userprofile:
                    env["HOME"] = userprofile
                    logger.debug(f"HOME 환경변수 설정: {userprofile}")

                logger.debug(f"Claude CLI 실행 환경: HOME={env.get('HOME')}, USERPROFILE={env.get('USERPROFILE')}")

            try:
                # 파일에서 프롬프트 읽어서 실행
                # enable_tools=True일 때만 --tools "Read" 추가 (이미지 분석 등)
                # enable_tools에 따라 명령어 구성
                # -p (prompt mode)는 Claude Code 컨텍스트를 활성화하므로 사용하지 않음
                if enable_tools:
                    tools_opt = '--tools "Read"'
                else:
                    tools_opt = ''

                if sys.platform == "win32":
                    # Windows: shell=True 필요
                    cmd = f'type "{prompt_file}" | claude {tools_opt}'
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
                    cmd = f'cat "{prompt_file}" | claude {tools_opt}'
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
                # stderr가 비어있을 수 있으므로 stdout도 확인
                error_details = result.stderr.strip() if result.stderr else ""
                if not error_details and result.stdout:
                    error_details = result.stdout.strip()[:500]  # stdout에서 에러 메시지 추출
                if not error_details:
                    error_details = f"returncode={result.returncode}"
                return {
                    "success": False,
                    "error": f"Claude CLI error: {error_details}",
                }

            raw_response = result.stdout.strip()

            # JSON 파싱 (선택적)
            if parse_json:
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
            else:
                # JSON 파싱 없이 raw_response만 반환
                return {
                    "success": True,
                    "result": None,
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
        """워커 건강 상태 확인.

        Returns:
            dict with keys:
                - status: "healthy" | "warning" | "unhealthy" | "no_worker"
                - message: 상태 설명
                - worker_id: 워커 ID (있는 경우)
                - state: 현재 상태 (healthy/warning인 경우)
                - processed_count: 처리 건수 (healthy인 경우)
                - seconds_since_heartbeat: 마지막 heartbeat 이후 경과 시간
        """
        status = self.get_worker_status()
        if not status:
            return {"status": "no_worker", "message": "활성 워커 없음"}

        now = datetime.now()
        if status.last_heartbeat:
            seconds_since = (now - status.last_heartbeat).total_seconds()

            if seconds_since > HEARTBEAT_UNHEALTHY_THRESHOLD:
                return {
                    "status": "unhealthy",
                    "message": f"마지막 heartbeat {seconds_since/60:.0f}분 전 - 재시작 필요",
                    "worker_id": status.worker_id,
                    "seconds_since_heartbeat": int(seconds_since),
                }
            elif seconds_since > HEARTBEAT_WARNING_THRESHOLD:
                return {
                    "status": "warning",
                    "message": f"마지막 heartbeat {seconds_since:.0f}초 전 - 지연 발생",
                    "worker_id": status.worker_id,
                    "state": status.current_state,
                    "seconds_since_heartbeat": int(seconds_since),
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
            status: 상태 필터. 콤마로 구분하여 여러 상태 지정 가능
                    (예: "completed,failed,cancelled")
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
            # 콤마로 구분된 여러 상태 지원
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if len(statuses) == 1:
                query = query.filter(LLMRequest.status == statuses[0])
            elif len(statuses) > 1:
                query = query.filter(LLMRequest.status.in_(statuses))
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
            request.result = None
            request.raw_response = None
            request.processed_at = None
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

    # ========== Cleanup ==========

    # 상수 정의
    STALE_PROCESSING_TIMEOUT_MINUTES = 10
    HISTORY_RETENTION_DAYS = 7

    def cleanup_stale_processing(self, timeout_minutes: int = None) -> int:
        """Stale processing 요청을 failed로 변경.

        워커가 비정상 종료되어 processing 상태로 stuck된 요청을 정리합니다.

        Args:
            timeout_minutes: 타임아웃 (분). 기본값: STALE_PROCESSING_TIMEOUT_MINUTES (10분)

        Returns:
            처리된 요청 수
        """
        if timeout_minutes is None:
            timeout_minutes = self.STALE_PROCESSING_TIMEOUT_MINUTES

        threshold = datetime.now() - timedelta(minutes=timeout_minutes)

        # processing 상태이면서 requested_at이 threshold보다 오래된 요청
        stale_requests = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "processing",
                LLMRequest.requested_at < threshold,
                LLMRequest.deleted_at.is_(None),
            )
            .all()
        )

        count = 0
        for request in stale_requests:
            request.status = "failed"
            request.processed_at = datetime.now()
            request.error_message = f"Stale processing: timeout after {timeout_minutes} minutes"
            request.retry_count += 1
            count += 1
            logger.info(f"Stale processing 정리: id={request.id}, caller={request.caller_type}:{request.caller_id}")

        if count > 0:
            self.db.commit()
            logger.info(f"Stale processing 정리 완료: {count}개")

        return count

    def cleanup_old_history(self, days: int = None, hard_delete: bool = True) -> int:
        """오래된 이력 삭제.

        completed/failed/cancelled 상태인 요청 중 일정 기간이 지난 것을 삭제합니다.

        Args:
            days: 보관 기간 (일). 기본값: HISTORY_RETENTION_DAYS (7일)
            hard_delete: True면 물리 삭제, False면 soft delete

        Returns:
            삭제된 요청 수
        """
        if days is None:
            days = self.HISTORY_RETENTION_DAYS

        threshold = datetime.now() - timedelta(days=days)

        # completed/failed/cancelled 상태이면서 processed_at이 threshold보다 오래된 요청
        old_requests = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status.in_(["completed", "failed", "cancelled"]),
                LLMRequest.processed_at < threshold,
                LLMRequest.deleted_at.is_(None),
            )
            .all()
        )

        count = 0
        for request in old_requests:
            if hard_delete:
                self.db.delete(request)
            else:
                request.deleted_at = datetime.now()
            count += 1

        if count > 0:
            self.db.commit()
            logger.info(f"오래된 이력 삭제 완료: {count}개 (days={days}, hard_delete={hard_delete})")

        return count

    def run_cleanup(self) -> dict:
        """전체 cleanup 실행.

        Returns:
            {"stale_processing": n, "old_history": n}
        """
        stale = self.cleanup_stale_processing()
        old = self.cleanup_old_history()
        return {"stale_processing": stale, "old_history": old}

    # ========== 호출자별 그룹화 ==========

    def list_requests_grouped_by_caller(
        self,
        caller_type: str = None,
        only_without_success: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """caller_id별로 그룹화된 요청 목록 조회.

        Args:
            caller_type: 호출자 타입 필터
            only_without_success: True면 성공한 적 없는 caller만 조회
            page: 페이지 번호
            page_size: 페이지 크기

        Returns:
            {
                "items": [
                    {
                        "caller_type": str,
                        "caller_id": str,
                        "total_count": int,
                        "completed_count": int,
                        "failed_count": int,
                        "pending_count": int,
                        "has_success": bool,
                        "last_status": str,
                        "last_requested_at": datetime,
                        "last_error": str | None,
                        "request_ids": list[int]  # 실패한 요청 ID들
                    }
                ],
                "total": int,
                "page": int,
                "page_size": int,
                "pages": int,
                "summary": {
                    "total_callers": int,
                    "callers_with_success": int,
                    "callers_without_success": int
                }
            }
        """
        from sqlalchemy import case, and_

        # 기본 쿼리: caller_type + caller_id로 그룹화
        base_query = self.db.query(LLMRequest).filter(
            LLMRequest.deleted_at.is_(None)
        )
        if caller_type:
            base_query = base_query.filter(LLMRequest.caller_type == caller_type)

        # 모든 caller_id별 요청 조회
        all_requests = base_query.all()

        # caller별 그룹화
        caller_groups = {}
        for req in all_requests:
            key = (req.caller_type, req.caller_id)
            if key not in caller_groups:
                caller_groups[key] = {
                    "caller_type": req.caller_type,
                    "caller_id": req.caller_id,
                    "total_count": 0,
                    "completed_count": 0,
                    "failed_count": 0,
                    "pending_count": 0,
                    "has_success": False,
                    "last_status": None,
                    "last_requested_at": None,
                    "last_error": None,
                    "request_ids": [],  # 실패한 요청 ID들
                    "prompt": req.prompt,  # 첫 번째 요청의 prompt
                }

            group = caller_groups[key]
            group["total_count"] += 1

            if req.status == "completed":
                group["completed_count"] += 1
                group["has_success"] = True
            elif req.status == "failed":
                group["failed_count"] += 1
                group["request_ids"].append(req.id)
                if req.error_message:
                    group["last_error"] = req.error_message
            elif req.status in ("pending", "processing"):
                group["pending_count"] += 1

            # 최신 요청 추적
            if group["last_requested_at"] is None or req.requested_at > group["last_requested_at"]:
                group["last_requested_at"] = req.requested_at
                group["last_status"] = req.status

        # 리스트로 변환 및 정렬
        items = list(caller_groups.values())

        # 성공 없는 것만 필터링
        if only_without_success:
            items = [g for g in items if not g["has_success"]]

        # 최신순 정렬
        items.sort(key=lambda x: x["last_requested_at"] or datetime.min, reverse=True)

        # 요약 통계
        total_callers = len(caller_groups)
        callers_with_success = sum(1 for g in caller_groups.values() if g["has_success"])
        callers_without_success = total_callers - callers_with_success

        # 페이지네이션
        total = len(items)
        pages = (total + page_size - 1) // page_size if total > 0 else 1
        start = (page - 1) * page_size
        end = start + page_size
        paginated_items = items[start:end]

        # datetime을 ISO string으로 변환
        for item in paginated_items:
            if item["last_requested_at"]:
                item["last_requested_at"] = item["last_requested_at"].isoformat()

        return {
            "items": paginated_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "summary": {
                "total_callers": total_callers,
                "callers_with_success": callers_with_success,
                "callers_without_success": callers_without_success,
            }
        }

    def retry_failed_callers_without_success(self, caller_type: str = None) -> dict:
        """성공한 적 없는 caller들의 실패 요청을 일괄 재시도.

        Args:
            caller_type: 호출자 타입 필터 (선택)

        Returns:
            {"retried": n, "callers": n}
        """
        # 그룹화된 데이터 조회
        grouped = self.list_requests_grouped_by_caller(
            caller_type=caller_type,
            only_without_success=True,
            page=1,
            page_size=10000,  # 전체 조회
        )

        retried = 0
        callers = 0

        for group in grouped["items"]:
            if group["request_ids"]:
                callers += 1
                for request_id in group["request_ids"]:
                    request = self.db.query(LLMRequest).filter(
                        LLMRequest.id == request_id
                    ).first()
                    if request and request.status == "failed":
                        request.status = "pending"
                        request.error_message = None
                        request.result = None
                        request.raw_response = None
                        request.processed_at = None
                        retried += 1

        if retried > 0:
            self.db.commit()
            logger.info(f"성공 없는 caller 일괄 재시도: {retried}개 요청, {callers}개 caller")

        return {"retried": retried, "callers": callers}

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

    # ========== 성능 분석 ==========

    def get_performance_stats(self, hours: int = 24) -> dict:
        """성능 분석 통계.

        Args:
            hours: 분석 기간 (시간)

        Returns:
            LLM 처리 시간 통계, 시간대별 분포 등
        """
        threshold = datetime.now() - timedelta(hours=hours)

        # 완료된 요청만 조회
        completed_requests = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "completed",
                LLMRequest.requested_at >= threshold,
                LLMRequest.processed_at.isnot(None),
                LLMRequest.deleted_at.is_(None),
            )
            .all()
        )

        # 실패한 요청 수
        failed_count = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "failed",
                LLMRequest.requested_at >= threshold,
                LLMRequest.deleted_at.is_(None),
            )
            .count()
        )

        # 처리 시간 계산
        processing_times = []
        for req in completed_requests:
            if req.processed_at and req.requested_at:
                seconds = (req.processed_at - req.requested_at).total_seconds()
                processing_times.append(seconds)

        # 통계 계산
        if processing_times:
            processing_times.sort()
            total_requests = len(processing_times)
            avg_time = sum(processing_times) / total_requests
            min_time = processing_times[0]
            max_time = processing_times[-1]
            p50 = processing_times[int(total_requests * 0.5)]
            p95 = processing_times[int(total_requests * 0.95)] if total_requests >= 20 else max_time
        else:
            total_requests = 0
            avg_time = min_time = max_time = p50 = p95 = 0

        # 시간대별 분포 (최근 24시간)
        by_hour = []
        for i in range(min(hours, 24)):
            hour_start = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=i)
            hour_end = hour_start + timedelta(hours=1)

            hour_requests = [
                r for r in completed_requests
                if r.processed_at and hour_start <= r.processed_at < hour_end
            ]

            hour_times = []
            for req in hour_requests:
                if req.processed_at and req.requested_at:
                    seconds = (req.processed_at - req.requested_at).total_seconds()
                    hour_times.append(seconds)

            by_hour.append({
                "hour": hour_start.strftime("%H:00"),
                "count": len(hour_requests),
                "avg_time": round(sum(hour_times) / len(hour_times), 1) if hour_times else 0,
            })

        by_hour.reverse()  # 시간순 정렬

        # 최근 느린 요청 (처리 시간 상위 10개)
        slow_requests = []
        if completed_requests:
            sorted_by_time = sorted(
                completed_requests,
                key=lambda r: (r.processed_at - r.requested_at).total_seconds() if r.processed_at and r.requested_at else 0,
                reverse=True
            )[:10]

            for req in sorted_by_time:
                if req.processed_at and req.requested_at:
                    slow_requests.append({
                        "id": req.id,
                        "caller_type": req.caller_type,
                        "caller_id": req.caller_id,
                        "processing_time": round((req.processed_at - req.requested_at).total_seconds(), 1),
                        "requested_at": req.requested_at.isoformat(),
                    })

        return {
            "period_hours": hours,
            "llm_stats": {
                "total_requests": total_requests,
                "failed_count": failed_count,
                "avg_processing_time": round(avg_time, 1),
                "min_time": round(min_time, 1),
                "max_time": round(max_time, 1),
                "p50": round(p50, 1),
                "p95": round(p95, 1),
            },
            "by_hour": by_hour,
            "slow_requests": slow_requests,
        }
