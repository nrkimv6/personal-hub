"""
Open a non-secret persistent Playwright browser with configurable launch presets.

Use this script for Coupang login/session troubleshooting with the same profile
cache (`data/browser_profiles/<profile_dir>`) used by workers.

Examples:
    python scripts/coupang_browser_profile_runner.py --preset chromium_default
    python scripts/coupang_browser_profile_runner.py --preset chrome_stealth --exit-after-open
    python scripts/coupang_browser_profile_runner.py --preset chrome_stealth --flow trip_then_login --exit-after-open
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "data" / "browser_profiles" / "default"
DEFAULT_URL = "https://trip.coupang.com/tp/products/10000011218760"
DEFAULT_LOGIN_URL = "https://login.coupang.com/login/login.pang"

PRESETS: Dict[str, Dict[str, Any]] = {
    # Mirrors current ContextManager visible-mode defaults as closely as possible.
    "chromium_default": {
        "channel": None,
        "ignore_default_args": None,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1280,800",
            "--window-position=100,100",
        ],
    },
    # Minimal custom args on Playwright Chromium.
    "chromium_stock": {
        "channel": None,
        "ignore_default_args": None,
        "args": [
            "--window-size=1280,800",
            "--window-position=100,100",
        ],
    },
    # Use installed Google Chrome channel, disable --enable-automation.
    "chrome_stealth": {
        "channel": "chrome",
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--window-size=1280,800",
            "--window-position=100,100",
        ],
    },
    # Use installed Microsoft Edge channel, disable --enable-automation.
    "edge_stealth": {
        "channel": "msedge",
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--window-size=1280,800",
            "--window-position=100,100",
        ],
    },
}


def _default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return PROJECT_ROOT / "logs" / "coupang-feasibility" / f"browser_launch_{ts}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open non-secret persistent browser with configurable settings"
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS.keys()),
        default="chromium_default",
        help="Launch preset",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Persistent user_data_dir path",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Initial URL to open")
    parser.add_argument(
        "--flow",
        choices=["single_url", "trip_then_login", "product_then_login", "trip_then_login_rtn"],
        default="single_url",
        help="Navigation flow mode",
    )
    parser.add_argument(
        "--login-url",
        default=DEFAULT_LOGIN_URL,
        help="Login URL used by flow modes",
    )
    parser.add_argument(
        "--channel",
        choices=["auto", "chromium", "chrome", "msedge"],
        default="auto",
        help="Channel override (auto uses preset)",
    )
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument(
        "--user-agent",
        help="Override user agent string (default: browser native UA)",
    )
    parser.add_argument(
        "--use-legacy-ua120",
        action="store_true",
        help="Force legacy UA (Chrome/120) for regression reproduction",
    )
    parser.add_argument(
        "--no-webdriver-mask",
        action="store_true",
        help="Do not inject navigator.webdriver masking script",
    )
    parser.add_argument(
        "--exit-after-open",
        action="store_true",
        help="Open URL, collect metadata, then close immediately",
    )
    parser.add_argument(
        "--keep-alive-seconds",
        type=float,
        default=0.0,
        help="Keep browser alive for N seconds (0 = wait until Ctrl+C)",
    )
    parser.add_argument(
        "--warmup-sec",
        type=float,
        default=0.0,
        help="Optional wait after first trip/product step before login navigation",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=45.0,
        help="Navigation timeout in seconds",
    )
    parser.add_argument(
        "--output",
        help="Output JSON path. Default: logs/coupang-feasibility/browser_launch_*.json",
    )
    return parser.parse_args()


def _resolve_channel(preset_channel: Optional[str], override: str) -> Optional[str]:
    if override == "auto":
        return preset_channel
    if override == "chromium":
        return None
    return override


async def _run(args: argparse.Namespace) -> Dict[str, Any]:
    preset = PRESETS[args.preset]
    profile_dir = Path(args.profile_dir).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    channel = _resolve_channel(preset.get("channel"), args.channel)
    launch_kwargs: Dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": args.headless,
        "args": list(preset.get("args") or []),
        "viewport": {"width": 1280, "height": 800},
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
    }
    forced_ua = args.user_agent
    if args.use_legacy_ua120:
        forced_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    if forced_ua:
        launch_kwargs["user_agent"] = forced_ua
    if channel:
        launch_kwargs["channel"] = channel
    ignore_default_args = preset.get("ignore_default_args")
    if ignore_default_args:
        launch_kwargs["ignore_default_args"] = list(ignore_default_args)

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "preset": args.preset,
        "channel": channel or "chromium",
        "profile_dir": str(profile_dir),
        "url": args.url,
        "flow": args.flow,
        "login_url": args.login_url,
        "headless": args.headless,
        "forced_user_agent": forced_ua,
        "exit_after_open": args.exit_after_open,
        "keep_alive_seconds": args.keep_alive_seconds,
        "warmup_sec": args.warmup_sec,
        "launch_kwargs_summary": {
            "args": launch_kwargs.get("args", []),
            "ignore_default_args": launch_kwargs.get("ignore_default_args", []),
            "locale": launch_kwargs.get("locale"),
            "timezone_id": launch_kwargs.get("timezone_id"),
        },
        "ok": False,
        "error": None,
        "page": {},
        "steps": [],
    }

    stop_event = asyncio.Event()

    def _stop(*_sig: int) -> None:
        stop_event.set()

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except Exception:
        pass

    try:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            try:
                if not args.no_webdriver_mask:
                    await context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                    )

                page = context.pages[0] if context.pages else await context.new_page()

                async def run_step(label: str, target_url: str) -> None:
                    rec: Dict[str, Any] = {"step": label, "target_url": target_url}
                    try:
                        resp = await page.goto(
                            target_url,
                            wait_until="domcontentloaded",
                            timeout=int(args.timeout_sec * 1000),
                        )
                        rec["status"] = resp.status if resp else None
                    except Exception as exc:
                        rec["goto_error"] = str(exc)
                    try:
                        rec["current_url"] = page.url
                    except Exception:
                        rec["current_url"] = ""
                    try:
                        rec["title"] = await page.title()
                    except Exception:
                        rec["title"] = ""
                    report["steps"].append(rec)

                if args.flow == "single_url":
                    await run_step("single_url", args.url)
                elif args.flow == "trip_then_login":
                    await run_step("trip", "https://trip.coupang.com")
                    if args.warmup_sec > 0:
                        await page.wait_for_timeout(int(args.warmup_sec * 1000))
                        report["steps"].append(
                            {
                                "step": "warmup_wait",
                                "seconds": args.warmup_sec,
                                "current_url": page.url,
                                "title": await page.title(),
                            }
                        )
                    await run_step("login", args.login_url)
                elif args.flow == "product_then_login":
                    await run_step("product", args.url)
                    if args.warmup_sec > 0:
                        await page.wait_for_timeout(int(args.warmup_sec * 1000))
                        report["steps"].append(
                            {
                                "step": "warmup_wait",
                                "seconds": args.warmup_sec,
                                "current_url": page.url,
                                "title": await page.title(),
                            }
                        )
                    await run_step("login", args.login_url)
                elif args.flow == "trip_then_login_rtn":
                    await run_step("trip", "https://trip.coupang.com")
                    if args.warmup_sec > 0:
                        await page.wait_for_timeout(int(args.warmup_sec * 1000))
                        report["steps"].append(
                            {
                                "step": "warmup_wait",
                                "seconds": args.warmup_sec,
                                "current_url": page.url,
                                "title": await page.title(),
                            }
                        )
                    await run_step(
                        "login_rtn",
                        "https://login.coupang.com/login/login.pang?rtnUrl=https%3A%2F%2Fwww.coupang.com%2Fnp%2Fpost%2Flogin%3Fr%3Dhttps%253A%252F%252Fwww.coupang.com",
                    )

                report["ok"] = True
                last_step = report["steps"][-1] if report["steps"] else {}
                report["page"] = {
                    "current_url": last_step.get("current_url", ""),
                    "title": last_step.get("title", ""),
                    "goto_error": last_step.get("goto_error"),
                }

                if args.exit_after_open:
                    return report

                if args.keep_alive_seconds > 0:
                    await asyncio.sleep(args.keep_alive_seconds)
                else:
                    await stop_event.wait()

                return report
            finally:
                await context.close()
    except Exception as exc:
        report["error"] = str(exc)
        return report


def main() -> None:
    args = _parse_args()
    output = Path(args.output) if args.output else _default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    report = asyncio.run(_run(args))
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[coupang-browser-runner] output: {output}")
    print(f"- preset={report.get('preset')} channel={report.get('channel')}")
    print(f"- profile_dir={report.get('profile_dir')}")
    print(f"- ok={report.get('ok')} error={report.get('error') or '-'}")
    page = report.get("page") or {}
    if isinstance(page, dict):
        print(f"- current_url={page.get('current_url') or '-'}")
        print(f"- title={page.get('title') or '-'}")
        print(f"- goto_error={page.get('goto_error') or '-'}")
    steps = report.get("steps")
    if isinstance(steps, list) and steps:
        for step in steps:
            if not isinstance(step, dict):
                continue
            print(
                f"- step:{step.get('step')} status={step.get('status')} "
                f"url={step.get('current_url') or '-'} title={step.get('title') or '-'} "
                f"error={step.get('goto_error') or '-'}"
            )


if __name__ == "__main__":
    main()
