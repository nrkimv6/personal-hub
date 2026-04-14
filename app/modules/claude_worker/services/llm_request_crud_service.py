"""LLMRequestCrudService — LLM 요청 CRUD + 일괄 처리.

DB 접근: LLMRequestRepository 경유.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger("claude_worker.llm_request_crud_service")


class LLMRequestCrudService:
    """LLM 요청 CRUD + 일괄 처리."""

    def __init__(self, repo, db: Session):
        self._repo = repo
        self.db = db

    def list_requests(
        self,
        status: str = None,
        caller_type: str = None,
        requested_by: str = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 20,
        queue_name: str = None,
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
            queue_name: 큐 이름 필터 ('utility' 또는 'system')

        Returns:
            {"items": [...], "total": n, "page": n, "page_size": n, "pages": n}
        """
        items, total = self._repo.list_with_filters(
            status=status,
            caller_type=caller_type,
            requested_by=requested_by,
            include_deleted=include_deleted,
            page=page,
            page_size=page_size,
            queue_name=queue_name,
        )
        pages = (total + page_size - 1) // page_size

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_request_by_id(self, request_id: int) -> Optional[LLMRequest]:
        """단일 요청 조회."""
        return self._repo.get_by_id(request_id)

    def update_request(self, request_id: int, cli_options=None, prompt=None):
        """pending/failed 요청의 cli_options 또는 prompt 갱신."""
        request = self._repo.get_by_id(request_id)
        if not request or request.status not in ("pending", "failed"):
            return None
        if cli_options is not None:
            request.cli_options = json.dumps(cli_options)
        if prompt is not None:
            request.prompt = prompt
        self.db.commit()
        self.db.refresh(request)
        return request

    def cancel_request(self, request_id: int) -> bool:
        """pending 요청 취소.

        Returns:
            True if cancelled, False if not found or not pending
        """
        request = self._repo.get_by_id(request_id)
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
        request = self._repo.get_by_id(request_id)
        if not request:
            return False

        if hard_delete:
            self._repo.delete(request)
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
            request = self._repo.get_by_id(request_id)
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
