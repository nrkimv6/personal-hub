"""auto_dev_runner 통합 시뮬레이션 TC (T3).

실제 파일시스템 + 임시 plan 파일 사용.
executor_service.start_dev_runner만 mock.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from app.modules.dev_runner.schedulers.auto_dev_runner_schedule import (
    _scan_and_run_plans,
    _collect_eligible_plans,
)
from app.modules.dev_runner.services.plan_frontmatter import read_auto_run_meta


def _make_plan_file(plans_dir: Path, date_str: str, scope: str = "tc") -> Path:
    name = f"{date_str}_integration-test-plan.md"
    p = plans_dir / name
    content = (
        f"> auto_run: true\n"
        f"> auto_run_scope: {scope}\n"
        f"> 상태: 초안\n"
        f"\n# Integration Test Plan\n"
        f"\n- [ ] `tests/test_foo.py`: 테스트 추가\n"
    )
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def plans_dir(tmp_path):
    d = tmp_path / "plans"
    d.mkdir()
    return d


@pytest.fixture
def reports_dir(tmp_path):
    d = tmp_path / "daily-reports"
    d.mkdir()
    return d


# ── T3-1: plan 스캔/헤더 갱신/JSON 저장 실제 파일시스템으로 검증 ──────────────

@pytest.mark.asyncio
async def test_scan_and_run_plans_updates_frontmatter(plans_dir, reports_dir):
    """_scan_and_run_plans 실행 후 plan에 auto_run_status가 기록됨"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    plan = _make_plan_file(plans_dir, str(yesterday))

    fake_run_status = MagicMock()
    fake_run_status.runner_id = "runner-abc123"

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", plans_dir), \
         patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._DAILY_REPORTS_DIR", reports_dir), \
         patch("app.modules.dev_runner.services.executor_service.executor_service") as mock_exec:
        mock_exec.start_dev_runner = AsyncMock(return_value=fake_run_status)
        runs = await _scan_and_run_plans(today)

    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed"

    # frontmatter 갱신 검증
    meta = read_auto_run_meta(plan)
    assert meta.get("auto_run_status") == "completed"
    assert meta.get("auto_run_at") is not None


@pytest.mark.asyncio
async def test_scan_and_run_plans_saves_json(plans_dir, reports_dir):
    """_scan_and_run_plans 실행 후 auto-runs-YYYY-MM-DD.json 저장"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    _make_plan_file(plans_dir, str(yesterday))

    fake_run_status = MagicMock()
    fake_run_status.runner_id = "runner-xyz"

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", plans_dir), \
         patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._DAILY_REPORTS_DIR", reports_dir), \
         patch("app.modules.dev_runner.services.executor_service.executor_service") as mock_exec:
        mock_exec.start_dev_runner = AsyncMock(return_value=fake_run_status)
        await _scan_and_run_plans(today)

    json_file = reports_dir / f"auto-runs-{today}.json"
    assert json_file.exists()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["date"] == str(today)
    assert len(data["runs"]) == 1


@pytest.mark.asyncio
async def test_scan_and_run_plans_scope_mismatch_skipped(plans_dir, reports_dir):
    """scope=tc 인데 app 코드 수정 plan → skipped 상태로 기록"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    # tc scope이지만 app/ 경로 힌트 포함
    name = f"{yesterday}_scope-mismatch-plan.md"
    p = plans_dir / name
    p.write_text(
        "> auto_run: true\n> auto_run_scope: tc\n> 상태: 초안\n\n"
        "- [ ] `app/modules/billing/service.py`: 수정\n",
        encoding="utf-8",
    )

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", plans_dir), \
         patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._DAILY_REPORTS_DIR", reports_dir), \
         patch("app.modules.dev_runner.services.executor_service.executor_service") as mock_exec:
        mock_exec.start_dev_runner = AsyncMock()
        runs = await _scan_and_run_plans(today)

    assert len(runs) == 1
    assert runs[0]["status"] == "skipped"
    mock_exec.start_dev_runner.assert_not_called()

    meta = read_auto_run_meta(p)
    assert meta.get("auto_run_status") == "skipped"


@pytest.mark.asyncio
async def test_scan_and_run_plans_already_run_not_rerun(plans_dir, reports_dir):
    """이미 auto_run_status 있는 plan → 재실행 없음"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    name = f"{yesterday}_already-done.md"
    p = plans_dir / name
    p.write_text(
        "> auto_run: true\n> auto_run_scope: tc\n> auto_run_status: completed\n> 상태: 초안\n\n",
        encoding="utf-8",
    )

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", plans_dir), \
         patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._DAILY_REPORTS_DIR", reports_dir), \
         patch("app.modules.dev_runner.services.executor_service.executor_service") as mock_exec:
        mock_exec.start_dev_runner = AsyncMock()
        runs = await _scan_and_run_plans(today)

    assert runs == []
    mock_exec.start_dev_runner.assert_not_called()


@pytest.mark.asyncio
async def test_scan_and_run_plans_executor_failure_continues(plans_dir, reports_dir):
    """executor 예외 → status=failed 기록 후 다음 plan 계속"""
    today = date(2026, 4, 26)
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    plan1 = _make_plan_file(plans_dir, str(yesterday), scope="tc")
    plan2 = _make_plan_file(plans_dir, str(day_before), scope="docs")
    # plan2 이름 충돌 방지를 위해 다른 이름 사용
    plan2.rename(plans_dir / f"{day_before}_other-plan.md")
    plan2 = plans_dir / f"{day_before}_other-plan.md"
    plan2.write_text(
        f"> auto_run: true\n> auto_run_scope: docs\n> 상태: 초안\n\n# Other\n",
        encoding="utf-8",
    )

    call_count = 0

    async def _failing_start(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("runner init failed")
        return MagicMock(runner_id="ok")

    with patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._PLANS_DIR", plans_dir), \
         patch("app.modules.dev_runner.schedulers.auto_dev_runner_schedule._DAILY_REPORTS_DIR", reports_dir), \
         patch("app.modules.dev_runner.services.executor_service.executor_service") as mock_exec:
        mock_exec.start_dev_runner = _failing_start
        runs = await _scan_and_run_plans(today)

    statuses = {r["plan_id"]: r["status"] for r in runs}
    # 첫 번째는 실패, 두 번째는 완료
    assert any(v == "failed" for v in statuses.values())
    assert any(v == "completed" for v in statuses.values())
