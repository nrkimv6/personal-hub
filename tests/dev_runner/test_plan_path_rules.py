"""공통 plan/archive/history 경로 규칙 단위 테스트."""

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _dr_plan_paths import (
    PathRuleError,
    classify_plan_stage,
    is_reserved_plan_status,
    resolve_plan_target,
)


def test_resolve_common_plan_to_common_archive_R(tmp_path):
    plan = tmp_path / "common" / "docs" / "plan" / "2026-04-03_test.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("> 상태: 구현중\n", encoding="utf-8")

    resolved = resolve_plan_target(plan, purpose="archive")
    assert resolved.target_kind == "archive"
    assert resolved.rule_id == "common_plan_archive"
    assert resolved.target.parts[-4:] == ("common", "docs", "archive", "2026-04-03_test.md")


def test_resolve_project_plan_to_archive_R(tmp_path):
    plan = tmp_path / "docs" / "plan" / "2026-04-03_test.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("> 상태: 구현중\n", encoding="utf-8")

    resolved = resolve_plan_target(plan, purpose="archive")
    assert resolved.target_kind == "archive"
    assert resolved.rule_id == "project_plan_archive"
    assert resolved.target.parts[-3:] == ("docs", "archive", "2026-04-03_test.md")


def test_resolve_plans_worktree_plan_to_archive_R(tmp_path):
    plan = tmp_path / ".worktrees" / "plans" / "docs" / "plan" / "2026-04-03_test.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("> 상태: 구현중\n", encoding="utf-8")

    resolved = resolve_plan_target(plan, purpose="archive")
    assert resolved.target_kind == "archive"
    assert resolved.rule_id == "plans_worktree_archive"
    assert resolved.target.parts[-5:] == (".worktrees", "plans", "docs", "archive", "2026-04-03_test.md")


def test_resolve_auto_plan_to_history_R(tmp_path):
    plan = tmp_path / "docs" / "plan" / "2026-04-03_auto-next-check.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("> 상태: 구현중\n", encoding="utf-8")

    resolved = resolve_plan_target(plan, purpose="archive")
    assert resolved.target_kind == "history"
    assert resolved.rule_id == "auto_history"
    assert resolved.target.parts[-3:] == ("docs", "history", "2026-04-03_auto-next-check.md")


def test_resolve_outside_docs_plan_raises_E(tmp_path):
    not_plan = tmp_path / "notes" / "x.md"
    not_plan.parent.mkdir(parents=True)
    not_plan.write_text("x", encoding="utf-8")

    with pytest.raises(PathRuleError):
        resolve_plan_target(not_plan, purpose="archive")


def test_classify_plan_stage_R():
    assert classify_plan_stage("검토대기") == "pre_review"
    assert classify_plan_stage("예약대기") == "pre_review"
    assert classify_plan_stage("검토완료") == "post_review"
    assert classify_plan_stage("구현중") == "post_review"


def test_is_reserved_plan_status_R():
    assert is_reserved_plan_status("예약대기") is True
    assert is_reserved_plan_status("검토대기") is False


def test_classify_plan_stage_unknown_B():
    assert classify_plan_stage("알수없음") == "unknown"
    assert classify_plan_stage("") == "unknown"
