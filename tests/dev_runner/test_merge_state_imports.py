from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN_RUNNER_DIR = ROOT / "scripts" / "plan_runner"


def test_stream_cleanup_uses_merge_state_constants_for_cleanup_decision():
    source = (PLAN_RUNNER_DIR / "_dr_stream_cleanup.py").read_text(encoding="utf-8")

    assert "from _dr_merge_state import" in source
    assert "MERGED" in source
    assert "MergeCleanupAction" in source
    assert "TERMINAL_STATUSES" in source
    assert 'state.merge_status == "merged"' not in source
    assert "state.merge_status == MERGED" in source
