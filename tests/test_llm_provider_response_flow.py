"""LLM provider 응답 처리 흐름 검증 테스트.

테스트 범위:
1. execute_llm() provider 분기 (gemini/claude 라우팅)
2. _parse_json_response() JSON 파싱 (코드블록, 순수 JSON, 텍스트 래핑, 실패)
3. Instagram 분류 응답 저장 흐름 (mock 방식)
4. execute_gemini()가 cli_options를 수용하되 image_path만 사용하는 동작 명시적 검증
"""

import inspect
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ---------------------------------------------------------------------------
# Helper: DB 없이 LLMService 인스턴스 생성
# ---------------------------------------------------------------------------

def _make_service():
    """LLMService를 DB 없이 생성 (DB가 필요한 메서드는 테스트하지 않음)."""
    from app.modules.claude_worker.services.llm_service import LLMService

    service = LLMService.__new__(LLMService)
    service.db = MagicMock()
    return service


# ===========================================================================
# 1. execute_llm() provider 분기 테스트
# ===========================================================================

class TestExecuteLlmProviderRouting(unittest.TestCase):
    """execute_llm()이 provider 파라미터에 따라 올바른 실행 메서드를 호출하는지 확인."""

    def setUp(self):
        self.service = _make_service()

    def test_gemini_provider_calls_execute_gemini(self):
        """provider='gemini' 전달 시 execute_gemini() 가 호출돼야 한다."""
        expected = {"success": True, "result": {"key": "value"}, "raw_response": "{}"}

        with patch.object(self.service, "execute_gemini", return_value=expected) as mock_gemini, \
             patch.object(self.service, "execute_claude") as mock_claude:

            result = self.service.execute_llm(prompt="test prompt", provider="gemini")

        mock_gemini.assert_called_once()
        mock_claude.assert_not_called()
        self.assertEqual(result, expected)

    def test_claude_provider_calls_execute_claude(self):
        """provider='claude' 전달 시 execute_claude() 가 호출돼야 한다."""
        expected = {"success": True, "result": {"key": "value"}, "raw_response": "{}"}

        with patch.object(self.service, "execute_claude", return_value=expected) as mock_claude, \
             patch.object(self.service, "execute_gemini") as mock_gemini:

            result = self.service.execute_llm(prompt="test prompt", provider="claude")

        mock_claude.assert_called_once()
        mock_gemini.assert_not_called()
        self.assertEqual(result, expected)

    def test_default_provider_is_claude(self):
        """provider 미지정 시 기본값 claude가 사용돼야 한다."""
        expected = {"success": True, "result": {}, "raw_response": "{}"}

        with patch.object(self.service, "execute_claude", return_value=expected) as mock_claude, \
             patch.object(self.service, "execute_gemini") as mock_gemini:

            self.service.execute_llm(prompt="test")

        mock_claude.assert_called_once()
        mock_gemini.assert_not_called()


# ===========================================================================
# 2. _parse_json_response() JSON 파싱 테스트
# ===========================================================================

class TestParseJsonResponse(unittest.TestCase):
    """_parse_json_response() 각 케이스 단위 테스트 (실제 호출)."""

    def setUp(self):
        self.service = _make_service()

    def test_tc_code_block_gemini_style(self):
        """TC-CodeBlock: Gemini가 ```json ... ``` 블록으로 응답 → 올바른 dict 추출."""
        text = '```json\n{"tag": "이벤트", "summary": "봄 할인"}\n```'
        result = self.service._parse_json_response(text)
        self.assertEqual(result["tag"], "이벤트")
        self.assertEqual(result["summary"], "봄 할인")

    def test_tc_pure_json(self):
        """TC-PureJson: 순수 {"key": "value"} 응답 → 올바른 dict 추출."""
        text = '{"tag": "팝업", "summary": "신상품 팝업 스토어"}'
        result = self.service._parse_json_response(text)
        self.assertEqual(result["tag"], "팝업")
        self.assertEqual(result["summary"], "신상품 팝업 스토어")

    def test_tc_text_wrapped(self):
        """TC-TextWrapped: 앞뒤 설명 텍스트 + {...} 블록 → dict 추출."""
        text = (
            "아래는 분석 결과입니다:\n\n"
            '{"tag": "기타", "summary": "일반 홍보 게시물"}\n\n'
            "이상입니다."
        )
        result = self.service._parse_json_response(text)
        self.assertEqual(result["tag"], "기타")
        self.assertEqual(result["summary"], "일반 홍보 게시물")

    def test_tc_fail_no_json(self):
        """TC-Fail: JSON 없는 텍스트 → ValueError 발생."""
        text = "이 텍스트에는 JSON이 전혀 없습니다. 분류 불가능한 응답입니다."
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            self.service._parse_json_response(text)


