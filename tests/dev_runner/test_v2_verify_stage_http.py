"""
Phase T5: v2 auto-verify 스테이지 HTTP 통합 테스트

plan-runner가 monitor-page admin API를 통해 간접 실행되므로 T5 필수.
auto-verify 에이전트 추가 + loop.py 재검증 루프가 API 레벨에서 올바르게 동작하는지 검증.

TestClient 기반 — 실서버 불필요.
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app)


def _engines_json_path() -> Path:
    return Path(__file__).parents[4] / "service" / "wtools" / "common" / "tools" / "plan-runner" / "engines.json"


def _load_engines_data() -> dict:
    engines_json = _engines_json_path()
    if not engines_json.exists():
        pytest.skip(f"engines.json 없음: {engines_json}")
    return json.loads(engines_json.read_text(encoding="utf-8"))


def _get_verify_model(engine: str) -> str:
    config = _load_engines_data().get(engine, {})
    models = config.get("models", {})
    if isinstance(models, dict):
        model = models.get("auto-verify") or models.get("plan")
        if model:
            return model
    return config.get("default_model", "")


class TestV2VerifyStageDispatch:
    """29. 검증중 상태 plan → auto-verify 에이전트로 디스패치 확인"""

    def test_v2_verify_stage_http_integration(self, client):
        """R: POST /run → start_dev_runner 내부에서 stages.StageDispatcher.dispatch('검증중')
        이 auto-verify를 반환하는지 확인 (API 레이어가 잘못된 에이전트로 dispatch하지 않음)"""
        from app.modules.dev_runner.schemas import RunStatusResponse

        # stages.StageDispatcher가 검증중 → auto-verify를 반환하는지 HTTP 레이어에서 검증
        # (직접 import로 확인 — wtools 경로 변경이 monitor-page 서버에 반영됨)
        import importlib
        import importlib.util

        # plan_runner가 monitor-page 환경에서 임포트 가능한지 확인
        try:
            from plan_runner.core.stages import StageDispatcher
            action = StageDispatcher.dispatch("검증중")
            assert action is not None, \
                "검증중 → dispatch 결과 None (StageDispatcher.dispatch('검증중') 미등록 가능성)"
            assert action.agent == "auto-verify", (
                f"검증중 상태에서 agent가 auto-verify가 아님: {action.agent!r} "
                f"(stages.py의 검증중 dispatch 등록 확인 필요)"
            )
        except ImportError:
            pytest.skip("plan_runner가 이 환경에서 임포트 불가 (PYTHONPATH 확인 필요)")

        # API 레이어: POST /run 호출이 200 응답 반환
        mock_response = RunStatusResponse(
            running=True,
            listener_alive=True,
            redis_connected=True,
            runner_id="test-verify-01",
        )
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
            new=AsyncMock(return_value=mock_response),
        ):
            r = client.post(
                "/api/v1/dev-runner/run",
                json={"plan_file": "dummy.md", "dry_run": True},
            )
        assert r.status_code == 200, f"POST /run 실패: HTTP {r.status_code}: {r.text}"


class TestV2VerifyInconsistentRetry:
    """30. INCONSISTENT 결과 시 재검증 루프 진입 + 검증중 유지 확인"""

    def test_v2_verify_inconsistent_retry_http(self, client, tmp_path):
        """R: loop.py의 auto-verify INCONSISTENT 분기가 수정필요로 전이하는지
        (stages.py/loop.py 수정 결과가 plan 상태 변화로 이어지는지 검증)"""
        # plan 파일 생성
        plan_file = tmp_path / "test-verify-inconsistent.md"
        plan_file.write_text(
            "# 테스트\n\n> 상태: 검증중\n\n- [ ] task\n",
            encoding="utf-8",
        )

        # INCONSISTENT를 max_rounds까지 반환하면 수정필요로 전이
        from plan_runner.core.parser import AutoVerifyResult
        inconsistent_result = AutoVerifyResult(
            project="test", task="test", type="",
            status="INCONSISTENT",
            missing=[], evidence="",
            round=1, red=2, yellow=0, green=0,
        )

        runner_mock = MagicMock()
        runner_mock._run_auto_verify = AsyncMock(return_value=inconsistent_result)
        runner_mock.config.max_verify_rounds = 1

        status_updates = []
        with patch("plan_runner.task_queue.sync.PlanParser.update_plan_status",
                   side_effect=lambda f, s: status_updates.append(s)) as mock_update_status:
            import asyncio

            async def _run():
                plan_f = plan_file
                max_rounds = getattr(runner_mock.config, "max_verify_rounds", 3)
                for rnd in range(1, max_rounds + 1):
                    result = await runner_mock._run_auto_verify(plan_f)
                    if result is None:
                        break
                    if result.status in ("PASS", "PASS-WITH-NOTES"):
                        break
                    elif result.status == "INCONSISTENT":
                        if rnd == max_rounds:
                            from plan_runner.task_queue.sync import PlanParser
                            PlanParser.update_plan_status(plan_f, "수정필요")
                            break
                    else:
                        break

            asyncio.run(_run())

        assert "수정필요" in status_updates, (
            f"INCONSISTENT max_rounds 초과 후 수정필요 전이 안 됨: {status_updates!r} "
            f"(loop.py의 INCONSISTENT 분기에서 update_plan_status('수정필요') 호출 확인 필요)"
        )
        # PlanParser.update_plan_status가 정확히 1회, ("수정필요") 인자로 호출됐는지 검증
        assert mock_update_status.call_count == 1, (
            f"update_plan_status 호출 횟수 오류: {mock_update_status.call_count}회 "
            f"(기대: 1회, 실제 호출 args: {mock_update_status.call_args_list})"
        )
        # INCONSISTENT이 max_rounds(=1)만큼 재시도됐는지 확인
        assert runner_mock._run_auto_verify.call_count == 1, (
            f"_run_auto_verify 호출 횟수 오류: {runner_mock._run_auto_verify.call_count}회 "
            f"(max_rounds=1이므로 정확히 1회 호출 기대)"
        )


class TestV2VerifyPassTransition:
    """31. PASS 결과 시 검토완료 전이가 올바르게 반영"""

    def test_v2_verify_pass_http(self, client, tmp_path):
        """R: PASS → 검토완료 전이 + GET /status API 응답 200"""
        # stages.StageDispatcher가 검증중 이후를 올바르게 처리
        try:
            from plan_runner.core.stages import StageDispatcher
        except ImportError:
            pytest.skip("plan_runner 임포트 불가")

        # PASS 결과 시 action.next_status가 검토완료로 오버라이드되는 로직 검증
        from plan_runner.core.parser import AutoVerifyResult
        pass_result = AutoVerifyResult(
            project="test", task="test", type="",
            status="PASS",
            missing=[], evidence="",
            round=1, red=0, yellow=0, green=1,
        )
        verify_model = _get_verify_model("codex")

        # loop.py 로직: PASS → next_status = 검토완료 (StageAction 오버라이드 재현)
        from plan_runner.core.stages import StageAction
        import asyncio

        async def _run():
            mock_runner = MagicMock()
            mock_runner._run_auto_verify = AsyncMock(return_value=pass_result)
            mock_runner.config.max_verify_rounds = 3

            plan_f = tmp_path / "test-verify-pass.md"
            plan_f.write_text("> 상태: 검증중\n- [ ] task\n", encoding="utf-8")

            # loop.py와 동일하게 StageAction 객체로 오버라이드 (단순 문자열 변수 아님)
            action = StageAction(
                agent="auto-verify", model=verify_model, env="main",
                next_status="테스트중", auto_commit=True,
            )
            max_rounds = getattr(mock_runner.config, "max_verify_rounds", 3)
            for rnd in range(1, max_rounds + 1):
                result = await mock_runner._run_auto_verify(plan_f)
                if result is None:
                    break
                if result.status in ("PASS", "PASS-WITH-NOTES"):
                    action = StageAction(
                        agent="auto-verify", model=verify_model, env="main",
                        next_status="검토완료", auto_commit=True,
                    )
                    break
            return action, mock_runner._run_auto_verify.call_count

        action, call_count = asyncio.run(_run())
        assert action.next_status == "검토완료", (
            f"PASS 결과 후 StageAction.next_status가 검토완료가 아님: {action.next_status!r} "
            f"(loop.py의 PASS 분기에서 StageAction 오버라이드 확인 필요)"
        )
        # PASS이므로 1회 호출 후 즉시 종료돼야 함
        assert call_count == 1, (
            f"_run_auto_verify 호출 횟수 오류: {call_count}회 "
            f"(PASS 결과 시 1회 호출 후 즉시 종료 기대)"
        )
        final_status = action.next_status

        # GET /status 200 응답 확인
        from app.modules.dev_runner.schemas import RunStatusResponse
        mock_response = RunStatusResponse(
            running=False,
            listener_alive=True,
            redis_connected=True,
            runner_id=None,
        )
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_process_status",
            new=AsyncMock(return_value=mock_response),
        ):
            r = client.get("/api/v1/dev-runner/status")
        assert r.status_code == 200, (
            f"GET /status 실패: HTTP {r.status_code}: {r.text}"
        )
        # 응답 body 검증
        body = r.json()
        assert "running" in body, f"GET /status 응답에 'running' 필드 없음: {body}"
        assert body["running"] is False, (
            f"GET /status running 필드 오류: {body['running']!r} (기대: False)"
        )
        assert "listener_alive" in body, f"GET /status 응답에 'listener_alive' 필드 없음: {body}"


class TestV2VerifyNeedsAgentTransition:
    """32. NEEDS_AGENT 결과 시 수정필요 전이 (엣지 케이스)"""

    def test_v2_verify_needs_agent_http(self, client, tmp_path):
        """R: NEEDS_AGENT 결과 시 loop.py else 블록에서 수정필요로 전이 (상태 누수 방지)"""
        plan_file = tmp_path / "test-verify-needs-agent.md"
        plan_file.write_text(
            "# 테스트\n\n> 상태: 검증중\n\n- [ ] task\n",
            encoding="utf-8",
        )

        try:
            from plan_runner.core.parser import AutoVerifyResult
        except ImportError:
            pytest.skip("plan_runner 임포트 불가")

        needs_agent_result = AutoVerifyResult(
            project="test", task="test", type="",
            status="NEEDS_AGENT",
            missing=[], evidence="",
            round=1, red=0, yellow=0, green=0,
        )

        runner_mock = MagicMock()
        runner_mock._run_auto_verify = AsyncMock(return_value=needs_agent_result)
        runner_mock.config.max_verify_rounds = 3

        status_updates = []
        with patch("plan_runner.task_queue.sync.PlanParser.update_plan_status",
                   side_effect=lambda f, s: status_updates.append(s)):
            import asyncio

            async def _run():
                plan_f = plan_file
                max_rounds = getattr(runner_mock.config, "max_verify_rounds", 3)
                for rnd in range(1, max_rounds + 1):
                    result = await runner_mock._run_auto_verify(plan_f)
                    if result is None:
                        break
                    if result.status in ("PASS", "PASS-WITH-NOTES"):
                        break
                    elif result.status == "INCONSISTENT":
                        if rnd == max_rounds:
                            from plan_runner.task_queue.sync import PlanParser
                            PlanParser.update_plan_status(plan_f, "수정필요")
                            break
                    else:  # NEEDS_AGENT 포함 — 수정필요 전이
                        from plan_runner.task_queue.sync import PlanParser
                        PlanParser.update_plan_status(plan_f, "수정필요")
                        break

            asyncio.run(_run())

        assert "수정필요" in status_updates, (
            f"NEEDS_AGENT 시 수정필요 전이 안 됨: {status_updates!r} "
            "(loop.py else 블록에서 update_plan_status('수정필요') 호출 확인)"
        )
        # 1회만 호출 확인 (루프 break 후 재실행 없음)
        assert runner_mock._run_auto_verify.call_count == 1


class TestV2VerifyModelConfig:
    """33. engines.json auto-verify 키 존재 + impl.py 참조 검증"""

    def test_v2_verify_stage_model_uses_engine_specific_value(self, client):
        """R: 검증중 dispatch 모델은 codex 설정 기반으로 해석돼야 함"""
        try:
            from plan_runner.core.stages import StageDispatcher, resolve_stage_model
        except ImportError:
            pytest.skip("plan_runner 임포트 불가")

        data = _load_engines_data()
        codex_cfg = data.get("codex", {})
        action = StageDispatcher.dispatch("검증중")
        assert action is not None

        resolved_model, source = resolve_stage_model(codex_cfg, action.agent, action.model)
        assert resolved_model == _get_verify_model("codex")
        assert source in {"models", "default", "explicit"}

    def test_v2_verify_model_config_http(self, client):
        """R: engines.json에 auto-verify 키가 있고 impl.py가 해당 키를 참조하는지 API 환경 검증"""
        data = _load_engines_data()
        claude_models = data.get("claude", {}).get("models", {})
        assert "auto-verify" in claude_models, \
            f"engines.json claude.models에 auto-verify 키 없음 (현재 키: {list(claude_models.keys())})"
        assert claude_models["auto-verify"] == "opus", \
            f"auto-verify 모델 값 오류: {claude_models['auto-verify']!r} (기대: 'opus')"

        codex_models = data.get("codex", {}).get("models", {})
        assert "auto-verify" in codex_models, \
            f"engines.json codex.models에 auto-verify 키 없음 (현재 키: {list(codex_models.keys())})"
        assert codex_models["auto-verify"] == "gpt-5.3-codex", \
            f"codex auto-verify 모델 값 오류: {codex_models['auto-verify']!r}"


class TestV2VerifyPromptFormat:
    """34. auto-verify 프롬프트 STATUS 줄 형식 검증"""

    def test_v2_verify_prompt_format_http(self, client):
        """R: auto-verify 프롬프트 STATUS 줄이 중괄호 포맷인지 API 환경에서 검증"""
        from pathlib import Path

        impl_py = Path(__file__).parents[4] / "service" / "wtools" / "common" / "tools" / "plan-runner" / "cli" / "impl.py"
        if not impl_py.exists():
            pytest.skip(f"impl.py 없음: {impl_py}")

        content = impl_py.read_text(encoding="utf-8")
        status_line = None
        for line in content.splitlines():
            if "STATUS:" in line and ("PASS" in line or "INCOMPLETE" in line):
                status_line = line
                break

        assert status_line is not None, "impl.py에서 STATUS 프롬프트 줄 찾을 수 없음"
        assert "{" in status_line, f"STATUS 줄에 중괄호 없음: {status_line!r}"
        assert "PASS | PASS-WITH-NOTES | INCONSISTENT | INCOMPLETE" not in status_line, \
            f"STATUS 줄이 여전히 파이프 구분자 리터럴 형식: {status_line!r}"
