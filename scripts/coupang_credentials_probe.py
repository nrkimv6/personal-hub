"""
Probe vendor-items responses by fetch credentials mode.

This is test-only code; no worker/backend behavior is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "logs" / "coupang-feasibility"

DEFAULT_PRODUCT_ID = "10000011218760"
DEFAULT_VENDOR_ITEM_PACKAGE_ID = "30000011218342"
TRIP_URL = "https://trip.coupang.com"
LOGIN_URL = "https://login.coupang.com/login/login.pang"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coupang credentials-mode probe")
    parser.add_argument("--product-id", default=DEFAULT_PRODUCT_ID)
    parser.add_argument("--vendor-item-package-id", default=DEFAULT_VENDOR_ITEM_PACKAGE_ID)
    parser.add_argument("--date", required=True, help="selectDate (YYYY-MM-DD)")
    parser.add_argument("--repeat", type=int, default=3, help="Repeat count")
    parser.add_argument("--interval-sec", type=float, default=5.0, help="Interval between repeats")
    parser.add_argument("--timeout-sec", type=float, default=25.0)
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument(
        "--profile-dir",
        default=str(PROJECT_ROOT / "data" / "browser_profiles" / "default"),
        help="Persistent user_data_dir",
    )
    parser.add_argument("--output", help="Output JSON path")
    return parser.parse_args()


def default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return OUTPUT_DIR / f"credentials_probe_{ts}.json"


def summarize_payload(payload: Any) -> Dict[str, Any]:
    summary = {
        "is_dict": isinstance(payload, dict),
        "travel_items_count": 0,
        "vendor_items_count": 0,
    }
    if not isinstance(payload, dict):
        return summary
    travel_items = payload.get("travelItems")
    if not isinstance(travel_items, list):
        return summary
    summary["travel_items_count"] = len(travel_items)
    vendor_count = 0
    for item in travel_items:
        if not isinstance(item, dict):
            continue
        vendor_items = item.get("vendorItems")
        if isinstance(vendor_items, list):
            vendor_count += sum(1 for x in vendor_items if isinstance(x, dict))
    summary["vendor_items_count"] = vendor_count
    return summary


async def run_once(page, *, product_id: str, package_id: str, select_date: str, timeout_sec: float) -> Dict[str, Any]:
    timeout_ms = int(timeout_sec * 1000)
    result: Dict[str, Any] = {
        "trip": {},
        "login": {},
        "credentials_modes": [],
    }

    trip_resp = await page.goto(TRIP_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    result["trip"] = {
        "status": trip_resp.status if trip_resp else None,
        "title": await page.title(),
        "url": page.url,
    }

    modes = ["omit", "same-origin", "include"]
    payload = {
        "vendorItemPackageId": package_id,
        "productType": "TICKET",
        "selectDate": select_date,
    }
    fetch_url = f"https://trip.coupang.com/api/products/{product_id}/vendor-items"

    for mode in modes:
        item: Dict[str, Any] = {"mode": mode, "status": None, "ok": False, "error": None}
        try:
            row = await page.evaluate(
                """
                async ({ url, payload, mode }) => {
                  try {
                    const r = await fetch(url, {
                      method: "POST",
                      credentials: mode,
                      headers: {
                        "accept": "application/json, text/plain, */*",
                        "content-type": "application/json;charset=UTF-8"
                      },
                      body: JSON.stringify(payload),
                    });
                    const text = await r.text();
                    let parsed = null;
                    try { parsed = JSON.parse(text); } catch (_) {}
                    return {
                      status: r.status,
                      ok: r.ok,
                      content_type: r.headers.get("content-type") || "",
                      text_preview: text.slice(0, 300),
                      parsed,
                    };
                  } catch (e) {
                    return { error: String(e) };
                  }
                }
                """,
                {"url": fetch_url, "payload": payload, "mode": mode},
            )
            item["status"] = row.get("status")
            item["ok"] = bool(row.get("ok"))
            item["content_type"] = row.get("content_type", "")
            item["error"] = row.get("error")
            item["schema_summary"] = summarize_payload(row.get("parsed"))
            item["text_preview"] = row.get("text_preview", "")
        except Exception as e:  # noqa: BLE001
            item["error"] = str(e)
        result["credentials_modes"].append(item)

    login_resp = await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    result["login"] = {
        "status": login_resp.status if login_resp else None,
        "title": await page.title(),
        "url": page.url,
    }
    return result


async def main_async(args: argparse.Namespace) -> Dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile_dir).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "settings": {
            "product_id": args.product_id,
            "vendor_item_package_id": args.vendor_item_package_id,
            "date": args.date,
            "repeat": args.repeat,
            "interval_sec": args.interval_sec,
            "timeout_sec": args.timeout_sec,
            "headless": args.headless,
            "profile_dir": str(profile_dir),
        },
        "runs": [],
    }

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=args.headless,
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            args=["--window-size=1280,800", "--window-position=140,140"],
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            for i in range(1, args.repeat + 1):
                row = await run_once(
                    page,
                    product_id=args.product_id,
                    package_id=args.vendor_item_package_id,
                    select_date=args.date,
                    timeout_sec=args.timeout_sec,
                )
                row["attempt"] = i
                report["runs"].append(row)
                mode_summary = ", ".join(
                    f"{x.get('mode')}:{x.get('status')}/{x.get('schema_summary', {}).get('travel_items_count', 0)}"
                    for x in row.get("credentials_modes", [])
                )
                print(
                    f"[attempt {i}] trip={row['trip'].get('status')} "
                    f"login={row['login'].get('status')}:{row['login'].get('title')} "
                    f"modes={mode_summary}"
                )
                if i < args.repeat and args.interval_sec > 0:
                    await page.wait_for_timeout(int(args.interval_sec * 1000))
        finally:
            await context.close()

    return report


def main() -> None:
    args = parse_args()
    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(main_async(args))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[coupang-credentials-probe] output: {output}")


if __name__ == "__main__":
    main()
