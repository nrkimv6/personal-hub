"""
LLM Provider Quota Pause 테스트 (RIGHT-BICEP + CORRECT)

Phase 7: 단위/서비스 테스트
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus
from app.modules.claude_worker.services.llm_service import (
    LLMService,
    QUOTA_PAUSE_DEFAULT_MS,
    _parse_quota_retry_ms,
)


# ========== Fixtures ==========

@pytest.fixture
def in_memory_engine():
    """인메모리 SQLite 엔진."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def llm_service_with_status(in_memory_engine):
    """LLMService + LLMWorkerStatus 레코드 1건 포함 인메모리 DB."""
    Session = sessionmaker(bind=in_memory_engine)
    db = Session()
    # worker status 레코드 생성
    status = LLMWorkerStatus(
        worker_id="test",
        is_alive=True,
        current_state="idle",
    )
    db.add(status)
    db.commit()
    service = LLMService(db)
    yield service, db
    db.close()


@pytest.fixture
def llm_service_empty(in_memory_engine):
    """LLMService + LLMWorkerStatus 레코드 없는 인메모리 DB."""
    Session = sessionmaker(bind=in_memory_engine)
    db = Session()
    service = LLMService(db)
    yield service, db
    db.close()


@pytest.fixture
def llm_service_with_requests(in_memory_engine):
    """LLMService + gemini/claude pending 요청 각 1건 포함 인메모리 DB."""
    Session = sessionmaker(bind=in_memory_engine)
    db = Session()
    status = LLMWorkerStatus(worker_id="test", is_alive=True, current_state="idle")
    db.add(status)

    req_gemini = LLMRequest(
        caller_type="test",
        caller_id="g1",
        prompt="gemini test",
        provider="gemini",
        status="pending",
        queue_name="utility",
    )
    req_claude = LLMRequest(
        caller_type="test",
        caller_id="c1",
        prompt="claude test",
        provider="claude",
        status="pending",
        queue_name="utility",
    )
    db.add(req_gemini)
    db.add(req_claude)
    db.commit()
    service = LLMService(db)
    yield service, db
    db.close()


# ========== 7-A: _parse_quota_retry_ms() TC ==========

class TestParseQuotaRetryMs:
    """_parse_quota_retry_ms() RIGHT + BICEP TC"""

    def test_parse_quota_retry_ms_retry_delay_ms(self):
        """retryDelayMs: 22751416.05046 포함 텍스트 → 22751416 반환."""
        text = "Some error output\nretryDelayMs: 22751416.05046\nmore lines"
        result = _parse_quota_retry_ms(text)
        assert result == 22751416

    def test_parse_quota_retry_ms_reset_after_text(self):
        """reset after 6h19m11s 포함 텍스트 → ms로 계산."""
        text = "quota exceeded. reset after 6h19m11s."
        result = _parse_quota_retry_ms(text)
        expected_ms = (6 * 3600 + 19 * 60 + 11) * 1000  # 22751000
        assert abs(result - expected_ms) <= 1000

    def test_parse_quota_retry_ms_priority(self):
        """두 패턴 모두 있으면 retryDelayMs 우선 반환."""
        text = "reset after 1h0m0s\nretryDelayMs: 99999"
        result = _parse_quota_retry_ms(text)
        assert result == 99999

    def test_parse_quota_retry_ms_empty_string(self):
        """빈 문자열 → None."""
        assert _parse_quota_retry_ms("") is None

    def test_parse_quota_retry_ms_zero(self):
        """retryDelayMs: 0 → 0 반환 (None 아님)."""
        text = "retryDelayMs: 0"
        result = _parse_quota_retry_ms(text)
        assert result is not None
        assert result == 0

    def test_parse_quota_retry_ms_no_pattern(self):
        """패턴 없는 텍스트 → None."""
        assert _parse_quota_retry_ms("generic error message") is None

    def test_parse_quota_retry_ms_zero_time(self):
        """reset after 0h0m0s → 0."""
        result = _parse_quota_retry_ms("reset after 0h0m0s")
        assert result == 0


# ========== 7-B: execute_gemini() quota 감지 TC ==========

