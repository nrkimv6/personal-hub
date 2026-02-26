"""Instagram Classifier LLM Provider 테스트.

테스트 범위:
1. LLMClassifierService.create_request() 에 provider 파라미터가 enqueue()로 전달되는지
2. ClassifierService._trigger_llm_classification_if_needed() 가
   instagram_feed 스케줄의 target_config에서 provider를 읽어 전달하는지
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ---------------------------------------------------------------------------
# Helper: mock DB 세션 생성
# ---------------------------------------------------------------------------

def _make_mock_db():
    """SQLAlchemy Session 모의 객체 반환."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


# ===========================================================================
# 1. LLMClassifierService.create_request() — provider 파라미터 전달 검증
# ===========================================================================

class TestLLMClassifierServiceProvider(unittest.TestCase):
    """LLMClassifierService.create_request()가 provider/model을 enqueue()로 올바르게 전달하는지 확인."""

    def _make_mock_post(self, post_id=1):
        """mock InstagramPost 반환."""
        post = MagicMock()
        post.id = post_id
        post.caption = "이벤트 참여하세요! 추첨을 통해 선물을 드립니다."
        post.posted_at = None
        post.images = []
        return post

    def _make_service_with_mock_db(self, post):
        """post를 반환하는 mock DB로 LLMClassifierService 인스턴스 생성."""
        from app.modules.instagram.services.llm_classifier_service import LLMClassifierService

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = post

        service = LLMClassifierService.__new__(LLMClassifierService)
        service.db = db
        service._llm_service = MagicMock()
        service._llm_service.enqueue.return_value = MagicMock()
        return service

    def test_create_request_right_gemini_provider(self):
        """TC-Right: provider='gemini' 전달 시 enqueue()에 provider='gemini' 전달됨."""
        post = self._make_mock_post()
        service = self._make_service_with_mock_db(post)

        service.create_request(post_id=1, trigger_tag="event", provider="gemini", model="gemini-2.0-flash")

        service._llm_service.enqueue.assert_called_once()
        call_kwargs = service._llm_service.enqueue.call_args
        assert call_kwargs.kwargs.get("provider") == "gemini", (
            f"enqueue()에 provider='gemini' 전달 안 됨: {call_kwargs.kwargs}"
        )
        assert call_kwargs.kwargs.get("model") == "gemini-2.0-flash", (
            f"enqueue()에 model='gemini-2.0-flash' 전달 안 됨: {call_kwargs.kwargs}"
        )

    def test_create_request_default_claude_provider(self):
        """TC-Default: provider 미지정(기본값) 시 enqueue()에 provider='claude' 전달됨."""
        post = self._make_mock_post()
        service = self._make_service_with_mock_db(post)

        service.create_request(post_id=1, trigger_tag="event")

        service._llm_service.enqueue.assert_called_once()
        call_kwargs = service._llm_service.enqueue.call_args
        assert call_kwargs.kwargs.get("provider") == "claude", (
            f"기본값 provider='claude' 아님: {call_kwargs.kwargs}"
        )

    def test_create_requests_batch_passes_provider(self):
        """TC-Batch: create_requests_batch()가 각 create_request()에 provider 전달함."""
        post = self._make_mock_post()

        from app.modules.instagram.services.llm_classifier_service import LLMClassifierService

        service = LLMClassifierService.__new__(LLMClassifierService)
        service.db = MagicMock()
        service._llm_service = MagicMock()

        with patch.object(service, "create_request", return_value=MagicMock()) as mock_cr:
            service.create_requests_batch(
                post_ids=[1, 2],
                trigger_tag="manual",
                provider="gemini",
                model="gemini-2.0-flash",
            )

        assert mock_cr.call_count == 2
        for c in mock_cr.call_args_list:
            assert c.kwargs.get("provider") == "gemini", (
                f"create_request()에 provider='gemini' 전달 안 됨: {c}"
            )


# ===========================================================================
# 2. ClassifierService._trigger_llm_classification_if_needed() — target_config 읽기 검증
# ===========================================================================

