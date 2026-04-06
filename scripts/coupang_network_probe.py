"""
Coupang login network probe.

Checks:
1) Network hint endpoints (public IP / ASN)
2) httpx login-domain direct access
3) Playwright channel-level login access

This is test-only code; no worker/backend behavior is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "logs" / "coupang-feasibility"
TRIP_URL = "https://trip.coupang.com"
LOGIN_URL = "https://login.coupang.com/login/login.pang"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coupang network probe")
    parser.add_argument("--label", default="network-probe", help="Run label")
    parser.add_argument(
        "--channels",
        default="chromium,chrome",
        help="Playwright channels (comma-separated, e.g. chromium,chrome,msedge)",
    )
    parser.add_argument("--timeout-sec", type=float, default=20.0, help="Request/navigation timeout")
    parser.add_argument("--warmup-sec", type=float, default=10.0, help="Trip warmup seconds")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--output", help="Output JSON path")
    return parser.parse_args()


def default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return OUTPUT_DIR / f"network_probe_{ts}.json"


async def fetch_json(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"url": url, "ok": False, "status": None, "json": None, "error": None}
    try:
        resp = await client.get(url)
        out["status"] = resp.status_code
        out["json"] = resp.json()
        out["ok"] = True
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


async def probe_httpx(timeout_sec: float) -> Dict[str, Any]:
    timeout = httpx.Timeout(timeout_sec)
    results: List[Dict[str, Any]] = []
    urls = [
        "https://login.coupang.com/login/login.pang",
        "https://www.coupang.com/np/login",
    ]
    headers = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for url in urls:
            row: Dict[str, Any] = {"url": url, "status": None, "server": "", "title_hint": "", "error": None}
            try:
                resp = await client.get(url)
                row["status"] = resp.status_code
                row["server"] = resp.headers.get("server", "")
                body_head = resp.text[:1200]
                if "Access Denied" in body_head:
                    row["title_hint"] = "Access Denied"
                elif "로그인" in body_head:
                    row["title_hint"] = "로그인"
                else:
                    row["title_hint"] = "unknown"
            except Exception as e:  # noqa: BLE001
                row["error"] = str(e)
            results.append(row)
    return {"results": results}


async def probe_browser_channel(channel: str, timeout_sec: float, warmup_sec: float, headless: bool) -> Dict[str, Any]:
    timeout_ms = int(timeout_sec * 1000)
    out: Dict[str, Any] = {
        "channel": channel,
        "ok": False,
        "error": None,
        "trip_status": None,
        "trip_title_initial": "",
        "trip_title_after_warmup": "",
        "login_status": None,
        "login_title": "",
        "runtime_user_agent": "",
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    profile_dir = PROJECT_ROOT / "data" / "browser_profiles" / f"networkprobe_{channel}_{ts}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    launch_kwargs: Dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "viewport": {"width": 1280, "height": 800},
        "args": ["--window-size=1280,800", "--window-position=140,140"],
    }
    if channel != "chromium":
        launch_kwargs["channel"] = channel

    try:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                trip_resp = await page.goto(TRIP_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                out["trip_status"] = trip_resp.status if trip_resp else None
                out["trip_title_initial"] = await page.title()
                if warmup_sec > 0:
                    await page.wait_for_timeout(int(warmup_sec * 1000))
                out["trip_title_after_warmup"] = await page.title()
                login_resp = await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                out["login_status"] = login_resp.status if login_resp else None
                out["login_title"] = await page.title()
                out["runtime_user_agent"] = await page.evaluate("navigator.userAgent")
                out["ok"] = True
            finally:
                await context.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


async def main_async(args: argparse.Namespace) -> Dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "label": args.label,
        "settings": {
            "channels": args.channels,
            "timeout_sec": args.timeout_sec,
            "warmup_sec": args.warmup_sec,
            "headless": args.headless,
        },
        "network_hints": [],
        "httpx_probe": {},
        "browser_probe": [],
    }

    timeout = httpx.Timeout(args.timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        hint_urls = [
            "https://ipinfo.io/json",
            "http://ip-api.com/json/",
        ]
        for url in hint_urls:
            report["network_hints"].append(await fetch_json(client, url))

    report["httpx_probe"] = await probe_httpx(args.timeout_sec)

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    for channel in channels:
        result = await probe_browser_channel(
            channel=channel,
            timeout_sec=args.timeout_sec,
            warmup_sec=args.warmup_sec,
            headless=args.headless,
        )
        report["browser_probe"].append(result)
        print(
            f"[browser:{channel}] trip={result.get('trip_status')} "
            f"login={result.get('login_status')} title={result.get('login_title')} "
            f"error={result.get('error') or '-'}"
        )

    return report


def main() -> None:
    args = parse_args()
    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    report = asyncio.run(main_async(args))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[coupang-network-probe] output: {output}")


if __name__ == "__main__":
    main()
