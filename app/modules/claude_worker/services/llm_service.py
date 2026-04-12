"""LLM Service - 범용 LLM 실행 서비스."""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus
from app.shared.io import read_json, write_json_atomic
from app.modules.claude_worker.services import provider_registry
from app.shared.llm_registry import (
    CALLER_TYPE_TO_STEP,
    NoAvailableModelError,
    pick_model,
    report_quota,
)

logger = logging.getLogger("claude_worker.llm_service")

# 워커 헬스체크 임계값 (초)
HEARTBEAT_WARNING_THRESHOLD = 120  # 2분: warning 상태
HEARTBEAT_UNHEALTHY_THRESHOLD = 600  # 10분: unhealthy 상태

# 큐 우선순위 — 앞에 있을수록 먼저 처리
QUEUE_PRIORITY = ["system", "utility"]

# Quota pause 기본 대기 시간 (ms) — 6시간
QUOTA_PAUSE_DEFAULT_MS = 6 * 60 * 60 * 1000

# LLM 기본값 설정 파일
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LLM_DEFAULTS_FILE = PROJECT_ROOT / "data" / "llm_defaults.json"
LEGACY_LLM_DEFAULTS_FILE = Path("data/llm_defaults.json")
LLM_DEFAULTS_FILE = DEFAULT_LLM_DEFAULTS_FILE

# provider 관련 상수는 provider_registry 에서 관리 (shadow 상수 제거됨)

# 설정 UI 노출용 caller_type 목록 (코드 기준)
KNOWN_CALLER_TYPES = [
    "instagram",
    "universal_crawl",
    "image_classify",
    "event_import",
    "report",
    "pytest_fix",
    "dev_runner",
    "git_repos",
    "topic_extract",
    "writing",
    "writing_generate",
    "writing_refine",
    "plan_archive_analyze",
    "plan_recurrence_check",
    "plan_recurrence_suggest",
]


def _normalize_path(path: Path) -> str:
    absolute = path if path.is_absolute() else (Path.cwd() / path)
    return os.path.normcase(os.path.normpath(str(absolute)))


def _same_path(lhs: Path, rhs: Path) -> bool:
    return _normalize_path(lhs) == _normalize_path(rhs)


def _resolve_llm_defaults_path() -> Path:
    """테스트 monkeypatch seam(LLM_DEFAULTS_FILE)을 유지하면서 경로를 해석."""
    configured = Path(LLM_DEFAULTS_FILE)
    if configured.is_absolute():
        return configured
    return PROJECT_ROOT / configured


def _is_default_llm_defaults_path(path: Path) -> bool:
    return _same_path(path, DEFAULT_LLM_DEFAULTS_FILE)


def _migrate_legacy_llm_defaults_if_needed(target_path: Path) -> None:
    if not _is_default_llm_defaults_path(target_path):
        logger.debug(f"[llm-defaults] 주입 경로 감지: 레거시 마이그레이션 스킵 ({target_path})")
        return
    if target_path.exists():
        logger.debug(f"[llm-defaults] 기본 경로 파일 존재: 레거시 마이그레이션 스킵 ({target_path})")
        return

    legacy_path = (
        LEGACY_LLM_DEFAULTS_FILE
        if LEGACY_LLM_DEFAULTS_FILE.is_absolute()
        else (Path.cwd() / LEGACY_LLM_DEFAULTS_FILE)
    )
    if not legacy_path.exists():
        logger.debug(f"[llm-defaults] 레거시 파일 없음: 마이그레이션 스킵 ({legacy_path})")
        return
    if _same_path(legacy_path, target_path):
        logger.debug(f"[llm-defaults] 레거시/기본 경로 동일: 마이그레이션 스킵 ({target_path})")
        return

    legacy_payload = read_json(legacy_path, default=None)
    if not isinstance(legacy_payload, dict):
        logger.warning(f"[llm-defaults] 레거시 설정 파일 손상: 마이그레이션 스킵 ({legacy_path})")
        return

    write_json_atomic(target_path, legacy_payload)
    logger.info(f"[llm-defaults] 레거시 설정 마이그레이션 완료: {legacy_path} -> {target_path}")