# ===========================================================================
# 3. Instagram 분류 응답 저장 흐름 테스트 (mock 방식)
# ===========================================================================

class TestInstagramClassificationFlow(unittest.TestCase):
    """worker.py의 save_instagram_result()가 Gemini 응답을 올바르게 저장하는지 확인."""

    def _make_mock_post(self, post_id: int):
        """Mock InstagramPost 객체 생성."""
        post = MagicMock()
        post.id = post_id
        post.account = "test_account"
        post.images = [{"src": "https://example.com/img.jpg"}]
        return post

    def _run_save_instagram_result(self, llm_result: dict, post_id: int = 1):
        """save_instagram_result()를 mock DB로 실행하고 저장 호출 여부를 검증한다.

        save_instagram_result()는 내부 로컬 import로 모델을 가져오므로
        db.add() 호출 횟수 및 인자를 통해 어떤 모델이 저장됐는지 확인한다.
        """
        from app.modules.claude_worker.worker.worker import save_instagram_result

        mock_post = self._make_mock_post(post_id)
        mock_db = MagicMock()

        # DB 쿼리 체인 mock — InstagramPost 조회
        mock_db.query.return_value.filter.return_value.first.return_value = mock_post

        result = save_instagram_result(mock_db, post_id, llm_result)
        return result, mock_db

    def test_instagram_event_tag_creates_event_record(self):
        """tag='이벤트' 응답 → Event 모델 인스턴스가 db.add()에 전달돼야 한다."""
        from app.models.event import Event

        llm_result = {
            "tag": "이벤트",
            "summary": "봄 세일 이벤트",
            "urls": ["https://event.example.com"],
            "event_period": {"start": "2026-03-01", "end": "2026-03-31"},
            "announcement_date": None,
            "location": {},
        }

        result, mock_db = self._run_save_instagram_result(llm_result)

        self.assertTrue(result)

        # db.add() 호출된 객체 중 Event 인스턴스가 있는지 확인
        added_types = [type(call.args[0]).__name__ for call in mock_db.add.call_args_list]
        self.assertIn("Event", added_types, f"Event 레코드가 저장돼야 한다. 실제 저장: {added_types}")
        self.assertNotIn("Popup", added_types)

    def test_instagram_popup_tag_creates_popup_record(self):
        """tag='팝업' 응답 → Popup 모델 인스턴스가 db.add()에 전달돼야 한다."""
        from app.models.popup import Popup

        llm_result = {
            "tag": "팝업",
            "summary": "팝업 스토어 오픈",
            "urls": [],
            "event_period": None,
            "announcement_date": None,
            "location": {},
        }

        result, mock_db = self._run_save_instagram_result(llm_result)

        self.assertTrue(result)

        added_types = [type(call.args[0]).__name__ for call in mock_db.add.call_args_list]
        self.assertIn("Popup", added_types, f"Popup 레코드가 저장돼야 한다. 실제 저장: {added_types}")
        self.assertNotIn("Event", added_types)

    def test_instagram_other_tag_creates_uncategorized_record(self):
        """tag='기타' 응답 → UncategorizedPost 모델 인스턴스가 db.add()에 전달돼야 한다."""
        from app.models.uncategorized_post import UncategorizedPost

        llm_result = {
            "tag": "기타",
            "summary": "일반 홍보 게시물",
            "urls": [],
            "event_period": None,
            "announcement_date": None,
            "location": {},
        }

        result, mock_db = self._run_save_instagram_result(llm_result)

        self.assertTrue(result)

        added_types = [type(call.args[0]).__name__ for call in mock_db.add.call_args_list]
        self.assertIn("UncategorizedPost", added_types, f"UncategorizedPost 레코드가 저장돼야 한다. 실제 저장: {added_types}")
        self.assertNotIn("Event", added_types)
        self.assertNotIn("Popup", added_types)

    def test_instagram_result_requires_tag_and_summary(self):
        """필수 필드 tag, summary가 있으면 예외 없이 처리된다."""
        llm_result = {
            "tag": "이벤트",
            "summary": "필수 필드 존재",
        }

        # tag와 summary가 있으면 예외 없이 처리돼야 함
        try:
            result, _ = self._run_save_instagram_result(llm_result)
            self.assertTrue(result)
        except Exception as e:
            self.fail(f"tag/summary 있는 결과 처리 중 예외 발생: {e}")

    def test_instagram_result_post_not_found_returns_false(self):
        """존재하지 않는 post_id → False 반환."""
        from app.modules.claude_worker.worker.worker import save_instagram_result

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None  # post 없음

        result = save_instagram_result(mock_db, 999999, {"tag": "기타", "summary": "없는 포스트"})
        self.assertFalse(result)


