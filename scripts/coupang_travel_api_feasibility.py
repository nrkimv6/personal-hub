"""
Probe Coupang travel vendor-items API feasibility.

This script compares HTTP and browser-backed execution paths and stores a
structured JSON report for the plan document.

Usage example:
    python scripts/coupang_travel_api_feasibility.py --date 2026-04-20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

DEFAULT_PRODUCT_ID = "10000011218760"
DEFAULT_VENDOR_ITEM_PACKAGE_ID = "30000011218342"
DEFAULT_METHODS = ["httpx", "playwright_fetch", "playwright_context_request"]
VALID_METHODS = set(DEFAULT_METHODS)


def build_vendor_items_url(product_id: str) -> str:
    return f"https://trip.coupang.com/api/products/{product_id}/vendor-items"


def build_product_url(product_id: str) -> str:
    return f"https://trip.coupang.com/tp/products/{product_id}"


def build_legacy_product_url(product_id: str) -> str:
    return f"https://trip.coupang.com/products/{product_id}"


def load_coupang_cookies_from_storage_state(storage_state_path: Path) -> Dict[str, str]:
    """Load cookies for *.coupang.com from Playwright storage_state JSON."""
    raw = json.loads(storage_state_path.read_text(encoding="utf-8"))
    cookies = raw.get("cookies", [])
    result: Dict[str, str] = {}
    if not isinstance(cookies, list):
        return result

    for item in cookies:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain", ""))
        if "coupang.com" not in domain:
            continue
        name = str(item.get("name", "")).strip()
        value = str(item.get("value", ""))
        if not name:
            continue
        result[name] = value
    return result


def summarize_vendor_items_response(payload: Any) -> Dict[str, Any]:
    """Summarize travelItems/vendorItems path and key field presence."""
    summary: Dict[str, Any] = {
        "top_level_type": type(payload).__name__,
        "has_travelItems": False,
        "travel_items_count": 0,
        "vendor_items_count": 0,
        "field_presence": {
            "vendorItemName": False,
            "saleStatus": False,
            "stockCount": False,
            "vendorItemId": False,
        },
        "sample_vendor_item_keys": [],
    }

    if not isinstance(payload, dict):
        return summary

    travel_items = payload.get("travelItems")
    if not isinstance(travel_items, list):
        return summary

    summary["has_travelItems"] = True
    summary["travel_items_count"] = len(travel_items)

    vendor_items: List[Dict[str, Any]] = []
    for travel_item in travel_items:
        if not isinstance(travel_item, dict):
            continue
        child_items = travel_item.get("vendorItems")
        if not isinstance(child_items, list):
            continue
        for child in child_items:
            if isinstance(child, dict):
                vendor_items.append(child)

    summary["vendor_items_count"] = len(vendor_items)
    if not vendor_items:
        return summary

    first_keys = sorted(vendor_items[0].keys())
    summary["sample_vendor_item_keys"] = first_keys[:20]

    for field in summary["field_presence"]:
        summary["field_presence"][field] = any(field in item for item in vendor_items)
    return summary


def extract_vendor_item_package_ids_from_html(html: str) -> List[str]:
    """Extract candidate vendorItemPackageId values from product page HTML."""
    patterns = (
        r'vendorItemPackageId"\s*:\s*"?(?P<id>\d+)"?',
        r'vendorItemPackageIdToString"\s*:\s*"?(?P<id>\d+)"?',
    )
    found: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html):
            value = match.group("id")
            if value:
                found.append(value)
    return sorted(set(found))


def summarize_product_page_html(html: str) -> Dict[str, Any]:
    return {
        "html_length": len(html),
        "contains_vendorItemPackageId": "vendorItemPackageId" in html,
        "contains_saleStatus": "saleStatus" in html,
        "contains_stockCount": "stockCount" in html,
        "contains_travelItems": "travelItems" in html,
        "contains_vendorItems": "vendorItems" in html,
        "vendor_item_package_ids": extract_vendor_item_package_ids_from_html(html),
    }


def _safe_parse_json(text: str, content_type: str) -> Optional[Any]:
    if not text:
        return None
    if "json" not in content_type.lower():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _response_payload_preview(parsed_json: Optional[Any], text: str) -> Dict[str, Any]:
    if parsed_json is not None:
        return {"json": parsed_json, "text_preview": text[:2000]}
    return {"json": None, "text_preview": text[:2000]}


def _base_headers(product_id: str) -> Dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://trip.coupang.com",
        "referer": build_product_url(product_id),
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }


def _build_result(
    *,
    method: str,
    select_date: str,
    elapsed_ms: int,
    status_code: Optional[int],
    ok: bool,
    content_type: str,
    parsed_json: Optional[Any],
    raw_text: str,
    error: Optional[str],
    response_headers: Dict[str, str],
    attempt: int = 1,
) -> Dict[str, Any]:
    summary = summarize_vendor_items_response(parsed_json)
    return {
        "method": method,
        "select_date": select_date,
        "attempt": attempt,
        "elapsed_ms": elapsed_ms,
        "status_code": status_code,
        "ok": ok,
        "content_type": content_type,
        "error": error,
        "schema_summary": summary,
        "response_headers": response_headers,
        "response": _response_payload_preview(parsed_json, raw_text),
    }


def _pick_interest_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    wanted = (
        "server",
        "cf-ray",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    )
    lowered = {k.lower(): v for k, v in headers.items()}
    return {name: lowered[name] for name in wanted if name in lowered}


async def probe_httpx(
    *,
    product_id: str,
    vendor_item_package_id: str,
    select_date: str,
    timeout_sec: float,
    cookies: Optional[Dict[str, str]],
    attempt: int = 1,
) -> Dict[str, Any]:
    headers = _base_headers(product_id)
    payload = {
        "vendorItemPackageId": vendor_item_package_id,
        "productType": "TICKET",
        "selectDate": select_date,
    }
    url = build_vendor_items_url(product_id)

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=False) as client:
            resp = await client.post(url, headers=headers, json=payload, cookies=cookies)
        elapsed = int((time.perf_counter() - start) * 1000)
        content_type = resp.headers.get("content-type", "")
        text = resp.text
        parsed_json = _safe_parse_json(text, content_type)
        return _build_result(
            method="httpx",
            select_date=select_date,
            elapsed_ms=elapsed,
            status_code=resp.status_code,
            ok=resp.is_success,
            content_type=content_type,
            parsed_json=parsed_json,
            raw_text=text,
            error=None,
            response_headers=_pick_interest_headers(resp.headers),
            attempt=attempt,
        )
    except Exception as exc:  # pylint: disable=broad-except
        elapsed = int((time.perf_counter() - start) * 1000)
        return _build_result(
            method="httpx",
            select_date=select_date,
            elapsed_ms=elapsed,
            status_code=None,
            ok=False,
            content_type="",
            parsed_json=None,
            raw_text="",
            error=f"{type(exc).__name__}: {exc}",
            response_headers={},
            attempt=attempt,
        )


async def probe_product_page_http(*, product_id: str, timeout_sec: float) -> Dict[str, Any]:
    """Probe product page URL patterns and extract HTML-level markers."""
    tp_url = build_product_url(product_id)
    legacy_url = build_legacy_product_url(product_id)
    result: Dict[str, Any] = {
        "tp_url": {"url": tp_url, "status_code": None, "content_type": "", "location": None},
        "legacy_url": {"url": legacy_url, "status_code": None, "content_type": "", "location": None},
        "html_summary": None,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=False) as client:
            tp_resp = await client.get(tp_url)
            legacy_resp = await client.get(legacy_url)

        result["tp_url"] = {
            "url": tp_url,
            "status_code": tp_resp.status_code,
            "content_type": tp_resp.headers.get("content-type", ""),
            "location": tp_resp.headers.get("location"),
        }
        result["legacy_url"] = {
            "url": legacy_url,
            "status_code": legacy_resp.status_code,
            "content_type": legacy_resp.headers.get("content-type", ""),
            "location": legacy_resp.headers.get("location"),
        }
        if tp_resp.is_success:
            result["html_summary"] = summarize_product_page_html(tp_resp.text)
    except Exception as exc:  # pylint: disable=broad-except
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


async def probe_playwright_fetch(
    *,
    page: Any,
    product_id: str,
    vendor_item_package_id: str,
    select_date: str,
    attempt: int = 1,
) -> Dict[str, Any]:
    headers = _base_headers(product_id)
    payload = {
        "vendorItemPackageId": vendor_item_package_id,
        "productType": "TICKET",
        "selectDate": select_date,
    }
    url = build_vendor_items_url(product_id)

    script = """
