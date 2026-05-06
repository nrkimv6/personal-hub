"""LLM Service - Facade: 하위 Domain Service들을 조합하여 기존 공개 API를 유지."""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus

logger = logging.getLogger("claude_worker.llm_service")

# 하위호환 상수/함수 — 외부 참조자(test_llm_classifier_service.py 등)가 사용
HEARTBEAT_WARNING_THRESHOLD = 120   # 2분: warning 상태
HEARTBEAT_UNHEALTHY_THRESHOLD = 600  # 10분: unhealthy 상태
QUEUE_PRIORITY = ["system", "utility"]
QUOTA_PAUSE_DEFAULT_MS = 6 * 60 * 60 * 1000

# 하위호환 re-export — test_quota_pause.py 등이 참조
from app.modules.claude_worker.services.executors.claude_executor import (
    _parse_quota_retry_ms,
)


class LLMService:
    """범용 LLM 서비스.

    Claude CLI를 subprocess로 호출하여 LLM 작업을 처리합니다.
    """

    def __init__(self, db: Session):
        self.db = db
        from app.modules.claude_worker.services.repositories import (
            LLMRequestRepository,
            LLMWorkerRepository,
        )
        from app.modules.claude_worker.services.llm_config_service import LLMConfigService
        from app.modules.claude_worker.services.llm_queue_service import LLMQueueService
        from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
        from app.modules.claude_worker.services.llm_worker_service import LLMWorkerService
        from app.modules.claude_worker.services.llm_request_crud_service import LLMRequestCrudService
        from app.modules.claude_worker.services.llm_stats_service import LLMStatsService

        self._repo = LLMRequestRepository(db)
        self._worker_repo = LLMWorkerRepository(db)
        self._config_svc = LLMConfigService()
        self._queue_svc = LLMQueueService(self._repo, self._config_svc, db)
        self._quota_svc = LLMQuotaService(self._repo, self._worker_repo, db)
        self._worker_svc = LLMWorkerService(self._worker_repo, db)
        self._crud_svc = LLMRequestCrudService(self._repo, db)
        self._stats_svc = LLMStatsService(self._repo, db)

    # ========== 기본값 관리 (→ LLMConfigService 위임) ==========

    @staticmethod
    def get_supported_providers() -> List[str]:
        from app.modules.claude_worker.services.llm_config_service import LLMConfigService
        return LLMConfigService.get_supported_providers()

    @staticmethod
    def get_known_caller_types() -> List[str]:
        from app.modules.claude_worker.services.llm_config_service import LLMConfigService
        return LLMConfigService.get_known_caller_types()

    @staticmethod
    def _normalize_provider(value: Optional[str]) -> Optional[str]:
        from app.modules.claude_worker.services.llm_config_service import LLMConfigService
        return LLMConfigService._normalize_provider(value)

    @staticmethod
    def _normalize_model(value: Optional[str]) -> Optional[str]:
        from app.modules.claude_worker.services.llm_config_service import LLMConfigService
        return LLMConfigService._normalize_model(value)

    @classmethod
    def _default_defaults_payload(cls) -> Dict[str, Any]:
        from app.modules.claude_worker.services.llm_config_service import LLMConfigService
        return LLMConfigService._default_defaults_payload()

    def _sanitize_defaults_payload(self, raw: Any) -> Dict[str, Any]:
        return self._config_svc._sanitize_defaults_payload(raw)

    def load_llm_defaults(self) -> Dict[str, Any]:
        return self._config_svc.load_llm_defaults()

    def save_llm_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._config_svc.save_llm_defaults(payload)

    def resolve_provider_model(
        self,
        caller_type: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[str, str]:
        return self._config_svc.resolve_provider_model(caller_type, provider, model)

    # ========== 큐 관리 (→ LLMQueueService 위임) ==========

    def enqueue(self, caller_type, caller_id, prompt, requested_by="unknown", request_source=None, provider=None, model=None, cli_options=None, queue_name="utility", mode="single") -> LLMRequest:
        return self._queue_svc.enqueue(caller_type, caller_id, prompt, requested_by, request_source, provider, model, cli_options, queue_name, mode)

    def update_chat_session(self, request_id: int, chat_session_id: str) -> None:
        return self._queue_svc.update_chat_session(request_id, chat_session_id)

    def get_result(self, caller_type: str, caller_id: str) -> Optional[LLMRequest]:
        return self._queue_svc.get_result(caller_type, caller_id)

    def get_pending_request(self) -> Optional[LLMRequest]:
        return self._queue_svc.get_pending_request()

    def get_next_request(self, exclude_providers: list = None) -> Optional[LLMRequest]:
        return self._queue_svc.get_next_request(exclude_providers)

    def get_queue_stats(self) -> dict:
        return self._queue_svc.get_queue_stats()

    def get_pending_count(self) -> int:
        return self._queue_svc.get_pending_count()

    def mark_processing(self, request_id: int) -> None:
        return self._queue_svc.mark_processing(request_id)

    def mark_completed(self, request_id: int, result: dict, raw_response: str = "", claude_session_id: Optional[str] = None) -> None:
        return self._queue_svc.mark_completed(request_id, result, raw_response, claude_session_id)

    def prepare_completed(self, request_id: int, result: dict, raw_response: str = "", claude_session_id: Optional[str] = None):
        return self._queue_svc.prepare_completed(request_id, result, raw_response, claude_session_id)

    def mark_failed(self, request_id: int, error_message: str, raw_response: str = "") -> None:
        return self._queue_svc.mark_failed(request_id, error_message, raw_response)

    def reset_to_pending(self, request_id: int, reason: str | None = None) -> bool:
        return self._queue_svc.reset_to_pending(request_id, reason)

    # ========== Quota 상태 관리 (→ LLMQuotaService 위임) ==========

    def set_provider_quota_pause(self, provider: str, retry_after_ms: int, reason: str = "") -> "datetime":
        return self._quota_svc.set_provider_quota_pause(provider, retry_after_ms, reason)

    def set_profile_quota_pause(self, provider: str, profile_name: str, retry_after_ms: int, reason: str = "") -> "datetime":
        return self._quota_svc.set_profile_quota_pause(provider, profile_name, retry_after_ms, reason)

    def get_provider_quota_pause(self, provider: str) -> Optional["datetime"]:
        return self._quota_svc.get_provider_quota_pause(provider)

    def get_profile_quota_pause(self, provider: str, profile_name: str) -> Optional["datetime"]:
        return self._quota_svc.get_profile_quota_pause(provider, profile_name)

    def is_paused(self, provider: str, profile_name: Optional[str] = None) -> bool:
        return self._quota_svc.is_paused(provider, profile_name)

    def get_provider_quota_pause_detail(self, provider: str) -> dict:
        return self._quota_svc.get_provider_quota_pause_detail(provider)

    def clear_provider_quota_pause(self, provider: str) -> bool:
        return self._quota_svc.clear_provider_quota_pause(provider)

    def clear_profile_quota_pause(self, provider: str, profile_name: str) -> bool:
        return self._quota_svc.clear_profile_quota_pause(provider, profile_name)

    def reset_quota_failed_requests(self, provider: str) -> int:
        return self._quota_svc.reset_quota_failed_requests(provider)

    def get_blocked_pending_count(self, provider: str) -> int:
        return self._quota_svc.get_blocked_pending_count(provider)

    # ========== Claude 실행 ==========

    def execute_claude(self, prompt: str, model: str = "", timeout: int = 120, parse_json: bool = True, enable_tools: bool = False, cli_options: dict = None, profile=None) -> dict:
        """Claude CLI 실행 (동기). → ClaudeExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch(
            "claude", prompt,
            model=model, timeout=timeout, parse_json=parse_json,
            enable_tools=enable_tools, cli_options=cli_options, profile=profile,
        )

    def execute_gemini(self, prompt: str, model: str = "", timeout: int = 120, parse_json: bool = True, enable_tools: bool = False, cli_options: dict = None, profile=None) -> dict:
        """Gemini CLI 실행 (동기). → GeminiExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch(
            "gemini", prompt,
            model=model, timeout=timeout, parse_json=parse_json,
            enable_tools=enable_tools, cli_options=cli_options, profile=profile,
        )

    def execute_llm(
        self,
        prompt: str,
        provider: str = "claude",
        model: str = "",
        timeout: int = 120,
        parse_json: bool = True,
        enable_tools: bool = False,
        cli_options: dict = None,
        profile=None,
    ) -> dict:
        """LLM 통합 실행. → ExecutionDispatcher.dispatch 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch(
            provider, prompt,
            model=model, timeout=timeout, parse_json=parse_json,
            enable_tools=enable_tools, cli_options=cli_options, profile=profile,
        )

    def execute_codex(self, prompt: str, model: str = "", timeout: int = 120) -> dict:
        """Codex CLI 실행. → CodexExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch("codex", prompt, model=model, timeout=timeout)

    def execute_cc_codex(self, prompt: str, model: str = "", timeout: int = 120) -> dict:
        """CC-Codex CLI 실행. → CCCodexExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch("cc-codex", prompt, model=model, timeout=timeout)

    # ========== 워커 상태 관리 (→ LLMWorkerService 위임) ==========

    def register_worker(self, worker_id: str, pid: int) -> LLMWorkerStatus:
        return self._worker_svc.register_worker(worker_id, pid)

    def update_heartbeat(self, worker_id: str) -> None:
        return self._worker_svc.update_heartbeat(worker_id)

    def update_worker_state(self, worker_id: str, state: str, request_id: int = None) -> None:
        return self._worker_svc.update_worker_state(worker_id, state, request_id)

    def increment_processed(self, worker_id: str) -> None:
        return self._worker_svc.increment_processed(worker_id)

    def increment_error(self, worker_id: str) -> None:
        return self._worker_svc.increment_error(worker_id)

    def mark_worker_dead(self, worker_id: str) -> None:
        return self._worker_svc.mark_worker_dead(worker_id)

    def get_worker_status(self) -> Optional[LLMWorkerStatus]:
        return self._worker_svc.get_worker_status()

    def check_worker_health(self) -> dict:
        return self._worker_svc.check_worker_health()

    def get_bootstrap_data(
        self,
        status=None,
        caller_type=None,
        requested_by=None,
        include_deleted=False,
        page=1,
        page_size=20,
        queue_name=None,
    ) -> Dict[str, Any]:
        """LLM /llm 화면 초기 진입용 묶음 데이터 조회."""
        request_list = self.list_requests(
            status=status,
            caller_type=caller_type,
            requested_by=requested_by,
            include_deleted=include_deleted,
            page=page,
            page_size=page_size,
            queue_name=queue_name,
        )
        return {
            "list": request_list,
            "stats": self.get_stats(),
            "queue_stats": self.get_queue_stats(),
            "worker_status": self.check_worker_health(),
        }

    def get_scheduler_runtime_summary(self, recent_limit: int = 50) -> Dict[str, Any]:
        """최근 scheduler 요청의 실제 provider/model 집계."""
        rows = (
            self.db.query(LLMRequest)
            .filter(LLMRequest.requested_by == "scheduler")
            .order_by(LLMRequest.requested_at.desc(), LLMRequest.id.desc())
            .limit(max(1, recent_limit))
            .all()
        )

        provider_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        caller_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        latest_request = None

        for req in rows:
            provider = (req.provider or "claude").strip() or "claude"
            model = (req.model or "").strip()
            provider_key = (provider, model)
            provider_entry = provider_map.setdefault(
                provider_key,
                {
                    "provider": provider,
                    "model": model,
                    "count": 0,
                    "latest_requested_at": None,
                    "caller_types": set(),
                },
            )
            provider_entry["count"] += 1
            provider_entry["caller_types"].add(req.caller_type)
            if provider_entry["latest_requested_at"] is None or (
                req.requested_at and provider_entry["latest_requested_at"] < req.requested_at
            ):
                provider_entry["latest_requested_at"] = req.requested_at

            caller_key = (req.caller_type, provider, model)
            caller_entry = caller_map.setdefault(
                caller_key,
                {
                    "caller_type": req.caller_type,
                    "provider": provider,
                    "model": model,
                    "count": 0,
                    "latest_requested_at": None,
                },
            )
            caller_entry["count"] += 1
            if caller_entry["latest_requested_at"] is None or (
                req.requested_at and caller_entry["latest_requested_at"] < req.requested_at
            ):
                caller_entry["latest_requested_at"] = req.requested_at

            if latest_request is None:
                latest_request = req

        provider_summary = [
            {
                **entry,
                "caller_types": sorted(entry["caller_types"]),
            }
            for entry in sorted(
                provider_map.values(),
                key=lambda item: (-item["count"], item["provider"], item["model"]),
            )
        ]
        caller_summary = sorted(
            caller_map.values(),
            key=lambda item: (-item["count"], item["caller_type"], item["provider"], item["model"]),
        )

        return {
            "recent_limit": recent_limit,
            "total_requests": len(rows),
            "provider_summary": provider_summary,
            "caller_summary": caller_summary,
            "latest_request": (
                {
                    "id": latest_request.id,
                    "caller_type": latest_request.caller_type,
                    "caller_id": latest_request.caller_id,
                    "provider": latest_request.provider or "claude",
                    "model": latest_request.model or "",
                    "requested_at": latest_request.requested_at,
                    "requested_by": latest_request.requested_by,
                    "request_source": latest_request.request_source,
                }
                if latest_request
                else None
            ),
        }

    # ========== 요청 관리 (→ LLMRequestCrudService 위임) ==========

    def list_requests(self, status=None, caller_type=None, requested_by=None, include_deleted=False, page=1, page_size=20, queue_name=None) -> dict:
        return self._crud_svc.list_requests(status, caller_type, requested_by, include_deleted, page, page_size, queue_name)

    def get_request_by_id(self, request_id: int) -> Optional[LLMRequest]:
        return self._crud_svc.get_request_by_id(request_id)

    def update_request(self, request_id: int, cli_options=None, prompt=None):
        return self._crud_svc.update_request(request_id, cli_options, prompt)

    def cancel_request(self, request_id: int) -> bool:
        return self._crud_svc.cancel_request(request_id)

    def delete_request(self, request_id: int, hard_delete: bool = False) -> bool:
        return self._crud_svc.delete_request(request_id, hard_delete)

    def batch_retry(self, request_ids: List[int]) -> dict:
        return self._crud_svc.batch_retry(request_ids)

    def batch_delete(self, request_ids: List[int], hard_delete: bool = False) -> dict:
        return self._crud_svc.batch_delete(request_ids, hard_delete)

    # ========== 이력 및 통계 + Cleanup + 그룹화 (→ LLMStatsService 위임) ==========

    def get_history_stats(self, start_date: date = None, end_date: date = None, group_by: str = "day") -> dict:
        return self._stats_svc.get_history_stats(start_date, end_date, group_by)

    def get_caller_stats(self) -> dict:
        return self._stats_svc.get_caller_stats()

    STALE_PROCESSING_TIMEOUT_MINUTES = 65
    HISTORY_RETENTION_DAYS = 7

    def cleanup_stale_processing(self, timeout_minutes: int = None) -> int:
        return self._stats_svc.cleanup_stale_processing(timeout_minutes)

    def cleanup_old_history(self, days: int = None, hard_delete: bool = True) -> int:
        return self._stats_svc.cleanup_old_history(days, hard_delete)

    def run_cleanup(self) -> dict:
        return self._stats_svc.run_cleanup()

    def _build_caller_aggregate_query(self, caller_type: str = None):
        return self._stats_svc._build_caller_aggregate_query(caller_type)

    def list_requests_grouped_by_caller(self, caller_type=None, only_without_success=False, page=1, page_size=50) -> dict:
        return self._stats_svc.list_requests_grouped_by_caller(caller_type, only_without_success, page, page_size)

    def retry_failed_callers_without_success(self, caller_type: str = None) -> dict:
        return self._stats_svc.retry_failed_callers_without_success(caller_type)

    def get_stats(self) -> dict:
        return self._stats_svc.get_stats()

    def get_performance_stats(self, hours: int = 24) -> dict:
        return self._stats_svc.get_performance_stats(hours)