class TestExecuteGeminiQuota:
    """execute_gemini() quota 감지 RIGHT + BICEP TC"""

    def test_execute_gemini_quota_with_retry_delay(self, in_memory_engine):
        """stderr에 TerminalQuotaError + retryDelayMs → quota_retry_ms == 22751416."""
        Session = sessionmaker(bind=in_memory_engine)
        db = Session()
        service = LLMService(db)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "TerminalQuotaError\nretryDelayMs: 22751416"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = service.execute_gemini("test prompt")

        assert result["success"] is False
        assert result["quota_retry_ms"] == 22751416
        db.close()

    def test_execute_gemini_quota_exhausted_default_ms(self, in_memory_engine):
        """stderr에 exhausted your capacity → quota_retry_ms == QUOTA_PAUSE_DEFAULT_MS."""
        Session = sessionmaker(bind=in_memory_engine)
        db = Session()
        service = LLMService(db)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "exhausted your capacity for today"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = service.execute_gemini("test prompt")

        assert result["success"] is False
        assert result["quota_retry_ms"] == QUOTA_PAUSE_DEFAULT_MS
        db.close()

    def test_execute_gemini_non_quota_error_no_key(self, in_memory_engine):
        """returncode != 0, quota 키워드 없음 → quota_retry_ms not in result."""
        Session = sessionmaker(bind=in_memory_engine)
        db = Session()
        service = LLMService(db)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "generic error"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = service.execute_gemini("test prompt")

        assert "quota_retry_ms" not in result
        db.close()

    def test_execute_gemini_success_no_quota_key(self, in_memory_engine):
        """returncode == 0 → success=True, quota_retry_ms not in result."""
        Session = sessionmaker(bind=in_memory_engine)
        db = Session()
        service = LLMService(db)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = '{"answer": "ok"}'

        with patch("subprocess.run", return_value=mock_result):
            result = service.execute_gemini("test prompt")

        assert result["success"] is True
        assert "quota_retry_ms" not in result
        db.close()


# ========== 7-C: set/get/clear_provider_quota_pause() TC ==========

class TestProviderQuotaPause:
    """set/get/clear_provider_quota_pause() RIGHT + BICEP TC"""

    def test_set_provider_quota_pause_saves_to_db(self, llm_service_with_status):
        """set_provider_quota_pause("gemini", 22751416) → 반환값이 datetime, DB 컬럼 확인."""
        service, db = llm_service_with_status
        result = service.set_provider_quota_pause("gemini", 22751416)
        assert isinstance(result, datetime)

        status = db.query(LLMWorkerStatus).first()
        assert status.quota_paused_provider == "gemini"
        assert status.quota_paused_until is not None

    def test_get_provider_quota_pause_returns_datetime(self, llm_service_with_status):
        """set 직후 get → datetime 반환."""
        service, db = llm_service_with_status
        service.set_provider_quota_pause("gemini", 3600000)  # 1시간
        result = service.get_provider_quota_pause("gemini")
        assert result is not None
        assert isinstance(result, datetime)

    def test_clear_provider_quota_pause_then_get_none(self, llm_service_with_status):
        """clear 후 get → None."""
        service, db = llm_service_with_status
        service.set_provider_quota_pause("gemini", 3600000)
        service.clear_provider_quota_pause("gemini")
        result = service.get_provider_quota_pause("gemini")
        assert result is None

    def test_get_provider_quota_pause_expired(self, llm_service_with_status):
        """paused_until을 과거로 직접 DB 설정 → get → None."""
        service, db = llm_service_with_status
        status = db.query(LLMWorkerStatus).first()
        status.quota_paused_provider = "gemini"
        status.quota_paused_until = datetime.now() - timedelta(seconds=1)
        db.commit()

        result = service.get_provider_quota_pause("gemini")
        assert result is None

    def test_get_provider_quota_pause_different_provider(self, llm_service_with_status):
        """claude pause 중 gemini get → None."""
        service, db = llm_service_with_status
        service.set_provider_quota_pause("claude", 3600000)
        result = service.get_provider_quota_pause("gemini")
        assert result is None

    def test_set_provider_quota_pause_no_status_record(self, llm_service_empty):
        """LLMWorkerStatus 레코드 없는 DB → set 호출 → 예외 없이 처리."""
        service, db = llm_service_empty
        try:
            service.set_provider_quota_pause("gemini", 3600000)
        except Exception as e:
            pytest.fail(f"예외 발생: {e}")

    def test_provider_pause_independence(self, in_memory_engine):
        """gemini + claude 각각 set → 각각 독립 확인."""
        Session = sessionmaker(bind=in_memory_engine)
        db = Session()
        # 두 레코드 생성
        db.add(LLMWorkerStatus(worker_id="w1", is_alive=True))
        db.commit()

        service = LLMService(db)
        service.set_provider_quota_pause("gemini", 3600000)
        # gemini pause 상태
        assert service.get_provider_quota_pause("gemini") is not None
        # claude는 pause 안 됨
        assert service.get_provider_quota_pause("claude") is None

        db.close()


# ========== 7-D: get_next_request(exclude_providers) TC ==========

