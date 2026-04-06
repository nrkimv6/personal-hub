"""
Probe Coupang auth/session behavior via CDP-attached Chrome.

Run Chrome with remote debugging enabled, then attach:
  chrome.exe --remote-debugging-port=9222
  python scripts/coupang_cdp_session_probe.py --date 2026-04-06

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

TRIP_URL = "https://trip.coupang.com"
LOGIN_URL = "https://login.coupang.com/login/login.pang"
MYCOUPANG_URL = "https://www.coupang.com/np/mycoupang"
DEFAULT_PRODUCT_ID = "10000011218760"
DEFAULT_VENDOR_ITEM_PACKAGE_ID = "30000011218342"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coupang CDP session probe")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222", help="CDP endpoint")
    parser.add_argument("--date", required=True, help="selectDate (YYYY-MM-DD)")
    parser.add_argument("--product-id", default=DEFAULT_PRODUCT_ID)
    parser.add_argument("--vendor-item-package-id", default=DEFAULT_VENDOR_ITEM_PACKAGE_ID)
    parser.add_argument("--repeat", type=int, default=6, help="Loop count")
    parser.add_argument("--interval-sec", type=float, default=30.0, help="Interval between loops")
    parser.add_argument("--timeout-sec", type=float, default=30.0, help="Navigation timeout")
    parser.add_argument("--output", help="Output JSON path")
    return parser.parse_args()


def default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return OUTPUT_DIR / f"cdp_session_probe_{ts}.json"


async def goto_snapshot(page, url: str, timeout_ms: int) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"url": url, "status": None, "title": "", "final_url": "", "error": None}
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        rec["status"] = resp.status if resp else None
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e)
    rec["final_url"] = page.url
    try:
        rec["title"] = await page.title()
    except Exception:
        rec["title"] = ""
    try:
        rec["has_login_text"] = await page.evaluate(
            "Boolean(document.body && document.body.innerText.includes('로그인'))"
        )
        rec["has_logout_text"] = await page.evaluate(
            "Boolean(document.body && document.body.innerText.includes('로그아웃'))"
        )
    except Exception:
        rec["has_login_text"] = False
        rec["has_logout_text"] = False
    return rec


async def fetch_vendor_items(
    page,
    *,
    product_id: str,
    vendor_item_package_id: str,
    select_date: str,
) -> Dict[str, Any]:
    url = f"https://trip.coupang.com/api/products/{product_id}/vendor-items"
    payload = {
        "vendorItemPackageId": vendor_item_package_id,
        "productType": "TICKET",
        "selectDate": select_date,
    }
    row = await page.evaluate(
        """
        async ({ url, payload }) => {
          try {
            const r = await fetch(url, {
              method: "POST",
              credentials: "include",
              headers: {
                "accept": "application/json, text/plain, */*",
                "content-type": "application/json;charset=UTF-8"
              },
              body: JSON.stringify(payload),
            });
            const text = await r.text();
            let parsed = null;
            try { parsed = JSON.parse(text); } catch (_) {}
            const travelItems = Array.isArray(parsed?.travelItems) ? parsed.travelItems : [];
            let vendorCount = 0;
            for (const ti of travelItems) {
              if (Array.isArray(ti?.vendorItems)) {
                vendorCount += ti.vendorItems.length;
              }
            }
            return {
              status: r.status,
              ok: r.ok,
              content_type: r.headers.get("content-type") || "",
              travel_items_count: travelItems.length,
              vendor_items_count: vendorCount,
              text_preview: text.slice(0, 300),
            };
          } catch (e) {
            return { error: String(e) };
          }
        }
        """,
        {"url": url, "payload": payload},
    )
    return row


async def run_once(
    page,
    *,
    product_id: str,
    vendor_item_package_id: str,
    select_date: str,
    timeout_sec: float,
) -> Dict[str, Any]:
    timeout_ms = int(timeout_sec * 1000)
    rec: Dict[str, Any] = {}
    rec["trip"] = await goto_snapshot(page, TRIP_URL, timeout_ms)
    rec["login"] = await goto_snapshot(page, LOGIN_URL, timeout_ms)
    rec["mycoupang"] = await goto_snapshot(page, MYCOUPANG_URL, timeout_ms)
    rec["vendor_items_fetch_include"] = await fetch_vendor_items(
        page,
        product_id=product_id,
        vendor_item_package_id=vendor_item_package_id,
        select_date=select_date,
    )
    login_status = rec.get("login", {}).get("status")
    my_status = rec.get("mycoupang", {}).get("status")
    rec["auth_gate_blocked"] = bool(login_status == 403 or my_status in (403, 404, None))
    return rec


async def main_async(args: argparse.Namespace) -> Dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "settings": {
            "cdp_url": args.cdp_url,
            "date": args.date,
            "product_id": args.product_id,
            "vendor_item_package_id": args.vendor_item_package_id,
            "repeat": args.repeat,
            "interval_sec": args.interval_sec,
            "timeout_sec": args.timeout_sec,
        },
        "runs": [],
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(args.cdp_url)
        try:
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()

            for i in range(1, args.repeat + 1):
                row = await run_once(
                    page,
                    product_id=args.product_id,
                    vendor_item_package_id=args.vendor_item_package_id,
                    select_date=args.date,
                    timeout_sec=args.timeout_sec,
                )
                row["attempt"] = i
                report["runs"].append(row)
                fetch = row.get("vendor_items_fetch_include", {})
                print(
                    f"[attempt {i}] login={row.get('login', {}).get('status')}:{row.get('login', {}).get('title')} "
                    f"my={row.get('mycoupang', {}).get('status')} "
                    f"fetch={fetch.get('status')} travel={fetch.get('travel_items_count')} "
                    f"vendor={fetch.get('vendor_items_count')} error={fetch.get('error') or '-'}"
                )
                if i < args.repeat and args.interval_sec > 0:
                    await page.wait_for_timeout(int(args.interval_sec * 1000))
        finally:
            await browser.close()
    return report


def summarize(report: Dict[str, Any]) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = report.get("runs", [])
    login_statuses = sorted(
        {r.get("login", {}).get("status") for r in runs if r.get("login") and r.get("login", {}).get("status") is not None}
    )
    my_statuses = sorted(
        {
            r.get("mycoupang", {}).get("status")
            for r in runs
            if r.get("mycoupang") and r.get("mycoupang", {}).get("status") is not None
        }
    )
    fetch_statuses = sorted(
        {
            r.get("vendor_items_fetch_include", {}).get("status")
            for r in runs
            if r.get("vendor_items_fetch_include")
            and r.get("vendor_items_fetch_include", {}).get("status") is not None
        }
    )
    return {
        "attempt_count": len(runs),
        "login_statuses": login_statuses,
        "mycoupang_statuses": my_statuses,
        "fetch_statuses": fetch_statuses,
        "login_ok_count": sum(1 for r in runs if r.get("login", {}).get("status") == 200),
        "mycoupang_ok_count": sum(1 for r in runs if r.get("mycoupang", {}).get("status") == 200),
        "fetch_ok_count": sum(
            1 for r in runs if r.get("vendor_items_fetch_include", {}).get("status") == 200
        ),
        "auth_gate_blocked_count": sum(1 for r in runs if r.get("auth_gate_blocked")),
    }


def main() -> None:
    args = parse_args()
    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(main_async(args))
    report["summary"] = summarize(report)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[coupang-cdp-session-probe] output: {output}")
    print(f"- summary: {json.dumps(report['summary'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
