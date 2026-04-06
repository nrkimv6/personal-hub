"""
Run repeatable browser-property matrix tests for Coupang login access.

Scope:
  - Test code only (no worker/backend behavior changes)
  - Collect reproducible evidence for Access Denied patterns

Example:
  python scripts/coupang_login_access_matrix.py --repeat 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "logs" / "coupang-feasibility"

LOGIN_URL = "https://login.coupang.com/login/login.pang"
TRIP_URL = "https://trip.coupang.com"
UA120 = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class CaseConfig:
    name: str
    channel: str  # chromium | chrome | msedge
    flow: str  # direct | trip_then_login
    force_ua120: bool = False
    set_locale_tz: bool = False
    ignore_enable_automation: bool = False
    disable_blink_automation: bool = False
    webdriver_mask: bool = False
    headless: bool = False


CASES: List[CaseConfig] = [
    # Baselines
    CaseConfig(name="chromium_direct_baseline", channel="chromium", flow="direct"),
    CaseConfig(name="chromium_trip_baseline", channel="chromium", flow="trip_then_login"),
    CaseConfig(name="chrome_direct_baseline", channel="chrome", flow="direct"),
    CaseConfig(name="chrome_trip_baseline", channel="chrome", flow="trip_then_login"),
    # UA effect
    CaseConfig(name="chrome_direct_ua120", channel="chrome", flow="direct", force_ua120=True),
    CaseConfig(name="chrome_trip_ua120", channel="chrome", flow="trip_then_login", force_ua120=True),
    # Locale/timezone effect
    CaseConfig(name="chrome_direct_locale_tz", channel="chrome", flow="direct", set_locale_tz=True),
    CaseConfig(name="chrome_trip_locale_tz", channel="chrome", flow="trip_then_login", set_locale_tz=True),
    # Automation flags effect
    CaseConfig(
        name="chrome_direct_no_enable_automation",
        channel="chrome",
        flow="direct",
        ignore_enable_automation=True,
    ),
    CaseConfig(
        name="chrome_trip_no_enable_automation",
        channel="chrome",
        flow="trip_then_login",
        ignore_enable_automation=True,
    ),
    # Combined "stealth-ish"
    CaseConfig(
        name="chrome_trip_stealth_combo",
        channel="chrome",
        flow="trip_then_login",
        ignore_enable_automation=True,
        disable_blink_automation=True,
        webdriver_mask=True,
    ),
    # Edge sample
    CaseConfig(name="edge_direct_baseline", channel="msedge", flow="direct"),
    CaseConfig(name="edge_trip_baseline", channel="msedge", flow="trip_then_login"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coupang login access matrix runner")
    parser.add_argument("--repeat", type=int, default=2, help="Repeat count per case")
    parser.add_argument("--timeout-sec", type=float, default=45.0, help="Navigation timeout")
    parser.add_argument("--headless", action="store_true", help="Force headless for all cases")
    parser.add_argument(
        "--output",
        help="Output JSON path. Default: logs/coupang-feasibility/login_matrix_*.json",
    )
    return parser.parse_args()


def default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return OUTPUT_DIR / f"login_matrix_{ts}.json"


def build_launch_kwargs(case: CaseConfig, profile_dir: Path, args: argparse.Namespace) -> Dict[str, Any]:
    launch_kwargs: Dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": args.headless or case.headless,
        "viewport": {"width": 1280, "height": 800},
        "args": ["--window-size=1280,800", "--window-position=120,120"],
    }

    if case.channel != "chromium":
        launch_kwargs["channel"] = case.channel

    if case.force_ua120:
        launch_kwargs["user_agent"] = UA120

    if case.set_locale_tz:
        launch_kwargs["locale"] = "ko-KR"
        launch_kwargs["timezone_id"] = "Asia/Seoul"

    if case.ignore_enable_automation:
        launch_kwargs["ignore_default_args"] = ["--enable-automation"]

    if case.disable_blink_automation:
        launch_kwargs["args"].append("--disable-blink-features=AutomationControlled")

    return launch_kwargs


async def navigate_flow(page, case: CaseConfig, timeout_ms: int) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    async def _step(label: str, url: str) -> None:
        item: Dict[str, Any] = {"step": label, "target_url": url}
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            item["status"] = resp.status if resp else None
        except Exception as e:
            item["error"] = str(e)
        item["current_url"] = page.url
        try:
            item["title"] = await page.title()
        except Exception:
            item["title"] = ""
        steps.append(item)

    if case.flow == "direct":
        await _step("login", LOGIN_URL)
    elif case.flow == "trip_then_login":
        await _step("trip", TRIP_URL)
        await _step("login", LOGIN_URL)
    else:
        raise ValueError(f"Unknown flow: {case.flow}")

    final = steps[-1] if steps else {}
    return {
        "steps": steps,
        "final_status": final.get("status"),
        "final_url": final.get("current_url"),
        "final_title": final.get("title"),
        "final_error": final.get("error"),
    }


async def run_case(case: CaseConfig, run_index: int, args: argparse.Namespace) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    profile_dir = PROJECT_ROOT / "data" / "browser_profiles" / f"matrix_{case.name}_{run_index}_{ts}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    result: Dict[str, Any] = {
        "case": asdict(case),
        "run_index": run_index,
        "profile_dir": str(profile_dir),
        "ok": False,
        "error": None,
    }

    launch_kwargs = build_launch_kwargs(case, profile_dir, args)
    result["launch_summary"] = {
        "channel": launch_kwargs.get("channel", "chromium"),
        "headless": launch_kwargs.get("headless"),
        "has_user_agent": "user_agent" in launch_kwargs,
        "locale": launch_kwargs.get("locale"),
        "timezone_id": launch_kwargs.get("timezone_id"),
        "ignore_default_args": launch_kwargs.get("ignore_default_args", []),
        "args": launch_kwargs.get("args", []),
    }

    timeout_ms = int(args.timeout_sec * 1000)
    try:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            try:
                if case.webdriver_mask:
                    await context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                    )

                page = context.pages[0] if context.pages else await context.new_page()
                flow_result = await navigate_flow(page, case, timeout_ms)

                ua = ""
                try:
                    ua = await page.evaluate("navigator.userAgent")
                except Exception:
                    pass

                result["ok"] = True
                result["flow"] = flow_result
                result["runtime_user_agent"] = ua

                status = flow_result.get("final_status")
                title = (flow_result.get("final_title") or "").strip().lower()
                result["login_access_ok"] = bool(status == 200 and "access denied" not in title)
                return result
            finally:
                await context.close()
    except Exception as e:
        result["error"] = str(e)
        result["login_access_ok"] = False
        return result


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_case: Dict[str, Dict[str, Any]] = {}
    for item in results:
        case_name = item["case"]["name"]
        entry = by_case.setdefault(
            case_name,
            {
                "count": 0,
                "ok_count": 0,
                "blocked_count": 0,
                "error_count": 0,
                "sample_final_status": None,
                "sample_final_title": None,
            },
        )
        entry["count"] += 1
        if item.get("error"):
            entry["error_count"] += 1
            continue
        if item.get("login_access_ok"):
            entry["ok_count"] += 1
        else:
            entry["blocked_count"] += 1
        flow = item.get("flow") or {}
        entry["sample_final_status"] = flow.get("final_status")
        entry["sample_final_title"] = flow.get("final_title")

    return {"by_case": by_case}


async def main_async(args: argparse.Namespace) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for case in CASES:
        for i in range(1, args.repeat + 1):
            rec = await run_case(case, i, args)
            results.append(rec)
            flow = rec.get("flow") or {}
            print(
                f"[{case.name} #{i}] ok={rec.get('ok')} login_access_ok={rec.get('login_access_ok')} "
                f"status={flow.get('final_status')} title={flow.get('final_title') or '-'} "
                f"error={rec.get('error') or '-'}"
            )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repeat": args.repeat,
        "timeout_sec": args.timeout_sec,
        "results": results,
        "summary": summarize(results),
    }


def main() -> None:
    args = parse_args()
    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    report = asyncio.run(main_async(args))
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[coupang-login-matrix] output: {output}")
    for case_name, item in report["summary"]["by_case"].items():
        print(
            f"- {case_name}: ok={item['ok_count']}/{item['count']} "
            f"blocked={item['blocked_count']} errors={item['error_count']} "
            f"sample=({item['sample_final_status']}, {item['sample_final_title']})"
        )


if __name__ == "__main__":
    main()