async ({ url, headers, payload }) => {
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify(payload),
    });
    const contentType = resp.headers.get("content-type") || "";
    const text = await resp.text();
    let parsed = null;
    const interestHeaderNames = [
      "server",
      "cf-ray",
      "retry-after",
      "x-ratelimit-limit",
      "x-ratelimit-remaining",
      "x-ratelimit-reset"
    ];
    const interestHeaders = {};
    for (const key of interestHeaderNames) {
      const value = resp.headers.get(key);
      if (value !== null) {
        interestHeaders[key] = value;
      }
    }
    if (contentType.toLowerCase().includes("json")) {
      try {
        parsed = JSON.parse(text);
      } catch (e) {
        parsed = null;
      }
    }
    return {
      ok: resp.ok,
      status: resp.status,
      statusText: resp.statusText,
      contentType,
      interestHeaders,
      text,
      parsed,
    };
  } catch (e) {
    return {
      ok: false,
      status: null,
      statusText: "",
      contentType: "",
      interestHeaders: {},
      text: "",
      parsed: null,
      error: String(e),
    };
  }
}
"""

    start = time.perf_counter()
    try:
        raw = await page.evaluate(script, {"url": url, "headers": headers, "payload": payload})
    except Exception as exc:  # pylint: disable=broad-except
        elapsed = int((time.perf_counter() - start) * 1000)
        return _build_result(
            method="playwright_fetch",
            select_date=select_date,
            elapsed_ms=elapsed,
            status_code=None,
            ok=False,
            content_type="",
            parsed_json=None,
            raw_text="",
            error=f"{type(exc).__name__}: {exc}",
            response_headers={},
            attempt=attempt,
        )

    elapsed = int((time.perf_counter() - start) * 1000)
    if raw.get("error"):
        return _build_result(
            method="playwright_fetch",
            select_date=select_date,
            elapsed_ms=elapsed,
            status_code=raw.get("status"),
            ok=False,
            content_type=str(raw.get("contentType", "")),
            parsed_json=raw.get("parsed"),
            raw_text=str(raw.get("text", "")),
            error=str(raw.get("error")),
            response_headers=dict(raw.get("interestHeaders", {}) or {}),
            attempt=attempt,
        )
    return _build_result(
        method="playwright_fetch",
        select_date=select_date,
        elapsed_ms=elapsed,
        status_code=raw.get("status"),
        ok=bool(raw.get("ok")),
        content_type=str(raw.get("contentType", "")),
        parsed_json=raw.get("parsed"),
        raw_text=str(raw.get("text", "")),
        error=None,
        response_headers=dict(raw.get("interestHeaders", {}) or {}),
        attempt=attempt,
    )


async def probe_playwright_context_request(
    *,
    context: Any,
    product_id: str,
    vendor_item_package_id: str,
    select_date: str,
    attempt: int = 1,
) -> Dict[str, Any]:
    headers = _base_headers(product_id)
    payload = {
        "vendorItemPackageId": vendor_item_package_id,
        "productType": "TICKET",
        "selectDate": select_date,
    }
    url = build_vendor_items_url(product_id)

    start = time.perf_counter()
    try:
        resp = await context.request.post(url, headers=headers, data=payload, fail_on_status_code=False)
        text = await resp.text()
        elapsed = int((time.perf_counter() - start) * 1000)
        content_type = resp.headers.get("content-type", "")
        parsed_json = _safe_parse_json(text, content_type)
        return _build_result(
            method="playwright_context_request",
            select_date=select_date,
            elapsed_ms=elapsed,
            status_code=resp.status,
            ok=200 <= resp.status < 300,
            content_type=content_type,
            parsed_json=parsed_json,
            raw_text=text,
            error=None,
            response_headers=_pick_interest_headers(resp.headers),
            attempt=attempt,
        )
    except Exception as exc:  # pylint: disable=broad-except
        elapsed = int((time.perf_counter() - start) * 1000)
        return _build_result(
            method="playwright_context_request",
            select_date=select_date,
            elapsed_ms=elapsed,
            status_code=None,
            ok=False,
            content_type="",
            parsed_json=None,
            raw_text="",
            error=f"{type(exc).__name__}: {exc}",
            response_headers={},
            attempt=attempt,
        )


def _default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return Path("logs") / "coupang-feasibility" / f"probe_{timestamp}.json"


def _build_analysis(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result_list = list(results)
    statuses = [item.get("status_code") for item in result_list if item.get("status_code") is not None]
    has_any_http_response = bool(statuses)
    has_vendor_items = any((item.get("schema_summary") or {}).get("vendor_items_count", 0) > 0 for item in result_list)
    unauth_block_candidates = {401, 403}
    has_auth_required_signal = any(status in unauth_block_candidates for status in statuses)
    return {
        "http_response_observed": has_any_http_response,
        "observed_status_codes": sorted(set(statuses)),
        "vendor_items_observed": has_vendor_items,
        "possible_auth_required": has_auth_required_signal,
    }


async def run_probe(args: argparse.Namespace) -> Dict[str, Any]:
    methods = [m for m in args.methods if m in VALID_METHODS]
    cookies: Optional[Dict[str, str]] = None
    if args.storage_state:
        cookies = load_coupang_cookies_from_storage_state(Path(args.storage_state))

    all_results: List[Dict[str, Any]] = []
    page_probe: Optional[Dict[str, Any]] = None

    if not args.skip_page_probe:
        page_probe = await probe_product_page_http(
            product_id=args.product_id,
            timeout_sec=args.timeout_sec,
        )

    for select_date in args.dates:
        for attempt in range(1, args.repeat + 1):
            if "httpx" in methods:
                all_results.append(
                    await probe_httpx(
                        product_id=args.product_id,
                        vendor_item_package_id=args.vendor_item_package_id,
                        select_date=select_date,
                        timeout_sec=args.timeout_sec,
                        cookies=cookies,
                        attempt=attempt,
                    )
                )
            if args.interval_sec > 0 and attempt < args.repeat and not any(
                m.startswith("playwright") for m in methods
            ):
                await asyncio.sleep(args.interval_sec)

    needs_playwright = any(m.startswith("playwright") for m in methods)
    if needs_playwright:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not args.headed)
            context_kwargs: Dict[str, Any] = {}
            if args.storage_state:
                context_kwargs["storage_state"] = str(Path(args.storage_state))
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
            if not args.skip_goto:
                await page.goto(build_product_url(args.product_id), wait_until="domcontentloaded", timeout=int(args.timeout_sec * 1000))

            try:
                for select_date in args.dates:
                    for attempt in range(1, args.repeat + 1):
                        if "playwright_fetch" in methods:
                            all_results.append(
                                await probe_playwright_fetch(
                                    page=page,
                                    product_id=args.product_id,
                                    vendor_item_package_id=args.vendor_item_package_id,
                                    select_date=select_date,
                                    attempt=attempt,
                                )
                            )
                        if "playwright_context_request" in methods:
                            all_results.append(
                                await probe_playwright_context_request(
                                    context=context,
                                    product_id=args.product_id,
                                    vendor_item_package_id=args.vendor_item_package_id,
                                    select_date=select_date,
                                    attempt=attempt,
                                )
                            )
                        if args.interval_sec > 0 and attempt < args.repeat:
                            await asyncio.sleep(args.interval_sec)
            finally:
                await context.close()
                await browser.close()

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "product_id": args.product_id,
        "vendor_item_package_id": args.vendor_item_package_id,
        "dates": args.dates,
        "methods": methods,
        "storage_state": args.storage_state or None,
        "repeat": args.repeat,
        "interval_sec": args.interval_sec,
        "page_probe": page_probe,
        "results": all_results,
        "analysis": _build_analysis(all_results),
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Coupang travel vendor-items API feasibility")
    parser.add_argument("--product-id", default=DEFAULT_PRODUCT_ID, help="Coupang travel product ID")
    parser.add_argument(
        "--vendor-item-package-id",
        default=DEFAULT_VENDOR_ITEM_PACKAGE_ID,
        help="vendorItemPackageId for request body",
    )
    parser.add_argument(
        "--date",
        dest="dates",
        action="append",
        required=False,
        help="selectDate (YYYY-MM-DD). Can be repeated.",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=sorted(VALID_METHODS),
        default=DEFAULT_METHODS,
        help="Probe methods to execute",
    )
    parser.add_argument("--storage-state", help="Path to Playwright storage_state JSON (optional)")
    parser.add_argument("--headed", action="store_true", help="Run Playwright in headed mode")
    parser.add_argument("--skip-goto", action="store_true", help="Skip page.goto before browser probes")
    parser.add_argument("--skip-page-probe", action="store_true", help="Skip product page URL/HTML probe")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat count per date")
    parser.add_argument("--interval-sec", type=float, default=0.0, help="Sleep seconds between repeats")
    parser.add_argument("--timeout-sec", type=float, default=20.0, help="Request timeout in seconds")
    parser.add_argument("--output", help="Output JSON path. Default: logs/coupang-feasibility/probe_*.json")
    return parser.parse_args()


def _print_summary(report: Dict[str, Any], output_path: Path) -> None:
    print(f"[coupang-feasibility] output: {output_path}")
    page_probe = report.get("page_probe")
    if isinstance(page_probe, dict):
        tp = page_probe.get("tp_url", {})
        legacy = page_probe.get("legacy_url", {})
        html_summary = page_probe.get("html_summary", {}) or {}
        print(
            "- page_probe: "
            f"tp={tp.get('status_code')} legacy={legacy.get('status_code')} "
            f"vendorItemPackageIds={html_summary.get('vendor_item_package_ids', [])}"
        )
    for item in report["results"]:
        schema = item.get("schema_summary", {})
        print(
            f"- {item['method']} {item['select_date']}#attempt{item.get('attempt', 1)}: "
            f"status={item.get('status_code')} ok={item.get('ok')} "
            f"travelItems={schema.get('travel_items_count')} vendorItems={schema.get('vendor_items_count')} "
            f"error={item.get('error') or '-'}"
        )
    print(f"- analysis: {json.dumps(report.get('analysis', {}), ensure_ascii=False)}")


def main() -> None:
    args = parse_args()
    if not args.dates:
        args.dates = [datetime.now().strftime("%Y-%m-%d")]
    if args.repeat < 1:
        raise ValueError("--repeat must be >= 1")
    if args.interval_sec < 0:
        raise ValueError("--interval-sec must be >= 0")

    output_path = Path(args.output) if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = asyncio.run(run_probe(args))
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _print_summary(report, output_path)


if __name__ == "__main__":
    main()
