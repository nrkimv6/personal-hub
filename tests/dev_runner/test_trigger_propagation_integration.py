"""T3 통합 TC: restart-after-merge trigger 전파 (Phase T3)

근본 원인 재현: _do_inline_merge()가 restart_after_merge 시 trigger를 전파하지 않아
새 러너가 trigger='unknown'으로 생성되는 버그.

수정 후 동작: trigger가 Redis에서 읽혀 새 command에 포함됨.

fakeredis(FakeServer 공유)로 실제 Redis 없이 통합 동작 검증.
_execute_merge_with_lock만 mock (merge 성공 시뮬레이션), 나머지는 실물 사용.
"""
import json
import sys
import pytest
import fakeredis
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

RUNNER_KEY_PREFIX = "plan-runner:runners"
COMMANDS_KEY = "plan-runner:commands"


@pytest.fixture
def shared_redis():
    """FakeServer 공유 fakeredis (통합 테스트용)"""
    server = fakeredis.FakeServer()
    r = fakeredis.FakeRedis(server=server, decode_responses=True)
    yield r
    r.close()


class TestRestartAfterMergeTriggerIntegration:
    """restart-after-merge trigger 전파 통합 테스트"""

    def test_restart_after_merge_trigger_preserved_integration(self, shared_redis):
        """T3: 실제 fakeredis에 runner 등록(trigger='user') + merge 성공 시뮬레이션
        → _do_inline_merge() 실행 → 새 command에 trigger='user' 포함 + plan_file/engine 보존
        """
        runner_id = "int-test-trigger-001"

        # Redis 상태 세팅 (실제 runner 시작 시나리오)
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/integration-test.md")
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", "claude")
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:fix_engine", "claude-mini")
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge", "1")

        # _execute_merge_with_lock mock (merge 성공 시뮬레이션, 실제 git 실행 방지)
        with patch("_dr_stream_cleanup._execute_merge_with_lock") as mock_merge, \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("_dr_plan_runner._pub_and_log"):
            from _dr_plan_runner import _do_inline_merge
            _do_inline_merge(runner_id, shared_redis)

        mock_merge.assert_called_once_with(runner_id, shared_redis, action_name="inline-merge")

        # COMMANDS_KEY에서 새 command 확인
        raw_commands = shared_redis.lrange(COMMANDS_KEY, 0, -1)
        assert len(raw_commands) == 1, f"새 command 1개 기대, 실제: {len(raw_commands)}개"

        command = json.loads(raw_commands[0])

        # trigger 전파 검증 (근본 원인 수정 확인)
        assert command["trigger"] == "user", (
            f"trigger 전파 실패! command['trigger']={command.get('trigger')!r} (기대: 'user')\n"
            f"  이 실패는 restart-after-merge trigger 소실 버그가 재발했음을 의미합니다."
        )

        # plan_file, engine 보존 검증
        assert command["plan_file"] == "docs/plan/integration-test.md"
        assert command["engine"] == "claude"
        assert command["fix_engine"] == "claude-mini"
        assert command["action"] == "run"

        # restart_after_merge 플래그가 삭제됐는지 확인 (중복 실행 방지)
        flag = shared_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge")
        assert flag is None, f"restart_after_merge 플래그가 삭제되지 않음: {flag!r}"

    def test_restart_after_merge_trigger_none_skips_integration(self, shared_redis):
        """T3: trigger 소실(None) 상황에서 restart_after_merge 발동 시 새 command 미생성
        → 비정상 unknown trigger 러너 생성 방지 확인
        """
        runner_id = "int-test-trigger-002"

        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")
        shared_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge", "1")
        # trigger 키 미설정 (소실 시나리오)

        with patch("_dr_stream_cleanup._execute_merge_with_lock"), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("_dr_plan_runner._pub_and_log"):
            from _dr_plan_runner import _do_inline_merge
            _do_inline_merge(runner_id, shared_redis)

        raw_commands = shared_redis.lrange(COMMANDS_KEY, 0, -1)
        assert len(raw_commands) == 0, (
            f"trigger 소실 시 새 command를 생성하면 안 됨. 생성된 command: {raw_commands}"
        )
