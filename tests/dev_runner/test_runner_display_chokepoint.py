from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_stale_labels_use_backend_display_fields():
    targets = [
        ROOT / "frontend/src/lib/components/dev-runner/RunnerInstanceTab.svelte",
        ROOT / "frontend/src/lib/components/dev-runner/RunStatusBar.svelte",
    ]

    for target in targets:
        source = target.read_text(encoding="utf-8")
        assert "displaySecondary" in source or "display_secondary" in source
        assert "hideStaleBranchBadge" in source or "hide_stale_branch_badge" in source

    instance_source = targets[0].read_text(encoding="utf-8")
    status_source = targets[1].read_text(encoding="utf-8")
    stale_badge_body = re.search(r"function staleBadgeLabel\(\): string \| null \{(?P<body>.*?)\n\t\}", instance_source, re.S)
    stale_status_body = re.search(r"function resolveStaleLabel\(runner: RunnerTab\): string \| null \{(?P<body>.*?)\n\t\}", status_source, re.S)
    assert stale_badge_body
    assert stale_status_body
    assert "branchExists" not in stale_badge_body.group("body")
    assert "worktreeExists" not in stale_badge_body.group("body")
    assert "runner.branch_exists" not in stale_status_body.group("body")
    assert "runner.worktree_exists" not in stale_status_body.group("body")


def test_backend_runner_surfaces_build_display_state():
    for relative in [
        "app/modules/dev_runner/services/executor_service.py",
        "app/modules/dev_runner/services/event_payload.py",
    ]:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "build_runner_read_model(" in source
        assert "build_display_state(" in source
        assert '"display_state"' in source or "display_state=" in source
