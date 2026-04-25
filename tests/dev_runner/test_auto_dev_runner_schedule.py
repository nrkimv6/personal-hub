"""auto_dev_runner_schedule 단위 테스트."""
import json
import pytest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.modules.dev_runner.schedulers.auto_dev_runner_schedule import (
    _get_plan_date,
    _get_plan_status,
    _collect_eligible_plans,
)


# ── _get_plan_date ─────────────────────────────────────────────────────────────

def test_get_plan_date_R_valid_filename():
    """정상 날짜 파일명 → date 반환"""
    p = Path("2026-04-25_my-plan.md")
    result = _get_plan_date(p)
    assert result == date(2026, 4, 25)


def test_get_plan_date_B_no_date_prefix():
    """날짜 없는 파일명 → None"""
    p = Path("my-plan-no-date.md")
    assert _get_plan_date(p) is None


def test_get_plan_date_E_malformed_date():
    """잘못된 날짜 형식 → None"""
    p = Path("9999-99-99_bad-date.md")
    assert _get_plan_date(p) is None


# ── _get_plan_status ───────────────────────────────────────────────────────────

def test_get_plan_status_R_found(tmp_path):
    """상태 필드 존재 → 값 반환"""
    p = tmp_path / "plan.md"
    p.write_text("> 상태: 초안\n\n# Title\n", encoding="utf-8")
    assert _get_plan_status(p) == "초안"


def test_get_plan_status_B_missing(tmp_path):
    """상태 필드 없음 → None"""
    p = tmp_path / "plan.md"
    p.write_text("# Title\n", encoding="utf-8")
    assert _get_plan_status(p) is None


def test_get_plan_status_E_nonexistent(tmp_path):
    """존재하지 않는 파일 → None"""
    p = tmp_path / "missing.md"
    assert _get_plan_status(p) is None


# ── _collect_eligible_plans ────────────────────────────────────────────────────

def _make_plan(plans_dir: Path, date_str: str, *, auto_run: bool = True,
               scope: str = "tc", status: str = "초안",
               auto_run_status: str = "") -> Path:
    name = f"{date_str}_test-plan.md"
    p = plans_dir / name
    lines = [f"> auto_run: {'true' if auto_run else 'false'}", f"> auto_run_scope: {scope}"]
    if auto_run_status:
        lines.append(f"> auto_run_status: {auto_run_status}")
    lines += ["", f"> 상태: {status}", "", "# Title", ""]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_collect_R_yesterday_plan_picked(tmp_path):
    """전일 plan + auto_run:true + 초안 → 수집"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    plan = _make_plan(tmp_path, str(yesterday))

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", tmp_path):
        result = _collect_eligible_plans(today)

    assert plan in result


def test_collect_R_day_before_picked(tmp_path):
    """전전일 plan → 수집"""
    today = date(2026, 4, 26)
    day_before = today - timedelta(days=2)
    plan = _make_plan(tmp_path, str(day_before))

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", tmp_path):
        result = _collect_eligible_plans(today)

    assert plan in result


def test_collect_E_already_run_skip(tmp_path):
    """auto_run_status 있음 → 수집 제외"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    _make_plan(tmp_path, str(yesterday), auto_run_status="completed")

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", tmp_path):
        result = _collect_eligible_plans(today)

    assert result == []


def test_collect_E_auto_run_false_skip(tmp_path):
    """auto_run:false → 수집 제외"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    _make_plan(tmp_path, str(yesterday), auto_run=False)

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", tmp_path):
        result = _collect_eligible_plans(today)

    assert result == []


def test_collect_E_completed_status_skip(tmp_path):
    """status=구현완료 → 수집 제외"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    _make_plan(tmp_path, str(yesterday), status="구현완료")

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", tmp_path):
        result = _collect_eligible_plans(today)

    assert result == []


def test_collect_B_3day_old_skip(tmp_path):
    """3일 전 plan → 수집 제외 (전일/전전일만 대상)"""
    today = date(2026, 4, 26)
    three_days_ago = today - timedelta(days=3)
    _make_plan(tmp_path, str(three_days_ago))

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", tmp_path):
        result = _collect_eligible_plans(today)

    assert result == []


def test_collect_B_nonexistent_plans_dir(tmp_path):
    """plans 디렉토리 없음 → 빈 리스트"""
    missing = tmp_path / "nonexistent"
    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", missing):
        result = _collect_eligible_plans(date.today())
    assert result == []


def test_collect_R_검토완료_status_picked(tmp_path):
    """status=검토완료 → 수집 포함"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    plan = _make_plan(tmp_path, str(yesterday), status="검토완료")

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", tmp_path):
        result = _collect_eligible_plans(today)

    assert plan in result
