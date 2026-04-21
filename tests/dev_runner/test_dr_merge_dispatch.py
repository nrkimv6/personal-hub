import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from unittest.mock import MagicMock, patch

def test_exit_code_handlers_dispatch_success_R():
    from _dr_merge import _EXIT_CODE_HANDLERS, _handle_merge_success
    assert _EXIT_CODE_HANDLERS.get(0) is _handle_merge_success

def test_exit_code_handlers_dispatch_test_failed_R():
    from _dr_merge import _EXIT_CODE_HANDLERS, _handle_test_failed
    assert _EXIT_CODE_HANDLERS.get(2) is _handle_test_failed

def test_exit_code_handlers_dispatch_conflict_R():
    from _dr_merge import _EXIT_CODE_HANDLERS, _handle_conflict
    assert _EXIT_CODE_HANDLERS.get(3) is _handle_conflict

def test_exit_code_handlers_dispatch_else_R():
    from _dr_merge import _EXIT_CODE_HANDLERS
    assert _EXIT_CODE_HANDLERS.get(1) is None  # else는 partial로 처리

def test_exit_code_handlers_dispatch_unknown_B():
    from _dr_merge import _EXIT_CODE_HANDLERS
    assert _EXIT_CODE_HANDLERS.get(99) is None  # 폴백은 runtime에서 partial로


def test_build_merge_completed_sentinel_conflict_like_success_still_fails_B():
    from _dr_merge import _build_merge_completed_sentinel

    sentinel = _build_merge_completed_sentinel({"success": True, "merge_status": "conflict"})
    assert sentinel == "__MERGE_COMPLETED::merge_failed__"
