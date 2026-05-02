"""일일 보고서 빌더.

auto-runs-YYYY-MM-DD.json을 읽어 요약 JSON과 self-contained HTML을 생성한다.
"""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT
from app.shared.io import write_json_atomic

logger = logging.getLogger(__name__)

_DAILY_REPORTS_DIR = PROJECT_ROOT / "logs" / "daily-reports"
_PLAN_RUNS_DIR = PROJECT_ROOT / "logs" / "plan-runs"
_EXTRACT_SCRIPT = PROJECT_ROOT / "scripts" / "logs" / "extract-plan-log.ps1"


def _load_raw_runs(target_date: date) -> list[dict]:
    raw_path = _DAILY_REPORTS_DIR / f"auto-runs-{target_date}.json"
    if not raw_path.exists():
        return []
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        return data.get("runs", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[daily_report_builder] raw JSON 읽기 실패: %s", exc)
        return []


def _try_extract_log(runner_id: str) -> str:
    """extract-plan-log.ps1을 호출해 plan-runs/<runner_id>.log를 생성하고 경로를 반환."""
    out_file = _PLAN_RUNS_DIR / f"{runner_id}.log"
    if out_file.exists():
        return str(out_file)

    if not _EXTRACT_SCRIPT.exists():
        return ""

    try:
        result = subprocess.run(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(_EXTRACT_SCRIPT),
             "-Plan", runner_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and out_file.exists():
            return str(out_file)
        logger.warning("[daily_report_builder] extract-plan-log 실패 (runner_id=%s): %s", runner_id, result.stderr.strip())
    except Exception as exc:
        logger.warning("[daily_report_builder] extract-plan-log 예외 (runner_id=%s): %s", runner_id, exc)
    return ""


def build_report(target_date: date) -> dict:
    """auto-runs JSON을 읽어 최종 보고서 dict를 반환한다."""
    runs = _load_raw_runs(target_date)

    enriched: list[dict] = []
    for run in runs:
        entry: dict[str, Any] = dict(run)
        runner_id = run.get("plan_id", "")
        if runner_id and not entry.get("log_path"):
            log_path = _try_extract_log(runner_id)
            if log_path:
                entry["log_path"] = log_path
            else:
                entry.setdefault("suspicions", [])
                if log_path == "":
                    entry["suspicions"].append("로그 추출 실패 또는 아직 실행 중")
        enriched.append(entry)

    completed = sum(1 for r in enriched if r.get("status") == "completed")
    failed = sum(1 for r in enriched if r.get("status") == "failed")
    skipped = sum(1 for r in enriched if r.get("status") == "skipped")

    report = {
        "date": str(target_date),
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total": len(enriched),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        },
        "runs": enriched,
    }

    # JSON 저장
    json_path = _DAILY_REPORTS_DIR / f"{target_date}.json"
    write_json_atomic(json_path, report)

    # HTML 저장
    html = render_html(report)
    html_path = _DAILY_REPORTS_DIR / f"{target_date}.html"
    html_path.write_text(html, encoding="utf-8")

    logger.info(
        "[daily_report_builder] %s 보고서 생성 완료: total=%d completed=%d failed=%d skipped=%d",
        target_date, len(enriched), completed, failed, skipped,
    )
    return report


def render_html(report: dict) -> str:
    """보고서 dict를 self-contained HTML로 변환한다."""
    date_str = report.get("date", "")
    generated_at = report.get("generated_at", "")
    summary = report.get("summary", {})
    runs = report.get("runs", [])

    def _status_color(status: str) -> str:
        return {"completed": "#16a34a", "failed": "#dc2626", "skipped": "#d97706"}.get(status, "#6b7280")

    def _run_row(run: dict) -> str:
        plan_id = run.get("plan_id", "")
        scope = run.get("scope", "")
        status = run.get("status", "")
        merged = "✓" if run.get("merged") else "✗"
        suspicions = run.get("suspicions") or []
        log_path = run.get("log_path", "")
        log_link = f'<a href="file:///{log_path}" style="color:#2563eb">로그</a>' if log_path else "-"
        suspicion_text = "<br>".join(str(s) for s in suspicions) if suspicions else "-"
        color = _status_color(status)
        return (
            f"<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e5e7eb;font-family:monospace'>{plan_id}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e5e7eb'>{scope}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e5e7eb;color:{color};font-weight:600'>{status}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:center'>{merged}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e5e7eb'>{log_link}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e5e7eb;color:#b91c1c;font-size:12px'>{suspicion_text}</td>"
            f"</tr>"
        )

    rows = "\n".join(_run_row(r) for r in runs)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>일일 자동 실행 보고서 — {date_str}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin:0; padding:20px; background:#f9fafb; color:#111827; }}
  h1 {{ font-size:20px; margin-bottom:4px; }}
  .meta {{ color:#6b7280; font-size:13px; margin-bottom:20px; }}
  .summary {{ display:flex; gap:16px; margin-bottom:24px; }}
  .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:8px; padding:14px 20px; min-width:100px; }}
  .card .label {{ font-size:12px; color:#6b7280; margin-bottom:4px; }}
  .card .value {{ font-size:24px; font-weight:700; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  th {{ padding:10px 10px; background:#f3f4f6; text-align:left; font-size:13px; color:#374151; border-bottom:2px solid #e5e7eb; }}
</style>
</head>
<body>
<h1>일일 자동 실행 보고서</h1>
<div class="meta">날짜: {date_str} &nbsp;|&nbsp; 생성: {generated_at}</div>
<div class="summary">
  <div class="card"><div class="label">전체</div><div class="value">{summary.get("total", 0)}</div></div>
  <div class="card"><div class="label">완료</div><div class="value" style="color:#16a34a">{summary.get("completed", 0)}</div></div>
  <div class="card"><div class="label">실패</div><div class="value" style="color:#dc2626">{summary.get("failed", 0)}</div></div>
  <div class="card"><div class="label">스킵</div><div class="value" style="color:#d97706">{summary.get("skipped", 0)}</div></div>
</div>
{"<p style='color:#6b7280'>자동 실행 대상 plan이 없습니다.</p>" if not runs else f'''
<table>
<thead><tr>
  <th>Plan ID</th><th>Scope</th><th>상태</th><th>머지</th><th>로그</th><th>의심 항목</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>'''}
</body>
</html>
"""
