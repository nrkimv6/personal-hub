"""daily_report_builder 단위 테스트."""
import json
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.modules.dev_runner.services.daily_report_builder import (
    build_report,
    render_html,
    _load_raw_runs,
)


def _write_raw(reports_dir: Path, target_date: date, runs: list) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / f"auto-runs-{target_date}.json"
    data = {"date": str(target_date), "runs": runs}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


SAMPLE_RUNS = [
    {
        "plan_id": "2026-04-25_my-plan",
        "scope": "tc",
        "status": "completed",
        "merged": True,
        "suspicions": [],
        "log_path": "",
        "started_at": "2026-04-25T02:00:01",
        "ended_at": "2026-04-25T02:03:15",
    },
    {
        "plan_id": "2026-04-25_other-plan",
        "scope": "docs",
        "status": "failed",
        "merged": False,
        "suspicions": ["start_dev_runner 실패: timeout"],
        "log_path": "",
        "started_at": "2026-04-25T02:03:16",
        "ended_at": "2026-04-25T02:04:00",
    },
]


# ── _load_raw_runs ─────────────────────────────────────────────────────────────

def test_load_raw_runs_R_reads_json(tmp_path):
    """정상 JSON 파일 → runs 리스트 반환"""
    target = date(2026, 4, 25)
    _write_raw(tmp_path, target, SAMPLE_RUNS)

    with patch("app.modules.dev_runner.services.daily_report_builder._DAILY_REPORTS_DIR", tmp_path):
        result = _load_raw_runs(target)

    assert len(result) == 2
    assert result[0]["plan_id"] == "2026-04-25_my-plan"


def test_load_raw_runs_B_missing_file(tmp_path):
    """파일 없음 → 빈 리스트"""
    with patch("app.modules.dev_runner.services.daily_report_builder._DAILY_REPORTS_DIR", tmp_path):
        result = _load_raw_runs(date(2026, 1, 1))
    assert result == []


def test_load_raw_runs_E_malformed_json(tmp_path):
    """JSON 손상 → 빈 리스트, 예외 없음"""
    target = date(2026, 4, 25)
    p = tmp_path / f"auto-runs-{target}.json"
    p.write_text("not json!!", encoding="utf-8")

    with patch("app.modules.dev_runner.services.daily_report_builder._DAILY_REPORTS_DIR", tmp_path):
        result = _load_raw_runs(target)
    assert result == []


# ── build_report ───────────────────────────────────────────────────────────────

def test_build_report_R_summary_counts(tmp_path):
    """build_report → summary 카운트 정확"""
    target = date(2026, 4, 25)
    _write_raw(tmp_path, target, SAMPLE_RUNS)

    with patch("app.modules.dev_runner.services.daily_report_builder._DAILY_REPORTS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path / "plan-runs"), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", tmp_path / "missing.ps1"):
        report = build_report(target)

    assert report["summary"]["total"] == 2
    assert report["summary"]["completed"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["skipped"] == 0


def test_build_report_R_json_file_saved(tmp_path):
    """build_report → YYYY-MM-DD.json 저장"""
    target = date(2026, 4, 25)
    _write_raw(tmp_path, target, SAMPLE_RUNS)

    with patch("app.modules.dev_runner.services.daily_report_builder._DAILY_REPORTS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path / "plan-runs"), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", tmp_path / "missing.ps1"):
        build_report(target)

    json_file = tmp_path / f"{target}.json"
    assert json_file.exists()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["date"] == str(target)


def test_build_report_R_html_file_saved(tmp_path):
    """build_report → YYYY-MM-DD.html 저장"""
    target = date(2026, 4, 25)
    _write_raw(tmp_path, target, SAMPLE_RUNS)

    with patch("app.modules.dev_runner.services.daily_report_builder._DAILY_REPORTS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path / "plan-runs"), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", tmp_path / "missing.ps1"):
        build_report(target)

    html_file = tmp_path / f"{target}.html"
    assert html_file.exists()
    html = html_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html


def test_build_report_B_empty_runs(tmp_path):
    """실행 없음 → summary total=0, html 저장됨"""
    target = date(2026, 4, 24)
    _write_raw(tmp_path, target, [])

    with patch("app.modules.dev_runner.services.daily_report_builder._DAILY_REPORTS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path / "plan-runs"), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", tmp_path / "missing.ps1"):
        report = build_report(target)

    assert report["summary"]["total"] == 0


# ── render_html ────────────────────────────────────────────────────────────────

def test_render_html_R_contains_plan_id():
    """render_html → plan_id가 HTML에 포함"""
    report = {
        "date": "2026-04-25",
        "generated_at": "2026-04-25T08:00:00",
        "summary": {"total": 1, "completed": 1, "failed": 0, "skipped": 0},
        "runs": [SAMPLE_RUNS[0]],
    }
    html = render_html(report)
    assert "2026-04-25_my-plan" in html


def test_render_html_R_status_color_in_html():
    """render_html → 완료/실패/스킵 색상 코드 포함"""
    report = {
        "date": "2026-04-25",
        "generated_at": "2026-04-25T08:00:00",
        "summary": {"total": 2, "completed": 1, "failed": 1, "skipped": 0},
        "runs": SAMPLE_RUNS,
    }
    html = render_html(report)
    assert "#16a34a" in html  # completed color
    assert "#dc2626" in html  # failed color


def test_render_html_B_empty_runs():
    """run 없음 → '대상 plan이 없습니다' 메시지"""
    report = {
        "date": "2026-04-24",
        "generated_at": "2026-04-24T08:00:00",
        "summary": {"total": 0, "completed": 0, "failed": 0, "skipped": 0},
        "runs": [],
    }
    html = render_html(report)
    assert "plan이 없습니다" in html


def test_render_html_Co_suspicion_shown():
    """의심 항목 → HTML에 표시"""
    report = {
        "date": "2026-04-25",
        "generated_at": "2026-04-25T08:00:00",
        "summary": {"total": 1, "completed": 0, "failed": 1, "skipped": 0},
        "runs": [SAMPLE_RUNS[1]],
    }
    html = render_html(report)
    assert "start_dev_runner 실패" in html