class TestGetNextRequestExclude:
    """get_next_request() provider 제외 RIGHT + BICEP TC"""

    def test_get_next_request_exclude_gemini_only_gemini(self, llm_service_with_requests):
        """gemini 요청만 있고 exclude_providers=["gemini"] → None."""
        service, db = llm_service_with_requests
        # claude 요청 삭제
        db.query(LLMRequest).filter(LLMRequest.provider == "claude").delete()
        db.commit()

        result = service.get_next_request(exclude_providers=["gemini"])
        assert result is None

    def test_get_next_request_exclude_gemini_returns_claude(self, llm_service_with_requests):
        """gemini+claude 요청, exclude_providers=["gemini"] → claude 요청 반환."""
        service, db = llm_service_with_requests
        result = service.get_next_request(exclude_providers=["gemini"])
        assert result is not None
        assert result.provider == "claude"

    def test_get_next_request_empty_exclude(self, llm_service_with_requests):
        """exclude_providers=[] → 기존 동작 (가장 높은 우선순위 요청)."""
        service, db = llm_service_with_requests
        result = service.get_next_request(exclude_providers=[])
        assert result is not None

    def test_get_next_request_exclude_all_providers(self, llm_service_with_requests):
        """exclude_providers=["gemini", "claude"] → None."""
        service, db = llm_service_with_requests
        result = service.get_next_request(exclude_providers=["gemini", "claude"])
        assert result is None

    def test_get_next_request_priority_preserved_after_exclude(self, in_memory_engine):
        """gemini 제외 후 남은 요청 중 system 우선 반환."""
        Session = sessionmaker(bind=in_memory_engine)
        db = Session()
        # system 큐 claude 요청 (나중에 추가됐지만 system이므로 우선)
        req_sys = LLMRequest(
            caller_type="test", caller_id="sys1", prompt="sys",
            provider="claude", status="pending", queue_name="system",
        )
        # utility 큐 claude 요청
        req_util = LLMRequest(
            caller_type="test", caller_id="util1", prompt="util",
            provider="claude", status="pending", queue_name="utility",
        )
        db.add(req_sys)
        db.add(req_util)
        db.commit()

        service = LLMService(db)
        result = service.get_next_request(exclude_providers=["gemini"])
        assert result is not None
        assert result.queue_name == "system"
        db.close()


# ========== 7-E: reset_quota_failed_requests() TC ==========

class TestResetQuotaFailedRequests:
    """reset_quota_failed_requests() RIGHT + BICEP TC"""

    def _make_failed_request(self, db, provider, error_msg, caller_id="r1"):
        req = LLMRequest(
            caller_type="test", caller_id=caller_id, prompt="test",
            provider=provider, status="failed", queue_name="utility",
            error_message=error_msg,
        )
        db.add(req)
        db.commit()
        return req

    def test_reset_quota_failed_terminal_quota_error(self, llm_service_with_status):
        """gemini failed + TerminalQuotaError → pending 전환, 반환값 == 1."""
        service, db = llm_service_with_status
        self._make_failed_request(db, "gemini", "Gemini CLI error: TerminalQuotaError")
        count = service.reset_quota_failed_requests("gemini")
        assert count == 1
        req = db.query(LLMRequest).first()
        assert req.status == "pending"

    def test_reset_quota_failed_exhausted_capacity(self, llm_service_with_status):
        """gemini failed + exhausted your capacity → pending 전환."""
        service, db = llm_service_with_status
        self._make_failed_request(db, "gemini", "exhausted your capacity for today", caller_id="r2")
        count = service.reset_quota_failed_requests("gemini")
        assert count == 1

    def test_reset_quota_failed_wrong_provider(self, llm_service_with_status):
        """claude failed + quota 메시지, gemini 대상 호출 → 반환값 == 0."""
        service, db = llm_service_with_status
        self._make_failed_request(db, "claude", "TerminalQuotaError", caller_id="r3")
        count = service.reset_quota_failed_requests("gemini")
        assert count == 0

    def test_reset_quota_failed_non_quota_error(self, llm_service_with_status):
        """gemini failed + 일반 에러 → 반환값 == 0."""
        service, db = llm_service_with_status
        self._make_failed_request(db, "gemini", "generic error", caller_id="r4")
        count = service.reset_quota_failed_requests("gemini")
        assert count == 0

    def test_reset_quota_failed_zero_targets(self, llm_service_with_status):
        """대상 없음 → 반환값 == 0, 예외 없음."""
        service, db = llm_service_with_status
        count = service.reset_quota_failed_requests("gemini")
        assert count == 0