def _parse_quota_retry_ms(text: str) -> Optional[int]:
    """stderr/stdout에서 quota 재시도 대기 시간(ms) 파싱.

    1순위: retryDelayMs: 숫자 정규식 파싱
    2순위: reset after Xh Ym Zs 텍스트 파싱
    미감지: None 반환
    """
    if not text:
        return None

    # 1순위: retryDelayMs 파싱
    m = re.search(r"retryDelayMs:\s*([\d.]+)", text)
    if m:
        return int(float(m.group(1)))

    # 2순위: "reset after Xh Ym Zs" 파싱
    m = re.search(r"reset after (\d+)h(\d+)m(\d+)s", text)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (h * 3600 + mn * 60 + s) * 1000

    return None


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
        self._repo = LLMRequestRepository(db)
        self._worker_repo = LLMWorkerRepository(db)

    # ========== 기본값 관리 ==========

    @staticmethod
    def get_supported_providers() -> List[str]:
        return sorted(p.key for p in provider_registry.list_enabled())

    @staticmethod
    def get_known_caller_types() -> List[str]:
        return sorted(KNOWN_CALLER_TYPES)

    @staticmethod
    def _normalize_provider(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_model(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        normalized = value.strip()
        # 빈 문자열은 "미지정"으로 간주
        return normalized or None

    @classmethod
    def _default_defaults_payload(cls) -> Dict[str, Any]:
        return {
            "global_default": {"provider": "claude", "model": ""},
            "caller_defaults": {},
        }

    def _sanitize_defaults_payload(self, raw: Any) -> Dict[str, Any]:
        payload = self._default_defaults_payload()
        if not isinstance(raw, dict):
            return payload

        raw_global = raw.get("global_default")
        if isinstance(raw_global, dict):
            provider = self._normalize_provider(raw_global.get("provider")) or "claude"
            if not provider_registry.is_supported(provider):
                provider = "claude"
            model = raw_global.get("model")
            if model is None:
                model = ""
            if not isinstance(model, str):
                model = str(model)
            payload["global_default"] = {
                "provider": provider,
                "model": model.strip(),
            }

        raw_callers = raw.get("caller_defaults")
        if not isinstance(raw_callers, dict):
            return payload

        caller_defaults: Dict[str, Dict[str, str]] = {}
        for caller_type, config in raw_callers.items():
            caller = str(caller_type).strip()
            if not caller or not isinstance(config, dict):
                continue

            provider = self._normalize_provider(config.get("provider"))
            if provider is None or not provider_registry.is_supported(provider):
                continue

            model = config.get("model")
            if model is None:
                model = ""
            if not isinstance(model, str):
                model = str(model)

            caller_defaults[caller] = {
                "provider": provider,
                "model": model.strip(),
            }

        payload["caller_defaults"] = caller_defaults
        return payload

    def load_llm_defaults(self) -> Dict[str, Any]:
        target_path = _resolve_llm_defaults_path()
        _migrate_legacy_llm_defaults_if_needed(target_path)

        if not target_path.exists():
            return self._default_defaults_payload()

        try:
            data = read_json(target_path, default=None)
            if not isinstance(data, dict):
                raise ValueError("llm defaults payload is not an object")
            return self._sanitize_defaults_payload(data)
        except Exception:
            logger.warning(f"[llm-defaults] 설정 파일 읽기 실패, 기본값 사용: {target_path}")
            return self._default_defaults_payload()

    def save_llm_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        defaults = self._sanitize_defaults_payload(payload)

        # 저장 요청에서 caller_defaults를 명시적으로 보낸 경우 provider 공백 항목 제거
        if isinstance(payload, dict) and isinstance(payload.get("caller_defaults"), dict):
            requested = payload.get("caller_defaults", {})
            caller_defaults: Dict[str, Dict[str, str]] = {}
            for caller_type, config in requested.items():
                caller = str(caller_type).strip()
                if not caller:
                    continue
                if not isinstance(config, dict):
                    continue
                provider = self._normalize_provider(config.get("provider"))
                if provider is None:
                    # provider가 비어 있으면 caller override 삭제(=global fallback)
                    continue
                if not provider_registry.is_supported(provider):
                    raise ValueError(f"지원되지 않는 provider: {provider}")
                model = config.get("model")
                if model is None:
                    model = ""
                if not isinstance(model, str):
                    model = str(model)
                caller_defaults[caller] = {
                    "provider": provider,
                    "model": model.strip(),
                }
            defaults["caller_defaults"] = caller_defaults

        target_path = _resolve_llm_defaults_path()
        write_json_atomic(target_path, defaults)
        return defaults

    def resolve_provider_model(
        self,
        caller_type: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[str, str]:
        """우선순위 1-D:
        1순위: 호출자 명시 provider/model → 즉시 반환 (quota 확인 없음)
        2순위: caller_defaults pin → 반환. oneshot 모델 pin 시 WARN
        3순위: registry picker (step 기반) — openai 반환 시 재-pick (O-2)
        4순위: global_default (quota 차단이면 에러 전파)
        """
        defaults = self.load_llm_defaults()
        global_default = defaults.get("global_default", {})
        caller_defaults = defaults.get("caller_defaults", {})
        caller_default = caller_defaults.get(caller_type, {}) if isinstance(caller_defaults, dict) else {}

        # ── 1순위: 호출자 명시 ────────────────────────────────────────────────
        explicit_provider = self._normalize_provider(provider)
        explicit_model = self._normalize_model(model)
        if explicit_provider is not None and explicit_model is not None:
            return explicit_provider, explicit_model

        # ── 2순위: caller pin (명시 provider OR model 부분 지정 포함) ──────────
        pin_provider = self._normalize_provider(caller_default.get("provider"))
        pin_model = self._normalize_model(caller_default.get("model"))
        if pin_provider and pin_model:
            # O-5: pin된 모델이 oneshot 후보와 일치하면 WARN
            try:
                from app.shared.llm_registry import load_registry
                registry = load_registry()
                for candidates in registry.values():
                    for cand in candidates:
                        if cand.oneshot and cand.provider == pin_provider and cand.model == pin_model:
                            logger.warning(
                                f"[resolve] caller_pin {pin_provider}/{pin_model}이 "
                                "oneshot 전용 registry 모델과 일치. 핑퐁 경로에서 호출됩니다."
                            )
                            break
            except Exception:
                pass
            return pin_provider, pin_model

        # ── 3순위: registry picker ───────────────────────────────────────────
        step = CALLER_TYPE_TO_STEP.get(caller_type)
        if step:
            try:
                picked_provider, picked_model = pick_model(step, oneshot=False)
                # O-2: 실행 불가 provider(quota_pause=False) → exclude 재-pick
                _quota_providers = set(provider_registry.get_quota_providers())
                if picked_provider not in _quota_providers:
                    logger.warning(
                        f"[resolve] picker가 {picked_provider}/{picked_model} 반환 "
                        f"(실행 불가, quota_providers={_quota_providers}). 재-pick."
                    )
                    _all_providers = {p.key for p in provider_registry.list_enabled()}
                    picked_provider, picked_model = pick_model(
                        step, oneshot=False, exclude_providers=_all_providers - _quota_providers
                    )
                return picked_provider, picked_model
            except NoAvailableModelError as e:
                logger.error(f"[resolve] picker 실패: {e}. global_default로 fallback.")
            except Exception as e:
                logger.error(f"[resolve] picker 예외: {e}. global_default로 fallback.")

        # ── 4순위: global_default ─────────────────────────────────────────────
        gd_provider = self._normalize_provider(global_default.get("provider")) or "claude"
        gd_model = self._normalize_model(global_default.get("model")) or ""
        # 4순위도 quota 재확인 (1-E step 3)
        if gd_provider in set(provider_registry.get_quota_providers()):
            try:
                from app.shared.llm_registry import load_quota_state
                state = load_quota_state()
                key = f"{gd_provider}/{gd_model}" if gd_model else None
                if key and key in state:
                    quota = state[key]
                    from app.shared.llm_registry import _now_kst
                    now = _now_kst()
                    if quota.is_in_cooldown(now) or quota.is_weekly_exhausted():
                        raise NoAvailableModelError(
                            caller_type,
                            f"global_default {gd_provider}/{gd_model}도 quota 차단. 수동 보고 필요."
                        )
            except NoAvailableModelError:
                raise
            except Exception:
                pass  # quota 조회 실패 시 global_default 그대로 사용
        return gd_provider, gd_model

    # ========== 큐 관리 ==========

    def enqueue(
        self,
        caller_type: str,
        caller_id: str,
        prompt: str,
        requested_by: str = "unknown",
        request_source: str = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        cli_options: dict = None,
        queue_name: str = "utility",
        mode: str = "single",
    ) -> LLMRequest:
        """요청을 큐에 추가 (non-blocking).

        Args:
            caller_type: 호출자 타입 (예: 'instagram')
            caller_id: 호출자 측 ID (예: post_id)
            prompt: LLM에 전달할 프롬프트
            requested_by: 요청자 (예: 'api', 'scheduler', 'manual')
            request_source: 요청 출처 (예: 'instagram_crawl', 'manual_test')
            provider: LLM Provider (미지정 시 caller/global 설정 fallback)
            model: 모델명 (미지정 시 caller/global 설정 fallback)
            cli_options: CLI 옵션 dict (output_format, json_schema, allowed_tools, use_prompt_flag 등)
            queue_name: 큐 이름 ('utility' 또는 'system', 기본값: 'utility')

        Returns:
            생성된 LLMRequest
        """
        # 중복 pending 요청 확인 (같은 queue_name 내에서만)
        existing = self._repo.find_existing_pending(caller_type, caller_id, queue_name)

        if existing:
            logger.debug(f"이미 pending 요청 존재: {caller_type}:{caller_id} (queue={queue_name})")
            return existing

        resolved_provider, resolved_model = self.resolve_provider_model(
            caller_type=caller_type,
            provider=provider,
            model=model,
        )

        request = LLMRequest(
            caller_type=caller_type,
            caller_id=caller_id,
            prompt=prompt,
            status="pending",
            requested_by=requested_by,
            request_source=request_source,
            provider=resolved_provider,
            model=resolved_model,
            cli_options=json.dumps(cli_options, ensure_ascii=False) if cli_options else None,
            queue_name=queue_name,
            mode=mode,
        )
        self._repo.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"LLM 요청 생성: id={request.id}, caller={caller_type}:{caller_id}, queue={queue_name}, mode={mode}, by={requested_by}")
        return request

    def update_chat_session(self, request_id: int, chat_session_id: str) -> None:
        """chat_session_id DB 업데이트."""
        request = self._repo.get_by_id(request_id)
        if request:
            request.chat_session_id = chat_session_id
            self.db.commit()

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
        return self._repo.find_latest_by_caller(caller_type, caller_id)

    def get_pending_request(self) -> Optional[LLMRequest]:
        """가장 오래된 pending 요청 조회 (워커용, 레거시 — get_next_request() 사용 권장).

        Returns:
            pending 요청 또는 None
        """
        return self._repo.find_oldest_pending()

    def get_next_request(self, exclude_providers: list = None) -> Optional[LLMRequest]:
        """우선순위 기반으로 다음 처리할 요청 조회 (워커용).

        QUEUE_PRIORITY 순서로 각 큐를 확인하여 가장 오래된 pending 요청 반환.
        현재 우선순위: system → utility

        Args:
            exclude_providers: 제외할 provider 목록 (예: ["gemini"])

        Returns:
            pending 요청 또는 None
        """
        if exclude_providers is None:
            exclude_providers = []

        for queue in QUEUE_PRIORITY:
            request = self._repo.find_next_pending_in_queue(queue, exclude_providers)
            if request:
                return request
        return None

    # ========== Quota 상태 관리 ==========

    def set_provider_quota_pause(self, provider: str, retry_after_ms: int, reason: str = "") -> "datetime":
        """provider quota pause 상태 DB 저장.

        모든 활성 worker_status 레코드에 저장 (quota는 시스템 전역 상태).

        Returns:
            paused_until datetime
        """
        paused_until = datetime.now() + timedelta(milliseconds=retry_after_ms)

        statuses = self._worker_repo.find_all()
        for status in statuses:
            status.quota_paused_provider = provider
            status.quota_paused_until = paused_until
            status.quota_pause_reason = reason

        self.db.commit()
        return paused_until

    def get_provider_quota_pause(self, provider: str) -> Optional["datetime"]:
        """provider quota pause 만료 시각 조회.

        만료되지 않은 경우 paused_until 반환, 만료/없으면 None.
        """
        status = self._worker_repo.find_quota_pause(provider)
        if status and status.quota_paused_until:
            if status.quota_paused_until > datetime.now():
                return status.quota_paused_until
        return None

    def clear_provider_quota_pause(self, provider: str) -> bool:
        """provider quota pause 수동 해제."""
        statuses = self._worker_repo.find_by_quota_provider(provider)
        if not statuses:
            return False
        for status in statuses:
            status.quota_paused_provider = None
            status.quota_paused_until = None
            status.quota_pause_reason = None
        self.db.commit()
        return True

    def reset_quota_failed_requests(self, provider: str) -> int:
        """quota 에러로 실패한 요청을 pending으로 전환.

        Returns:
            전환된 요청 수
        """
        quota_messages = ["%TerminalQuotaError%", "%exhausted your capacity%"]
        targets = self._repo.find_quota_failed(provider)
        count = 0
        for req in targets:
            req.status = "pending"
            req.error_message = None
            req.result = None
            req.raw_response = None
            req.processed_at = None
            count += 1
        if count:
            self.db.commit()
        return count

    def get_blocked_pending_count(self, provider: str) -> int:
        """pause 중인 provider로 막힌 pending 요청 수 조회."""
        return self._repo.count_blocked_by_provider(provider)

    def get_queue_stats(self) -> dict:
        """큐별 상태 카운트 통계.

        Returns:
            {"system": {"pending": N, "processing": N, ...}, "utility": {...}}
        """
        rows = self._repo.get_queue_stats_rows()

        # 모든 큐에 대해 기본값 0으로 초기화
        result: dict = {}
        for queue in QUEUE_PRIORITY:
            result[queue] = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}

        for row in rows:
            queue = row.queue_name or "utility"
            if queue not in result:
                result[queue] = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}
            status = row.status
            if status in result[queue]:
                result[queue][status] = row.cnt

        return result

    def get_pending_count(self) -> int:
        """Pending 요청 수 조회."""
        return self._repo.count_pending()

    # ========== 상태 변경 ==========

    def mark_processing(self, request_id: int) -> None:
        """요청을 processing 상태로 변경."""
        request = self._repo.get_by_id(request_id)
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
        request = self._repo.get_by_id(request_id)
        if request:
            request.status = "completed"
            request.processed_at = datetime.now()
            request.result = json.dumps(result, ensure_ascii=False)
            request.raw_response = raw_response
            request.error_message = None
            self.db.commit()

    def mark_failed(self, request_id: int, error_message: str, raw_response: str = "") -> None:
        """요청을 failed 상태로 변경."""
        request = self._repo.get_by_id(request_id)
        if request:
            request.status = "failed"
            request.processed_at = datetime.now()
            request.error_message = error_message
            if raw_response:
                request.raw_response = raw_response
            request.retry_count += 1
            self.db.commit()

    def reset_to_pending(self, request_id: int) -> bool:
        """요청을 pending으로 리셋 (재시도용).

        failed 상태인 요청만 pending으로 변경할 수 있습니다.
        completed 상태는 이미 처리 완료되었으므로 리셋 불가.
        """
        request = self._repo.get_by_id(request_id)
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

    def execute_claude(self, prompt: str, model: str = "", timeout: int = 120, parse_json: bool = True, enable_tools: bool = False, cli_options: dict = None) -> dict:
        """Claude CLI 실행 (동기). → ClaudeExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch(
            "claude", prompt,
            model=model, timeout=timeout, parse_json=parse_json,
            enable_tools=enable_tools, cli_options=cli_options,
        )

    def execute_gemini(self, prompt: str, model: str = "", timeout: int = 120, parse_json: bool = True, enable_tools: bool = False, cli_options: dict = None) -> dict:
        """Gemini CLI 실행 (동기). → GeminiExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch(
            "gemini", prompt,
            model=model, timeout=timeout, parse_json=parse_json,
            enable_tools=enable_tools, cli_options=cli_options,
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
    ) -> dict:
        """LLM 통합 실행. → ExecutionDispatcher.dispatch 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch(
            provider, prompt,
            model=model, timeout=timeout, parse_json=parse_json,
            enable_tools=enable_tools, cli_options=cli_options,
        )

    def execute_codex(self, prompt: str, model: str = "", timeout: int = 120) -> dict:
        """Codex CLI 실행. → CodexExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch("codex", prompt, model=model, timeout=timeout)

    def execute_cc_codex(self, prompt: str, model: str = "", timeout: int = 120) -> dict:
        """CC-Codex CLI 실행. → CCCodexExecutor 위임."""
        from app.modules.claude_worker.services.executors import ExecutionDispatcher
        return ExecutionDispatcher.dispatch("cc-codex", prompt, model=model, timeout=timeout)

    # ========== 워커 상태 관리 ==========

    def register_worker(self, worker_id: str, pid: int) -> LLMWorkerStatus:
        """워커 등록."""
        # 기존 워커 비활성화
        self._worker_repo.deactivate_all_alive()

        now = datetime.now()
        status = LLMWorkerStatus(
            worker_id=worker_id,
            pid=pid,
            started_at=now,
            last_heartbeat=now,
            current_state="idle",
            is_alive=True,
        )
        self._worker_repo.add(status)
        self.db.commit()
        self.db.refresh(status)
        return status

    def update_heartbeat(self, worker_id: str) -> None:
        """하트비트 업데이트."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.last_heartbeat = datetime.now()
            self.db.commit()

    def update_worker_state(
        self, worker_id: str, state: str, request_id: int = None
    ) -> None:
        """워커 상태 업데이트."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.current_state = state
            status.current_request_id = request_id
            self.db.commit()

    def increment_processed(self, worker_id: str) -> None:
        """처리 카운트 증가."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.processed_count += 1
            self.db.commit()

    def increment_error(self, worker_id: str) -> None:
        """에러 카운트 증가."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.error_count += 1
            self.db.commit()

    def mark_worker_dead(self, worker_id: str) -> None:
        """워커 종료 표시."""
        status = self._worker_repo.get_by_worker_id(worker_id)
        if status:
            status.is_alive = False
            status.current_state = "stopped"
            self.db.commit()

    def get_worker_status(self) -> Optional[LLMWorkerStatus]:
        """활성 워커 상태 조회."""
        return self._worker_repo.get_alive()

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

        from app.shared.worker.health_redis import WorkerHealthRedis
        redis_health = WorkerHealthRedis.check("claude")

        if redis_health and redis_health.get("source") == "redis":
            ttl = redis_health.get("ttl_remaining", 0)
            seconds_since = max(0, 30 - ttl)

            if ttl <= 0:
                return {
                    "status": "unhealthy",
                    "message": "Redis heartbeat 만료 - 재시작 필요",
                    "worker_id": status.worker_id,
                    "seconds_since_heartbeat": int(seconds_since),
                }
            elif ttl <= 15:
                return {
                    "status": "warning",
                    "message": f"마지막 heartbeat {seconds_since:.0f}초 전 - 지연 발생",
                    "worker_id": status.worker_id,
                    "state": status.current_state,
                    "seconds_since_heartbeat": int(seconds_since),
                }
        else:
            return {
                "status": "unhealthy",
                "message": "Redis heartbeat 키 없음 - 재시작 필요",
                "worker_id": status.worker_id,
                "seconds_since_heartbeat": 999,
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
        import json as _json
        request = self._repo.get_by_id(request_id)
        if not request or request.status not in ("pending", "failed"):
            return None
        if cli_options is not None:
            request.cli_options = _json.dumps(cli_options)
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

        all_requests = self._repo.find_by_date_range(
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time()),
        )

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
        results = self._repo.get_caller_stats_rows()

        stats = {}
        for caller_type, status, count in results:
            if caller_type not in stats:
                stats[caller_type] = {"total": 0, "pending": 0, "processing": 0, "completed": 0, "failed": 0}
            stats[caller_type][status] = count
            stats[caller_type]["total"] += count

        return stats

    # ========== Cleanup ==========

    # 상수 정의
    STALE_PROCESSING_TIMEOUT_MINUTES = 65  # 시스템건 타임아웃(60분) + 여유 5분
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
        stale_requests = self._repo.find_stale_processing(threshold)

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
        old_requests = self._repo.find_old_history(threshold)

        count = 0
        for request in old_requests:
            if hard_delete:
                self._repo.delete(request)
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

    def _build_caller_aggregate_query(self, caller_type: str = None):
        """caller별 집계 쿼리 빌더 — repo에 위임."""
        return self._repo.build_caller_aggregate_query(caller_type)

    def list_requests_grouped_by_caller(
        self,
        caller_type: str = None,
        only_without_success: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """caller_id별 그룹 요청 목록. GROUP BY 집계 + 배치 상세 2-query."""
        from sqlalchemy import and_, or_

        # 집계 쿼리 실행 — 로우 수 = distinct (caller_type, caller_id) 수
        all_agg = self._build_caller_aggregate_query(caller_type).all()

        # summary: only_without_success 필터 전(전체 caller 기준)
        total_callers = len(all_agg)
        callers_with_success = sum(1 for r in all_agg if r.has_success)
        callers_without_success = total_callers - callers_with_success
        summary = {
            "total_callers": total_callers,
            "callers_with_success": callers_with_success,
            "callers_without_success": callers_without_success,
        }

        # only_without_success 필터 (ORDER BY는 DB에 위임됨)
        filtered = [r for r in all_agg if not r.has_success] if only_without_success else all_agg

        total = len(filtered)
        pages = (total + page_size - 1) // page_size if total > 0 else 1
        paged = filtered[(page - 1) * page_size : page * page_size]

        if not paged:
            return {
                "items": [],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
                "summary": summary,
            }

        # 페이지 caller 키셋으로 상세 배치 조회 (최대 page_size건 OR 조건)
        caller_keys = [(r.caller_type, r.caller_id) for r in paged]
        conditions = [
            and_(LLMRequest.caller_type == ct, LLMRequest.caller_id == ci)
            for ct, ci in caller_keys
        ]
        detail_rows = self._repo.find_by_caller_batch(conditions)

        # caller별 상세 매핑
        # ASC 정렬이므로: 첫 row = prompt, 마지막 row = last_status/last_error
        caller_detail: dict = {}
        for req in detail_rows:
            key = (req.caller_type, req.caller_id)
            caller_detail.setdefault(key, {
                "prompt": req.prompt,  # ASC 첫 row의 prompt
                "last_status": req.status,
                "last_error": None,
                "request_ids": [],
            })
            d = caller_detail[key]
            d["last_status"] = req.status  # ASC 마지막 row로 덮어쓰기
            if req.status == "failed":
                d["request_ids"].append(req.id)
                if req.error_message:
                    d["last_error"] = req.error_message  # ASC 마지막 failed row의 error

        # 결과 조립
        items = []
        for r in paged:
            key = (r.caller_type, r.caller_id)
            detail = caller_detail.get(
                key,
                {"prompt": None, "last_status": None, "last_error": None, "request_ids": []},
            )
            items.append(
                {
                    "caller_type": r.caller_type,
                    "caller_id": r.caller_id,
                    "total_count": r.total_count,
                    "completed_count": r.completed_count,
                    "failed_count": r.failed_count,
                    "pending_count": r.pending_count,
                    "has_success": bool(r.has_success),
                    "last_status": detail["last_status"],
                    "last_requested_at": r.last_at.isoformat() if r.last_at else None,
                    "last_error": detail["last_error"],
                    "request_ids": detail["request_ids"],
                    "prompt": detail["prompt"],
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "summary": summary,
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
                    request = self._repo.get_by_id(request_id)
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
        """통계 조회. deleted_at 필터 없음 (soft-deleted 포함, 기존 동작 보존).
        COUNT 5회 → GROUP BY 1회로 통합.
        """
        rows = self._repo.get_status_counts()
        counts = {s: n for s, n in rows}
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
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
        completed_requests = self._repo.find_completed_since(threshold)

        # 실패한 요청 수
        failed_count = self._repo.count_failed_since(threshold)

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