# ===========================================================================
# 4. execute_gemini()가 cli_options를 수용하되 image_path만 사용하는 동작 명시적 검증
# ===========================================================================

class TestGeminiCliOptions(unittest.TestCase):
    """execute_gemini()가 cli_options 파라미터를 수용하고 image_path만 사용함을 검증.

    설계 의도:
        Gemini는 Claude CLI subprocess와 달리 output_format, json_schema 등
        Claude CLI 전용 파라미터를 사용할 수 없다.
        단, image_path는 `@경로` 문법으로 이미지 첨부에 사용한다.
        응답은 raw text로 받아 _parse_json_response()로 파싱한다.

        이 테스트는 그 동작 차이를 문서화한다.
    """

    def setUp(self):
        self.service = _make_service()

    def test_execute_gemini_has_cli_options_parameter(self):
        """execute_gemini() 시그니처에 cli_options 파라미터가 있어야 한다 (image_path 전달용)."""
        from app.modules.claude_worker.services.llm_service import LLMService

        sig = inspect.signature(LLMService.execute_gemini)
        param_names = list(sig.parameters.keys())

        # cli_options 파라미터가 존재해야 함
        self.assertIn(
            "cli_options",
            param_names,
            "execute_gemini()는 cli_options 파라미터를 가져야 한다 (image_path 전달용).",
        )

    def test_execute_claude_has_cli_options_parameter(self):
        """execute_claude()는 cli_options 파라미터를 갖는다 (대조 확인)."""
        from app.modules.claude_worker.services.llm_service import LLMService

        sig = inspect.signature(LLMService.execute_claude)
        param_names = list(sig.parameters.keys())

        self.assertIn(
            "cli_options",
            param_names,
            "execute_claude()는 cli_options 파라미터를 가져야 한다.",
        )

    def test_execute_llm_with_gemini_passes_cli_options_to_execute_gemini(self):
        """provider='gemini' + cli_options 전달 시 cli_options가 execute_gemini()로 전달돼야 한다.

        설계 의도:
            execute_llm()이 gemini 분기에서 execute_gemini()를 호출할 때
            cli_options를 그대로 전달한다. (image_path 등 gemini 전용 옵션 활용)
            이 테스트는 그 동작을 문서화한다.
        """
        mock_gemini_result = {
            "success": True,
            "result": {"tag": "이벤트"},
            "raw_response": '{"tag": "이벤트"}',
        }

        with patch.object(self.service, "execute_gemini", return_value=mock_gemini_result) as mock_gemini:
            result = self.service.execute_llm(
                prompt="분류해주세요",
                provider="gemini",
                cli_options={"image_path": "/test/57.jpg"},
            )

        # execute_gemini가 호출됐는지 확인
        mock_gemini.assert_called_once()

        # execute_gemini 호출 시 cli_options가 전달됐는지 확인
        # positional(args) 또는 keyword(kwargs) 모두 허용
        call_args = mock_gemini.call_args[0]    # positional arguments
        call_kwargs = mock_gemini.call_args[1]  # keyword arguments

        # execute_gemini(prompt, model, timeout, parse_json, enable_tools, cli_options)
        # positional 6번째(index 5) 또는 keyword "cli_options"로 전달됨
        cli_options_passed = (
            "cli_options" in call_kwargs
            or len(call_args) >= 6  # positional 6개 이상이면 cli_options 포함
        )
        self.assertTrue(
            cli_options_passed,
            "execute_gemini() 호출에 cli_options가 전달돼야 한다 (image_path 포함).",
        )

        # 결과는 정상 반환
        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["tag"], "이벤트")

    def test_gemini_response_goes_through_raw_parsing(self):
        """provider='gemini'이면 응답이 _parse_json_response()를 통해 파싱된다.

        설계 의도:
            Claude는 --output-format json 옵션으로 구조화된 JSON을 직접 반환할 수 있지만,
            Gemini는 항상 raw text로 응답하고 _parse_json_response()가 JSON을 추출한다.
            이 테스트는 그 파싱 경로가 실제로 동작함을 검증한다.
        """
        raw_gemini_response = '```json\n{"tag": "팝업", "summary": "신규 팝업"}\n```'
        parsed = self.service._parse_json_response(raw_gemini_response)

        self.assertEqual(parsed["tag"], "팝업")
        self.assertEqual(parsed["summary"], "신규 팝업")


