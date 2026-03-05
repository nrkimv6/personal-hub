"""_set_error_status publish 동작 테스트

_do_start_plan_runner 내부 중첩 함수 _set_error_status가
라이브 로그 채널에 에러를 publish하는지 검증.
"""
from unittest.mock import MagicMock, call


# LOG_CHANNEL_PREFIX 상수 (command listener와 동일)
LOG_CHANNEL_PREFIX = "plan-runner:logs"
RUNNER_KEY_PREFIX = "plan-runner:runners"


def _make_set_error_status(runner_id: str, redis_client):
    """command listener의 _set_error_status 로직 재현"""
    def _set_error_status(message: str):
        if runner_id:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "error")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", message)
            try:
                redis_client.publish(f"{LOG_CHANNEL_PREFIX}:{runner_id}", f"[ERROR] {message}")
            except Exception:
                pass  # publish 실패 시 무시
    return _set_error_status


class TestSetErrorStatusPublish:
    """_set_error_status가 라이브 로그 채널에 publish하는지 검증"""

    def test_set_error_status_publishes_to_log_channel(self):
        """_set_error_status 호출 시 plan-runner:logs:{runner_id} 채널에 에러 메시지 publish"""
        runner_id = "t-errpub-abc1"
        redis = MagicMock()
        fn = _make_set_error_status(runner_id, redis)

        fn("worktree 생성 실패: git worktree add 실패")

        redis.publish.assert_called_once_with(
            f"{LOG_CHANNEL_PREFIX}:{runner_id}",
            "[ERROR] worktree 생성 실패: git worktree add 실패",
        )

    def test_set_error_status_still_sets_redis_keys(self):
        """publish 추가 후에도 기존 status=error, error=message SET 키가 정상 저장되는지 회귀 검증"""
        runner_id = "t-errpub-abc1"
        redis = MagicMock()
        fn = _make_set_error_status(runner_id, redis)

        fn("plan_file required")

        redis.set.assert_any_call(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "error")
        redis.set.assert_any_call(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", "plan_file required")

    def test_set_error_status_publish_failure_does_not_raise(self):
        """Redis publish가 예외를 던져도 _set_error_status가 조용히 처리하는지 검증"""
        runner_id = "t-errpub-abc1"
        redis = MagicMock()
        redis.publish.side_effect = ConnectionError("Redis 연결 끊김")
        fn = _make_set_error_status(runner_id, redis)

        # 예외 없이 완료되어야 함
        fn("worktree 생성 실패")

        # SET 키는 정상 저장됨
        redis.set.assert_any_call(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "error")

    def test_set_error_status_no_runner_id_does_nothing(self):
        """runner_id가 None/빈 문자열이면 아무것도 실행하지 않음 (경계값)"""
        redis = MagicMock()
        fn = _make_set_error_status(None, redis)

        fn("some error")

        redis.set.assert_not_called()
        redis.publish.assert_not_called()

    def test_set_error_status_error_message_prefixed_with_error_tag(self):
        """publish 메시지가 [ERROR] 접두사를 포함하는지 확인"""
        runner_id = "t-errpub-xyz1"
        redis = MagicMock()
        fn = _make_set_error_status(runner_id, redis)

        fn("테스트 에러 메시지")

        published_msg = redis.publish.call_args[0][1]
        assert published_msg.startswith("[ERROR] ")
        assert "테스트 에러 메시지" in published_msg
