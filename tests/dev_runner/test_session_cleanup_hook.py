from unittest.mock import patch

from tests.dev_runner import conftest as dev_runner_conftest


def test_pytest_sessionfinish_runs_cleanup():
    with patch.object(dev_runner_conftest, "_cleanup_session_test_worktrees") as mocked:
        dev_runner_conftest.pytest_sessionfinish(object(), 0)

    mocked.assert_called_once()


def test_pytest_sessionfinish_ignores_cleanup_failures():
    with patch.object(
        dev_runner_conftest,
        "_cleanup_session_test_worktrees",
        side_effect=RuntimeError("boom"),
    ):
        dev_runner_conftest.pytest_sessionfinish(object(), 0)


def test_pytest_sessionfinish_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_DISABLE_SESSION_CLEANUP", "1")
    with patch.object(dev_runner_conftest, "_cleanup_session_test_worktrees") as mocked:
        dev_runner_conftest.pytest_sessionfinish(object(), 0)

    mocked.assert_not_called()
