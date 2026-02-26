"""image_classify enqueue→폴링 흐름 e2e TC.

테스트 범위:
1. provider="gemini" 시 LLMService.enqueue()에 image_path 포함된 cli_options 전달
2. provider="claude" 시 cli_options에 image_path 없음 (Claude CLI exec_mode 사용)

enqueue_and_poll은 run_classification 내부 클로저이므로
run_classification을 통해 LLMService.enqueue mock으로 검증한다.
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _make_mock_llm_request(file_id: int, classify_path: str):
    """completed 상태의 더미 LLMRequest 반환."""
    req = MagicMock()
    req.id = file_id * 100
    req.status = "completed"
    req.result = json.dumps({"category": "test/category", "confidence": 0.9, "reasoning": "test"})
    req.error_message = None
    return req


class TestImageClassifyEnqueueFlow(unittest.TestCase):
    """run_classification을 통한 enqueue_and_poll 흐름 검증."""

    def _run_classification_with_mock(self, provider: str, file_id: int = 1):
        """단일 파일에 대해 run_classification을 실행하고 enqueue 호출 인수 반환."""
        from app.modules.image_classifier.routers import classify as classify_module

        fake_file = MagicMock()
        fake_file.id = file_id
        fake_file.file_path = f"/test/images/{file_id}.jpg"
        fake_file.phash = None

        enqueue_calls = []

        def fake_enqueue(**kwargs):
            enqueue_calls.append(kwargs)
            return _make_mock_llm_request(file_id, fake_file.file_path)

        def fake_get_request_by_id(req_id):
            return _make_mock_llm_request(file_id, fake_file.file_path)

        mock_db_session = MagicMock()
        mock_llm_service = MagicMock()
        mock_llm_service.enqueue.side_effect = fake_enqueue
        mock_llm_service.get_request_by_id.side_effect = fake_get_request_by_id

        mock_ic_db = MagicMock()
        mock_ic_db.execute.return_value.fetchall.return_value = [("카테고리A",), ("카테고리B",)]

        # thumbnail 파일 없음 → file_path 그대로 사용
        with patch.object(Path, "exists", return_value=False), \
             patch("app.modules.image_classifier.routers.classify._get_monitor_db_session",
                   return_value=mock_db_session), \
             patch("app.modules.claude_worker.services.llm_service.LLMService",
                   return_value=mock_llm_service), \
             patch("app.modules.image_classifier.routers.classify.SessionLocal",
                   return_value=mock_ic_db), \
             patch("app.modules.image_classifier.routers.classify.TaskProgressManager") as mock_pm, \
             patch("app.modules.image_classifier.routers.classify.pipeline_logs"):

            mock_pm.return_value.start_task.return_value = 1
            mock_pm.return_value.update_progress = MagicMock()
            mock_pm.return_value.finish_task = MagicMock()

            # classification_status 초기화
            classify_module.classification_status["running"] = True
            classify_module.classification_status["total"] = 1
            classify_module.classification_status["processed"] = 0
            classify_module.classification_status["failed"] = 0

            model = "gemini_cli" if provider == "gemini" else "claude_cli"
            asyncio.run(
                classify_module.run_classification(
                    files=[(fake_file.id, fake_file.file_path)],
                    model=model,
                    batch_size=1,
                    gap_minutes=0,
                    max_workers=1,
                )
            )

        return enqueue_calls

    def test_gemini_enqueue_includes_image_path(self):
        """provider='gemini' 시 enqueue()의 cli_options에 image_path 키가 포함됨."""
        calls = self._run_classification_with_mock(provider="gemini", file_id=1)

        self.assertTrue(len(calls) > 0, "enqueue()가 호출돼야 한다.")
        cli_options = calls[0].get("cli_options")
        self.assertIsNotNone(cli_options, "cli_options가 None이면 안 된다.")
        self.assertIn("image_path", cli_options, "gemini provider 시 cli_options에 image_path 키가 있어야 한다.")
        self.assertIsNotNone(cli_options["image_path"], "image_path 값이 None이면 안 된다.")

    def test_claude_enqueue_no_image_path(self):
        """provider='claude' 시 enqueue()의 cli_options에 image_path 키가 없음."""
        calls = self._run_classification_with_mock(provider="claude", file_id=2)

        self.assertTrue(len(calls) > 0, "enqueue()가 호출돼야 한다.")
        cli_options = calls[0].get("cli_options")
        # claude는 exec_mode 등 Claude CLI 전용 옵션 사용 — image_path 없어야 함
        if cli_options is not None:
            self.assertNotIn(
                "image_path", cli_options,
                "claude provider 시 cli_options에 image_path가 없어야 한다."
            )

    def test_gemini_provider_field_is_gemini(self):
        """provider='gemini' 시 enqueue() 호출 시 provider 필드가 'gemini'."""
        calls = self._run_classification_with_mock(provider="gemini", file_id=3)

        self.assertTrue(len(calls) > 0)
        self.assertEqual(calls[0].get("provider"), "gemini")


if __name__ == "__main__":
    unittest.main(verbosity=2)