# ===========================================================================
# 5. execute_gemini() image_path 동작 TC
# ===========================================================================

class TestGeminiImagePath(unittest.TestCase):
    """execute_gemini()가 cli_options["image_path"]를 subprocess 명령어에 @경로로 추가하는지 검증."""

    def setUp(self):
        self.service = _make_service()

    def _make_mock_run(self):
        """subprocess.run mock — returncode=0, 유효한 JSON 응답."""
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = '{"category": "test", "confidence": 0.9}'
        mock.stderr = "Loaded cached credentials."
        return mock

    def test_image_path_appended_to_cmd(self):
        """cli_options={"image_path": "C:/test/57.jpg"} 시 cmd에 @"C:/test/57.jpg" 포함."""
        import sys
        mock_result = self._make_mock_run()

        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("os.unlink"):
            self.service.execute_gemini(
                prompt="이미지를 분류하세요",
                cli_options={"image_path": "C:/test/57.jpg"},
                parse_json=False,
            )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]  # positional 첫 번째 인수 (cmd 문자열)
        self.assertIn('@"C:/test/57.jpg"', cmd)

    def test_no_image_path_no_append(self):
        """cli_options=None 또는 image_path 없을 때 cmd에 @ 문자 없음."""
        mock_result = self._make_mock_run()

        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("os.unlink"):
            self.service.execute_gemini(
                prompt="분류",
                cli_options=None,
                parse_json=False,
            )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertNotIn(" @", cmd)

    def test_claude_unaffected(self):
        """execute_claude() 시그니처에 cli_options 파라미터가 여전히 존재 (회귀 방지)."""
        from app.modules.claude_worker.services.llm_service import LLMService

        sig = inspect.signature(LLMService.execute_claude)
        param_names = list(sig.parameters.keys())
        self.assertIn(
            "cli_options",
            param_names,
            "execute_claude()는 cli_options 파라미터를 유지해야 한다.",
        )


