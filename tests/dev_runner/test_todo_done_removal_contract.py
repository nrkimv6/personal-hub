from pathlib import Path

import pytest

from app.modules.dev_runner.services.plan_done_service import PlanDoneService
from app.modules.dev_runner.services.plan_service import PlanService


def _plans_todo_path(project_root: Path) -> Path:
    path = project_root / ".worktrees" / "plans" / "TODO.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize("service_cls", [PlanService, PlanDoneService])
def test_update_todo_done_removes_exact_title_without_substring_collision(tmp_path, service_cls):
    todo_path = _plans_todo_path(tmp_path)
    todo_path.write_text(
        "# TODO\n\n"
        "- [ ] HTTP test plan\n"
        "- [ ] HTTP test plan followup\n",
        encoding="utf-8",
    )

    service_cls._update_todo_done(tmp_path, "HTTP test plan")

    content = todo_path.read_text(encoding="utf-8")
    assert "- [ ] HTTP test plan\n" not in content
    assert "- [ ] HTTP test plan followup\n" in content


@pytest.mark.parametrize("service_cls", [PlanService, PlanDoneService])
def test_update_todo_done_uses_plan_path_when_todo_label_differs(tmp_path, service_cls):
    plan_path = Path("docs/plan/2026-04-29_fix-live-done-http-todo-removal-contract.md")
    todo_path = _plans_todo_path(tmp_path)
    todo_path.write_text(
        "# TODO\n\n"
        "- [ ] short label ([plan](docs/plan/2026-04-29_fix-live-done-http-todo-removal-contract.md))\n"
        "- [ ] short label followup ([plan](docs/plan/2026-04-29_fix-live-done-http-todo-removal-contract-followup.md))\n",
        encoding="utf-8",
    )

    service_cls._update_todo_done(tmp_path, "Full plan title", plan_path)

    content = todo_path.read_text(encoding="utf-8")
    assert "fix-live-done-http-todo-removal-contract.md" not in content
    assert "fix-live-done-http-todo-removal-contract-followup.md" in content


@pytest.mark.parametrize("service_cls", [PlanService, PlanDoneService])
def test_update_todo_done_matches_bounded_stem_without_prefix_collision(tmp_path, service_cls):
    plan_path = Path("docs/plan/2026-04-29_exact-stem.md")
    todo_path = _plans_todo_path(tmp_path)
    todo_path.write_text(
        "# TODO\n\n"
        "- [ ] generated label (from: plan/2026-04-29_exact-stem)\n"
        "- [ ] generated label followup (from: plan/2026-04-29_exact-stem-followup)\n",
        encoding="utf-8",
    )

    service_cls._update_todo_done(tmp_path, "Full plan title", plan_path)

    content = todo_path.read_text(encoding="utf-8")
    assert "from: plan/2026-04-29_exact-stem)" not in content
    assert "from: plan/2026-04-29_exact-stem-followup)" in content
