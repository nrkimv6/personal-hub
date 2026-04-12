"""
Coupang login probe via ProxyManager (same path as Naver monitoring stack).

Key path:
  ProxyManagerFactory.initialize_proxy_manager()
    -> manager.get_fresh_proxy(exclude=...) or manager.get_playwright_proxy()
    -> playwright.chromium.launch_persistent_context(..., proxy=proxy_conf)

This is test-only code; no worker/backend behavior is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from app.services.proxy_manager_factory import create_proxy_manager, initialize_proxy_manager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "logs" / "coupang-feasibility"
TRIP_URL = "https://trip.coupang.com"
LOGIN_URL = "https://login.coupang.com/login/login.pang"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coupang proxy-manager Playwright probe")
    parser.add_argument("--label", default="proxy-manager", help="Run label")
    parser.add_argument(
        "--channel",
        choices=["chromium", "chrome", "msedge"],
        default="chrome",
        help="Browser channel",
    )
    parser.add_argument("--attempts", type=int, default=10, help="Proxy attempts")
    parser.add_argument("--warmup-sec", type=float, default=15.0, help="Trip warmup seconds")
    parser.add_argument("--timeout-sec", type=float, default=45.0, help="Navigation timeout")
    parser.add_argument("--headless", action="store_true", help="Headless mode")
    parser.add_argument(
        "--selection",
        choices=["playwright", "fresh"],
        default="fresh",
        help="Proxy selection method (fresh mirrors naver retry path)",
    )
    parser.add_argument(
        "--protocols",
        default="http,https,socks5",
        help="Allowed proxy protocols (comma-separated)",
    )
    parser.add_argument(
        "--fixed-proxy-url",
        help="Use one fixed proxy URL for all attempts (e.g. http://1.2.3.4:8080)",
    )
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="Ignore HTTPS certificate errors in browser context",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "db", "file"],
        default="auto",
        help="Proxy backend",
    )
    parser.add_argument(
        "--include-baseline",
        action="store_true",
        help="Run one baseline (no proxy) before proxy attempts",
    )
    parser.add_argument(
        "--stop-on-success",
        action="store_true",
        help="Stop attempts when first login success is observed",
    )
    parser.add_argument("--output", help="Output JSON path")
    return parser.parse_args()


def default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return OUTPUT_DIR / f"proxy_manager_probe_{ts}.json"


def proxy_conf_to_url(proxy_conf: Dict[str, Any]) -> str:
    server = str(proxy_conf.get("server") or "")
    if not server:
        return ""
    parsed = urlparse(server)
    username = proxy_conf.get("username")
    password = proxy_conf.get("password")
    if username:
        return f"{parsed.scheme}://{username}:{password or ''}@{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


def proxy_url_to_playwright_conf(proxy_url: str) -> Optional[Dict[str, Any]]:
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return None
    conf: Dict[str, Any] = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        conf["username"] = parsed.username
        conf["password"] = parsed.password or ""
    return conf


async def run_single(
    *,
    channel: str,
    timeout_sec: float,
    warmup_sec: float,
    headless: bool,
    profile_dir: Path,
    proxy_conf: Optional[Dict[str, Any]],
    ignore_https_errors: bool,
) -> Dict[str, Any]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    timeout_ms = int(timeout_sec * 1000)
    out: Dict[str, Any] = {
        "ok": False,
        "error": None,
        "proxy": proxy_conf,
        "trip_status": None,
        "trip_title_initial": "",
        "trip_title_after_warmup": "",
        "login_status": None,
        "login_title": "",
        "login_ok": False,
        "runtime_user_agent": "",
    }

    launch_kwargs: Dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "viewport": {"width": 1280, "height": 800},
        "ignore_https_errors": ignore_https_errors,
        "args": ["--window-size=1280,800", "--window-position=120,120"],
    }
    if channel != "chromium":
        launch_kwargs["channel"] = channel
    if proxy_conf:
        launch_kwargs["proxy"] = proxy_conf

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

                out["login_ok"] = bool(out["login_status"] == 200 and out["login_title"] == "로그인")
                out["ok"] = True
                return out
            finally:
                await context.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
        return out


async def build_proxy_manager(backend: str):
    if backend == "auto":
        return await initialize_proxy_manager()

    manager = create_proxy_manager(backend=backend)
    if manager and hasattr(manager, "initialize"):
        init = getattr(manager, "initialize")
        if asyncio.iscoroutinefunction(init):
            await init()
        else:
            maybe = init()
            if asyncio.iscoroutine(maybe):
                await maybe
    return manager


async def main_async(args: argparse.Namespace) -> Dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manager = await build_proxy_manager(args.backend)

    allowed_protocols: Set[str] = {p.strip().lower() for p in args.protocols.split(",") if p.strip()}
    if not allowed_protocols:
        allowed_protocols = {"http", "https", "socks5"}

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "label": args.label,
        "settings": {
            "channel": args.channel,
            "attempts": args.attempts,
            "warmup_sec": args.warmup_sec,
            "timeout_sec": args.timeout_sec,
            "headless": args.headless,
            "selection": args.selection,
            "protocols": sorted(allowed_protocols),
            "fixed_proxy_url": args.fixed_proxy_url,
            "ignore_https_errors": args.ignore_https_errors,
            "backend": args.backend,
            "include_baseline": args.include_baseline,
            "stop_on_success": args.stop_on_success,
        },
        "proxy_manager": {
            "type": type(manager).__name__ if manager else None,
            "available": bool(getattr(manager, "is_available", False)) if manager else False,
            "pool_size": getattr(manager, "pool_size", None) if manager else None,
        },
        "baseline": None,
        "attempt_results": [],
    }

    if args.include_baseline:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        profile = PROJECT_ROOT / "data" / "browser_profiles" / f"proxyprobe_baseline_{ts}"
        baseline = await run_single(
            channel=args.channel,
            timeout_sec=args.timeout_sec,
            warmup_sec=args.warmup_sec,
            headless=args.headless,
            profile_dir=profile,
            proxy_conf=None,
            ignore_https_errors=args.ignore_https_errors,
        )
        report["baseline"] = baseline
        print(
            f"[baseline] login={baseline.get('login_status')} "
            f"title={baseline.get('login_title')} ok={baseline.get('login_ok')} "
            f"error={baseline.get('error') or '-'}"
        )

    if not manager and not args.fixed_proxy_url:
        report["error"] = "proxy_manager_unavailable"
        return report

    fixed_proxy_conf = proxy_url_to_playwright_conf(args.fixed_proxy_url) if args.fixed_proxy_url else None
    tried_proxy_urls: Set[str] = set()

    for i in range(1, args.attempts + 1):
        proxy_conf = None
        proxy_url = ""
        proxy_protocol = ""
        selected_by = args.selection

        try:
            if fixed_proxy_conf:
                selected_by = "fixed"
                proxy_conf = fixed_proxy_conf
                proxy_url = args.fixed_proxy_url or ""
            elif args.selection == "fresh" and hasattr(manager, "get_fresh_proxy"):
                fresh_url = manager.get_fresh_proxy(exclude=tried_proxy_urls)
                if fresh_url:
                    proxy_url = str(fresh_url)
                    tried_proxy_urls.add(proxy_url)
                    proxy_conf = proxy_url_to_playwright_conf(proxy_url)
            else:
                proxy_conf = manager.get_playwright_proxy()
                if proxy_conf:
                    proxy_url = proxy_conf_to_url(proxy_conf)
        except Exception as e:  # noqa: BLE001
            report["attempt_results"].append(
                {
                    "attempt": i,
                    "selected_by": selected_by,
                    "proxy_conf": None,
                    "proxy_url": "",
                    "ok": False,
                    "error": f"get_playwright_proxy_failed: {e}",
                }
            )
            continue

        if proxy_url and not proxy_conf:
            report["attempt_results"].append(
                {
                    "attempt": i,
                    "selected_by": selected_by,
                    "proxy_conf": None,
                    "proxy_url": proxy_url,
                    "ok": False,
                    "error": "invalid_proxy_url_format",
                }
            )
            continue

        if proxy_conf:
            parsed_server = urlparse(str(proxy_conf.get("server") or ""))
            proxy_protocol = (parsed_server.scheme or "").lower()

        if proxy_protocol and proxy_protocol not in allowed_protocols:
            report["attempt_results"].append(
                {
                    "attempt": i,
                    "selected_by": selected_by,
                    "proxy_conf": proxy_conf,
                    "proxy_url": proxy_url,
                    "proxy_protocol": proxy_protocol,
                    "ok": False,
                    "error": "filtered_by_protocol",
                }
            )
            continue

        if not proxy_conf:
            report["attempt_results"].append(
                {
                    "attempt": i,
                    "selected_by": selected_by,
                    "proxy_conf": None,
                    "proxy_url": "",
                    "ok": False,
                    "error": "no_proxy_returned",
                }
            )
            break

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        profile = PROJECT_ROOT / "data" / "browser_profiles" / f"proxyprobe_{i}_{ts}"
        result = await run_single(
            channel=args.channel,
            timeout_sec=args.timeout_sec,
            warmup_sec=args.warmup_sec,
            headless=args.headless,
            profile_dir=profile,
            proxy_conf=proxy_conf,
            ignore_https_errors=args.ignore_https_errors,
        )
        result["attempt"] = i
        result["selected_by"] = selected_by
        result["proxy_url"] = proxy_url
        result["proxy_protocol"] = proxy_protocol
        report["attempt_results"].append(result)

        if not result.get("login_ok") and proxy_url and manager:
            reason = result.get("error") or f"login_status={result.get('login_status')},title={result.get('login_title')}"
            try:
                if hasattr(manager, "mark_failed"):
                    manager.mark_failed(proxy_url, str(reason)[:120])
            except Exception:
                pass

        print(
            f"[attempt {i}] proxy={proxy_conf.get('server')} "
            f"protocol={proxy_protocol} "
            f"login={result.get('login_status')} title={result.get('login_title')} "
            f"ok={result.get('login_ok')} error={result.get('error') or '-'}"
        )

        if args.stop_on_success and result.get("login_ok"):
            break

    report["summary"] = {
        "attempt_count": len(report["attempt_results"]),
        "login_ok_count": sum(1 for x in report["attempt_results"] if x.get("login_ok")),
        "login_blocked_count": sum(
            1
            for x in report["attempt_results"]
            if x.get("ok") and not x.get("login_ok") and not x.get("error")
        ),
        "filtered_count": sum(
            1 for x in report["attempt_results"] if x.get("error") == "filtered_by_protocol"
        ),
        "error_count": sum(1 for x in report["attempt_results"] if x.get("error")),
    }
    return report


def main() -> None:
    args = parse_args()
    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    report = asyncio.run(main_async(args))
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[coupang-proxy-manager-probe] output: {output}")
    pm = report.get("proxy_manager", {})
    print(f"- proxy_manager: type={pm.get('type')} available={pm.get('available')} pool={pm.get('pool_size')}")
    summary = report.get("summary", {})
    if summary:
        print(
            f"- summary: attempts={summary.get('attempt_count')} "
            f"login_ok={summary.get('login_ok_count')} blocked={summary.get('login_blocked_count')} "
            f"errors={summary.get('error_count')}"
        )


if __name__ == "__main__":
    main()