class TestClassifierServiceProviderFromSchedule(unittest.TestCase):
    """ClassifierService._trigger_llm_classification_if_needed()가
    instagram_feed 스케줄의 target_config에서 llm_provider를 읽는지 확인."""

    def _make_classifier_service(self):
        """ClassifierService 인스턴스 (mock DB)."""
        from app.modules.instagram.services.classifier_service import ClassifierService

        db = MagicMock()
        service = ClassifierService.__new__(ClassifierService)
        service.db = db
        service._keyword_cache = {}
        return service

    def _make_mock_schedule(self, provider="gemini", model="gemini-2.0-flash"):
        """target_config를 가진 mock TaskSchedule 반환."""
        schedule = MagicMock()
        schedule.target_config = f'{{"llm_provider": "{provider}", "llm_model": "{model}"}}'
        schedule.get_target_config.return_value = {
            "llm_provider": provider,
            "llm_model": model,
        }
        return schedule

    def test_trigger_reads_gemini_provider_from_schedule(self):
        """TC-Right: instagram_feed 스케줄 target_config에 llm_provider=gemini 있으면 gemini로 요청 생성."""
        service = self._make_classifier_service()
        mock_schedule = self._make_mock_schedule(provider="gemini", model="")

        # DB에서 스케줄 반환하도록 설정
        service.db.query.return_value.filter_by.return_value.first.return_value = mock_schedule

        mock_llm_service = MagicMock()
        mock_llm_service.should_trigger_llm.return_value = True
        mock_llm_service.get_trigger_tag.return_value = "event"

        # _trigger_llm_classification_if_needed 내부에서 지역 import하므로
        # 모듈 속성을 직접 교체하여 패치
        import app.modules.instagram.services.llm_classifier_service as llm_cls_mod
        original_llm_cls = llm_cls_mod.LLMClassifierService
        mock_ctor = MagicMock(return_value=mock_llm_service)
        try:
            llm_cls_mod.LLMClassifierService = mock_ctor
            service._trigger_llm_classification_if_needed(post_id=1, matched_tags=["event"])
        finally:
            llm_cls_mod.LLMClassifierService = original_llm_cls

        mock_llm_service.create_request.assert_called_once()
        call_kwargs = mock_llm_service.create_request.call_args
        assert call_kwargs.kwargs.get("provider") == "gemini", (
            f"create_request()에 provider='gemini' 전달 안 됨: {call_kwargs}"
        )

    def test_trigger_defaults_to_claude_when_no_schedule(self):
        """TC-Default: instagram_feed 스케줄 없을 때 기본값 provider='claude' 사용."""
        service = self._make_classifier_service()

        # 스케줄 없음
        service.db.query.return_value.filter_by.return_value.first.return_value = None

        mock_llm_service = MagicMock()
        mock_llm_service.should_trigger_llm.return_value = True
        mock_llm_service.get_trigger_tag.return_value = "event"

        import app.modules.instagram.services.llm_classifier_service as llm_cls_mod
        original_llm_cls = llm_cls_mod.LLMClassifierService
        mock_ctor = MagicMock(return_value=mock_llm_service)
        try:
            llm_cls_mod.LLMClassifierService = mock_ctor
            service._trigger_llm_classification_if_needed(post_id=1, matched_tags=["event"])
        finally:
            llm_cls_mod.LLMClassifierService = original_llm_cls

        mock_llm_service.create_request.assert_called_once()
        call_kwargs = mock_llm_service.create_request.call_args
        assert call_kwargs.kwargs.get("provider") == "claude", (
            f"기본값 provider='claude' 아님: {call_kwargs}"
        )

    def test_trigger_no_llm_when_tag_not_trigger(self):
        """TC-NoTrigger: 트리거 태그 없으면 LLM 요청 생성하지 않음."""
        service = self._make_classifier_service()

        mock_llm_service = MagicMock()
        mock_llm_service.should_trigger_llm.return_value = False

        import app.modules.instagram.services.llm_classifier_service as llm_cls_mod
        original_llm_cls = llm_cls_mod.LLMClassifierService
        mock_ctor = MagicMock(return_value=mock_llm_service)
        try:
            llm_cls_mod.LLMClassifierService = mock_ctor
            service._trigger_llm_classification_if_needed(post_id=1, matched_tags=["other_tag"])
        finally:
            llm_cls_mod.LLMClassifierService = original_llm_cls

        mock_llm_service.create_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
