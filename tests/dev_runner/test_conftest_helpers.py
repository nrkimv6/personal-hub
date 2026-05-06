import hashlib
import inspect

from tests.dev_runner import conftest_e2e
from tests.dev_runner.conftest_e2e import FIXTURES_DIR, copy_fixture_plan_to_tmp


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_copy_fixture_plan_to_tmp_does_not_mutate_source(tmp_path):
    src = FIXTURES_DIR / "test_minimal_plan.md"
    before = _sha256(src)

    copied = copy_fixture_plan_to_tmp(tmp_path, "test_minimal_plan.md")

    assert copied != src
    assert copied.exists()
    assert _sha256(src) == before


def test_copy_fixture_plan_to_tmp_strips_merge_fields_by_default(tmp_path, monkeypatch):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    src = fixture_dir / "plan.md"
    src.write_text(
        "# Plan\n"
        "> branch: plan/test\n"
        "> worktree: .worktrees/test\n"
        "> worktree-owner: pytest\n"
        "\n"
        "- [ ] task\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(conftest_e2e, "FIXTURES_DIR", fixture_dir)

    copied = copy_fixture_plan_to_tmp(tmp_path, "plan.md")

    content = copied.read_text(encoding="utf-8")
    assert "> branch:" not in content
    assert "> worktree:" not in content
    assert "> worktree-owner:" not in content


def test_copy_fixture_plan_to_tmp_can_preserve_merge_fields(tmp_path, monkeypatch):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    src = fixture_dir / "plan.md"
    src.write_text(
        "# Plan\n"
        "> branch: plan/test\n"
        "> worktree: .worktrees/test\n"
        "> worktree-owner: pytest\n"
        "\n"
        "- [ ] task\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(conftest_e2e, "FIXTURES_DIR", fixture_dir)

    copied = copy_fixture_plan_to_tmp(tmp_path, "plan.md", strip_merge_fields=False)

    content = copied.read_text(encoding="utf-8")
    assert "> branch: plan/test" in content
    assert "> worktree: .worktrees/test" in content
    assert "> worktree-owner: pytest" in content


def test_cleanup_test_worktrees_does_not_write_fixture_files():
    source = inspect.getsource(conftest_e2e._cleanup_test_worktrees)

    assert "fixture_path.write_text" not in source
    assert "FIXTURES_DIR /" not in source
