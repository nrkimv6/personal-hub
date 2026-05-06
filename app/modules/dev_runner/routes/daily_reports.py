"""일일 자동 실행 보고서 API."""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

router = APIRouter()

_DAILY_REPORTS_DIR = PROJECT_ROOT / "logs" / "daily-reports"


class DailyReportSummary(BaseModel):
    date: str
    generated_at: Optional[str] = None
    summary: dict = {}
    html_available: bool = False


@router.get("/daily-reports", response_model=list[DailyReportSummary])
def list_daily_reports():
    """날짜별 보고서 목록을 반환한다."""
    if not _DAILY_REPORTS_DIR.exists():
        return []

    result = []
    for json_file in sorted(_DAILY_REPORTS_DIR.glob("????-??-??.json"), reverse=True):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            html_file = json_file.with_suffix(".html")
            result.append(DailyReportSummary(
                date=data.get("date", json_file.stem),
                generated_at=data.get("generated_at"),
                summary=data.get("summary", {}),
                html_available=html_file.exists(),
            ))
        except Exception as exc:
            logger.warning("[daily_reports] JSON 파싱 실패 (%s): %s", json_file.name, exc)

    return result


@router.get("/daily-reports/{report_date}")
def get_daily_report(report_date: str):
    """특정 날짜 보고서 JSON을 반환한다."""
    json_file = _DAILY_REPORTS_DIR / f"{report_date}.json"
    if not json_file.exists():
        raise HTTPException(status_code=404, detail=f"보고서를 찾을 수 없습니다: {report_date}")
    try:
        return json.loads(json_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"보고서 읽기 실패: {exc}")


@router.get("/daily-reports/{report_date}/html")
def get_daily_report_html(report_date: str):
    """특정 날짜 보고서 HTML 본문을 텍스트로 반환한다."""
    from fastapi.responses import HTMLResponse

    html_file = _DAILY_REPORTS_DIR / f"{report_date}.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail=f"HTML 보고서를 찾을 수 없습니다: {report_date}")
    try:
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"HTML 읽기 실패: {exc}")
