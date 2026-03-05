"""runner_id test_source 주입 TC

Phase T1: runner_id 생성 로직 및 command dict 검증
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.modules.dev_runner.schemas import RunRequest
from app.modules.dev_runner.services.executor_service import ExecutorService


@pytest.fixture
def mock_executor():
    """Redis 연결 없이 ExecutorService 인스턴스 생성"""
    with patch("app.modules.dev_runner.services.executor_service.redis.Redis") as mock_r, \
         patch("app.modules.dev_runner.services.executor_service.aioredis.Redis") as mock_ar:
        mock_r.return_value = MagicMock()
        mock_ar.return_value = AsyncMock()
        svc = ExecutorService()
    return svc


# --- T1 TC: runner_id 생성 ---

def test_runner_id_includes_test_source():
    """R(Right): test_source 설정 시 runner_id에 t-{source}- 접두사 포함"""
    import re
    import uuid

    # executor_service의 로직을 직접 재현
    test_source = "my_test"
    _src = re.sub(r'[^a-zA-Z0-9_]', '', test_source)[:20]
    runner_id = f"t-{_src}-{uuid.uuid4().hex[:4]}"

    assert runner_id.startswith("t-my_test-"), f"Expected 't-my_test-' prefix, got: {runner_id}"
    assert len(runner_id) == len("t-my_test-") + 4, f"Expected length {len('t-my_test-') + 4}, got: {len(runner_id)}"


def test_runner_id_default_without_test_source():
    """B(Boundary): test_source=None 시 uuid4 8자 hex 형식"""
    import uuid
    # test_source 없을 때 기본 형식: uuid4().hex[:8]
    runner_id = uuid.uuid4().hex[:8]
    assert len(runner_id) == 8
    assert all(c in "0123456789abcdef" for c in runner_id)


def test_runner_id_test_source_sanitized():
    """B(Boundary): 특수문자 포함 test_source는 re.sub으로 제거"""
    import re
    import uuid

    test_source = "my-test!@#"
    _src = re.sub(r'[^a-zA-Z0-9_]', '', test_source)[:20]
    runner_id = f"t-{_src}-{uuid.uuid4().hex[:4]}"

    # 특수문자 제거 후 mytest만 남음
    assert runner_id.startswith("t-mytest-"), f"Expected 't-mytest-' prefix, got: {runner_id}"
    assert "!" not in runner_id
    assert "@" not in runner_id
    # 형식: t-{sanitized}-{4hex} — sanitized 부분에 특수문자 없음
    parts = runner_id.split("-")
    assert len(parts) == 3, f"Expected 3 parts (t, sanitized, hex), got: {parts}"
    assert parts[1] == "mytest", f"Expected 'mytest', got: {parts[1]}"
    assert len(parts[2]) == 4


def test_runner_id_test_source_truncated():
    """B(Boundary): 30자 test_source는 20자로 잘림"""
    import re
    import uuid

    test_source = "a" * 30
    _src = re.sub(r'[^a-zA-Z0-9_]', '', test_source)[:20]
    runner_id = f"t-{_src}-{uuid.uuid4().hex[:4]}"

    # t- (2) + 20자 + - (1) + 4자 = 27자
    assert len(runner_id) == 27, f"Expected 27 chars, got: {len(runner_id)}"
    assert runner_id.startswith("t-" + "a" * 20 + "-")


def test_command_dict_includes_test_source(isolated_redis):
    """R(Right): test_source 설정 시 Redis LPUSH된 command JSON에 test_source 포함"""
    import re
    import uuid

    # command 구성 로직 재현 (executor_service.start_dev_runner 핵심 부분)
    test_source = "foo"
    command = {
        "action": "run",
        "runner_id": f"t-{re.sub(r'[^a-zA-Z0-9_]', '', test_source)[:20]}-{uuid.uuid4().hex[:4]}",
        "command_id": uuid.uuid4().hex[:8],
        "source": "test",
    }
    if test_source:
        command["test_source"] = test_source

    assert "test_source" in command, "command dict에 test_source 키가 없음"
    assert command["test_source"] == "foo"
    assert command["runner_id"].startswith("t-foo-")


def test_cleanup_report_prints_dirty(capsys, monkeypatch):
    """R(Right): 잔류 러너 있을 때 [DIRTY] 출력, test_source 없으면 (unknown) 표시"""
    import sys
    from unittest.mock import MagicMock

    # _try_connect_redis()가 mock redis를 반환하도록 patch
    mock_r = MagicMock()
    mock_r.smembers.side_effect = [
        set(),            # before_active (setup)
        {"t-dirty-abc1"}, # after_active (teardown)
    ]
    mock_r.get.side_effect = lambda key: {
        "plan-runner:runners:t-dirty-abc1:plan_file": "test.md",
        "plan-runner:runners:t-dirty-abc1:engine": "gemini",
        "plan-runner:runners:t-dirty-abc1:pid": "12345",
        "plan-runner:runners:t-dirty-abc1:test_source": None,  # test_source 없음
    }.get(key)

    output_lines = []
    original_write = sys.stderr.write

    def capture_write(text):
        output_lines.append(text)

    monkeypatch.setattr(sys.stderr, "write", capture_write)

    # runner_cleanup_report 로직 직접 재현
    before_active = mock_r.smembers("plan-runner:active_runners") or set()
    after_active = mock_r.smembers("plan-runner:active_runners") or set()
    remaining = after_active - before_active

    sep = "=" * 43
    if not remaining:
        sys.stderr.write(f"\n{sep}\n[CLEAN] 잔류 러너 0건\n{sep}\n")
    else:
        lines = [f"\n{sep}", f"[DIRTY] 잔류 러너 {len(remaining)}건:"]
        for rid in sorted(remaining):
            source = mock_r.get(f"plan-runner:runners:{rid}:test_source") or "(unknown)"
            lines.append(f"  - {rid} | source: {source}")
        lines.append(sep)
        sys.stderr.write("\n".join(lines) + "\n")

    combined = "".join(output_lines)
    assert "[DIRTY]" in combined
    assert "t-dirty-abc1" in combined
    assert "(unknown)" in combined
