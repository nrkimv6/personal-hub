from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.diagnostics.audit_mixed_scope_commits import (
    _collect_plan_keywords,
    _render_json,
    _render_markdown,
    audit_repo,
)


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, capture_output=True, check=True)


def _commit_all(path: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True, check=True)


def test_collect_plan_keywords_extracts_paths_and_backticks(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    plan = repo / "docs" / "plan" / "2026-04-13_example.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "\n".join(
            [
                "# fix: example",
                "",
                "- `app/modules/dev_runner/services/event_service.py`",
                "- `[route](frontend/src/routes/coupang/+page.svelte)`",
                "- `restart-all`",
            ]
        ),
        encoding="utf-8",
    )

    keywords = _collect_plan_keywords(plan)

    assert "app/modules/dev_runner/services/event_service.py" in keywords
    assert "frontend/src/routes/coupang/+page.svelte" in keywords
    assert "restart-all" in keywords


def test_audit_mixed_scope_right_flags_unplanned_event_service_change(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    plan = repo / "docs" / "plan" / "2026-04-13_example.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "\n".join(
            [
                "# fix: example",
                "",
                "- `frontend/src/routes/coupang/+page.svelte`",
                "- `docs/archive/2026-04-13_fix-coupang-monitoring-not-running.md`",
                "- `recovery_command`",
            ]
        ),
        encoding="utf-8",
    )

    code_file = repo / "app" / "modules" / "dev_runner" / "services" / "event_service.py"
    code_file.parent.mkdir(parents=True, exist_ok=True)
    code_file.write_text("runner_id = 'broken'\n", encoding="utf-8")

    _commit_all(repo, "fix: coupang recovery command")

    findings = audit_repo(repo, limit=5)

    assert findings, "mixed-scope finding should be detected"
    finding = findings[0]
    assert finding.sha
    assert finding.severity in {"P0", "P1"}
    assert "app/modules/dev_runner/services/event_service.py" in finding.changed_files
    assert any(doc.startswith("docs/plan/") for doc in finding.linked_docs)


def test_audit_mixed_scope_flags_touched_plan_scope_mismatch(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    plan = repo / "docs" / "plan" / "2026-04-13_loader_bootstrap.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "\n".join(
            [
                "# fix: loader bootstrap",
                "",
                "- `scripts/plan_runner/_dr_plan_runner.py`",
                "- `tests/dev_runner/test_plan_runner_loader_contract.py`",
                "- `bootstrap`",
            ]
        ),
        encoding="utf-8",
    )

    code_file = repo / "app" / "modules" / "dev_runner" / "services" / "event_service.py"
    code_file.parent.mkdir(parents=True, exist_ok=True)
    code_file.write_text("runner_id = 'broken'\n", encoding="utf-8")

    _commit_all(repo, "fix: dev-runner live SSE/status recovery")

    findings = audit_repo(repo, limit=5)

    assert findings, "touched plan scope mismatch should be detected"
    finding = findings[0]
    assert finding.sha
    assert any(doc.endswith("2026-04-13_loader_bootstrap.md") for doc in finding.linked_docs)
    assert "app/modules/dev_runner/services/event_service.py" in finding.changed_files


def test_audit_mixed_scope_flags_multi_domain_commit(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    plan = repo / "docs" / "plan" / "2026-04-13_broad_scope.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "\n".join(
            [
                "# fix: broad scope",
                "",
                "- `app/modules/dev_runner/services/event_service.py`",
                "- `frontend/src/routes/automation/+page.svelte`",
                "- `scripts/plan_runner/_dr_subprocess.py`",
            ]
        ),
        encoding="utf-8",
    )

    code_paths = [
        repo / "app" / "modules" / "dev_runner" / "services" / "event_service.py",
        repo / "frontend" / "src" / "routes" / "automation" / "+page.svelte",
        repo / "scripts" / "plan_runner" / "_dr_subprocess.py",
        repo / "tests" / "dev_runner" / "test_connection_leak_http.py",
    ]
    for path in code_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")

    _commit_all(repo, "test: broad multi domain audit sample")

    findings = audit_repo(repo, limit=5)

    assert findings, "multi-domain mixed-scope commit should be detected"
    finding = findings[0]
    assert finding.severity in {"P0", "P1"}
    assert any(doc.endswith("2026-04-13_broad_scope.md") for doc in finding.linked_docs)
    assert "frontend/src/routes/automation/+page.svelte" in finding.changed_files
    assert "scripts/plan_runner/_dr_subprocess.py" in finding.changed_files


def test_audit_mixed_scope_boundary_allows_doc_only_commit(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    plan = repo / "docs" / "plan" / "2026-04-13_doc_only.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# fix: doc only\n\n- `app/modules/dev_runner/services/event_service.py`\n", encoding="utf-8")

    _commit_all(repo, "docs: add plan note")

    findings = audit_repo(repo, limit=5)

    assert findings == []


def test_audit_mixed_scope_error_handles_missing_plan_file(tmp_path):
    missing = tmp_path / "missing.md"
    assert _collect_plan_keywords(missing) == set()


def test_audit_mixed_scope_reference_staged_mode_ignores_todo_md(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    todo = repo / "TODO.md"
    todo.write_text("- [ ] mixed scope note\n", encoding="utf-8")
    _commit_all(repo, "chore: seed repo")

    todo.write_text("- [ ] mixed scope note\n- [ ] stage only\n", encoding="utf-8")
    subprocess.run(["git", "add", "TODO.md"], cwd=repo, capture_output=True, check=True)

    findings = audit_repo(repo, staged=True)

    assert findings == []


def test_renderers_produce_json_and_markdown(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    plan = repo / "docs" / "plan" / "2026-04-13_example.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# fix: example\n", encoding="utf-8")
    _commit_all(repo, "docs: seed")

    findings = audit_repo(repo, limit=1)
    assert findings == []

    sample = []
    json_text = _render_json(sample)
    md_text = _render_markdown(sample)

    assert json.loads(json_text) == []
    assert "Mixed-Scope Commit Audit" in md_text
