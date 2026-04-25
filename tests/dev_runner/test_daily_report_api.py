"""일일 보고서 API 단위 테스트 (TestClient, 파일시스템 mock)."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.daily_reports import router

app = FastAPI()
app.include_router(router, prefix="/api/v1/dev-runner")
client = TestClient(app)


def _seed_report(reports_dir: Path, date_str: str, runs: list | None = None) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "date": date_str,
        "generated_at": f"{date_str}T08:00:00",
        "summary": {"total": len(runs or []), "completed": 0, "failed": 0, "skipped": 0},
        "runs": runs or [],
    }
    (reports_dir / f"{date_str}.json").write_text(json.dumps(data), encoding="utf-8")
    (reports_dir / f"{date_str}.html").write_text(f"<html>{date_str}</html>", encoding="utf-8")


# ── GET /daily-reports ────────────────────────────────────────────────────────

def test_list_daily_reports_R_returns_list(tmp_path):
    """보고서 파일 있으면 200 + 목록 반환"""
    _seed_report(tmp_path, "2026-04-25")
    _seed_report(tmp_path, "2026-04-24")

    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", tmp_path):
        resp = client.get("/api/v1/dev-runner/daily-reports")

    assert resp.status_code == 200
    dates = [r["date"] for r in resp.json()]
    assert "2026-04-25" in dates
    assert "2026-04-24" in dates


def test_list_daily_reports_B_empty_dir(tmp_path):
    """보고서 없으면 200 + 빈 리스트"""
    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", tmp_path):
        resp = client.get("/api/v1/dev-runner/daily-reports")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_daily_reports_B_no_dir(tmp_path):
    """디렉토리 없으면 200 + 빈 리스트"""
    missing = tmp_path / "nonexistent"
    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", missing):
        resp = client.get("/api/v1/dev-runner/daily-reports")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_daily_reports_Co_html_available_flag(tmp_path):
    """html_available 플래그 — HTML 파일 있으면 True"""
    _seed_report(tmp_path, "2026-04-25")

    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", tmp_path):
        resp = client.get("/api/v1/dev-runner/daily-reports")

    items = resp.json()
    assert items[0]["html_available"] is True


# ── GET /daily-reports/{date} ─────────────────────────────────────────────────

def test_get_daily_report_R_returns_200(tmp_path):
    """날짜 보고서 JSON 200 반환"""
    _seed_report(tmp_path, "2026-04-25")

    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", tmp_path):
        resp = client.get("/api/v1/dev-runner/daily-reports/2026-04-25")

    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == "2026-04-25"


def test_get_daily_report_E_missing_date_404(tmp_path):
    """없는 날짜 → 404"""
    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", tmp_path):
        resp = client.get("/api/v1/dev-runner/daily-reports/1999-01-01")

    assert resp.status_code == 404


# ── GET /daily-reports/{date}/html ────────────────────────────────────────────

def test_get_daily_report_html_R_returns_html(tmp_path):
    """날짜 HTML 보고서 200 + Content-Type: text/html"""
    _seed_report(tmp_path, "2026-04-25")

    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", tmp_path):
        resp = client.get("/api/v1/dev-runner/daily-reports/2026-04-25/html")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "2026-04-25" in resp.text


def test_get_daily_report_html_E_missing_date_404(tmp_path):
    """없는 날짜 HTML → 404"""
    with patch("app.modules.dev_runner.routes.daily_reports._DAILY_REPORTS_DIR", tmp_path):
        resp = client.get("/api/v1/dev-runner/daily-reports/1999-01-01/html")

    assert resp.status_code == 404