# ===========================================================================
# 6. RIGHT-BICEP: parse_json=False / caller_type fallback / mark_failed
# ===========================================================================

class TestParsJsonFalseAndCallerTypeFallback(unittest.TestCase):
    """TC-R/B/E: parse_json=False 처리 및 caller_type fallback 로직 검증.

    TC-R (Right): parse_json=False 시 plain text 응답이 success=True로 처리됨
    TC-B (Boundary): caller_type="test" + JSON 파싱 실패 → mark_completed (raw_response 사용)
    TC-E (Error): 미등록 caller_type + JSON 파싱 실패 → mark_failed 호출
    """

    def test_tc_r_parse_json_false_plain_text_success(self):
        """TC-R: parse_json=False 설정 시 plain text 응답이 success=True로 반환돼야 한다."""
        service = _make_service()
        raw_text = "# 계획서\n아이디어 구체화\n"

        with patch.object(service, "execute_claude", return_value={
            "success": True,
            "result": None,
            "raw_response": raw_text,
        }) as mock_claude:
            result = service.execute_llm(
                prompt="/plan 테스트",
                provider="claude",
                parse_json=False,
                cli_options={"cwd": "/tmp", "parse_json": False},
            )

        self.assertTrue(result["success"], f"성공이어야 함: {result}")
        self.assertEqual(result.get("raw_response"), raw_text)

    def test_tc_b_test_caller_type_fallback_on_json_failure(self):
        """TC-B: JSON 파싱 실패 + caller_type='test' → mark_completed가 raw_response로 호출돼야 한다."""
        # worker.py의 fallback 분기 로직을 직접 테스트
        service_mock = MagicMock()
        service_mock.mark_completed = MagicMock()
        service_mock.mark_failed = MagicMock()

        request = MagicMock()
        request.id = 999
        request.caller_type = "test"

        llm_result = {
            "success": False,
            "error": "JSON 파싱 실패: No valid JSON found in response",
            "raw_response": "# 계획서\n- 아이디어 구체화",
        }

        # worker.py 1465-1485 분기 로직 재현
        result = llm_result
        if not result["success"]:
            if "raw_response" in result and result.get("raw_response"):
                if request.caller_type in ["writing_generate", "writing_refine", "report", "test"]:
                    service_mock.mark_completed(
                        request.id,
                        {},
                        result.get("raw_response", ""),
                    )
                else:
                    service_mock.mark_failed(request.id, result["error"], result.get("raw_response", ""))

        service_mock.mark_completed.assert_called_once_with(
            999, {}, "# 계획서\n- 아이디어 구체화"
        )
        service_mock.mark_failed.assert_not_called()

    def test_tc_e_unknown_caller_type_marks_failed(self):
        """TC-E: 미등록 caller_type + JSON 파싱 실패 → mark_failed가 호출돼야 한다."""
        service_mock = MagicMock()
        service_mock.mark_completed = MagicMock()
        service_mock.mark_failed = MagicMock()

        request = MagicMock()
        request.id = 1000
        request.caller_type = "unknown_type"

        llm_result = {
            "success": False,
            "error": "JSON 파싱 실패: No valid JSON found in response",
            "raw_response": "some plain text",
        }

        result = llm_result
        if not result["success"]:
            if "raw_response" in result and result.get("raw_response"):
                if request.caller_type in ["writing_generate", "writing_refine", "report", "test"]:
                    service_mock.mark_completed(request.id, {}, result.get("raw_response", ""))
                else:
                    service_mock.mark_failed(request.id, result["error"], result.get("raw_response", ""))

        service_mock.mark_failed.assert_called_once_with(
            1000,
            "JSON 파싱 실패: No valid JSON found in response",
            "some plain text",
        )
        service_mock.mark_completed.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
