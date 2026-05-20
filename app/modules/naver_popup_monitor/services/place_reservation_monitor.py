from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.modules.naver_popup_monitor.services.fetcher import PopupFetcher, PopupFetchResult
from app.modules.naver_popup_monitor.services.place_reservation import (
    ReservationSignal,
    ReservationState,
    extract_place_reservation_state,
)


def reservation_state_hash(state: ReservationState) -> str:
    payload = json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def merge_reservation_states(states: list[ReservationState]) -> ReservationState:
    merged = ReservationState()
    seen_signals: set[tuple[str, str, str | None]] = set()
    seen_links: set[str] = set()
    for state in states:
        merged.available = merged.available or state.available
        merged.booking_business_id = merged.booking_business_id or state.booking_business_id
        merged.booking_url = merged.booking_url or state.booking_url
        merged.ticket_count = max(merged.ticket_count, state.ticket_count)
        for link in state.concrete_links:
            if link not in seen_links:
                seen_links.add(link)
                merged.concrete_links.append(link)
        for signal in state.signals:
            key = (signal.kind, signal.path, signal.url)
            if key not in seen_signals:
                seen_signals.add(key)
                merged.signals.append(signal)
    return merged


def reservation_state_from_payload(payload: dict[str, Any]) -> ReservationState:
    state = ReservationState(
        available=bool(payload.get("available")),
        booking_business_id=payload.get("booking_business_id"),
        booking_url=payload.get("booking_url"),
        ticket_count=int(payload.get("ticket_count") or 0),
        concrete_links=list(payload.get("concrete_links") or []),
    )
    for signal in payload.get("signals") or []:
        if not isinstance(signal, dict):
            continue
        state.signals.append(
            ReservationSignal(
                kind=str(signal.get("kind") or ""),
                path=str(signal.get("path") or ""),
                value=signal.get("value"),
                url=signal.get("url"),
            )
        )
    return state


async def fetch_http_reservation_state(
    fetcher: PopupFetcher,
    url: str,
    **fetch_kwargs: Any,
) -> tuple[ReservationState, dict[str, Any], PopupFetchResult]:
    result = await fetcher.fetch_popup_html(url=url, **fetch_kwargs)
    if not result.success:
        raise RuntimeError(result.error or f"HTTP {result.status}")
    state = extract_place_reservation_state(result.html)
    return state, {
        "status": result.status,
        "final_url": result.final_url,
        "request_profile": result.request_profile,
        "proxy_url": result.proxy_url,
        "fallback_applied": result.fallback_applied,
    }, result


async def fetch_playwright_reservation_state(url: str) -> tuple[ReservationState, dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - optional environment dependency
        raise RuntimeError("playwright is not installed") from exc

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            apollo_state = await page.evaluate("() => window.__APOLLO_STATE__ || {}")
            links = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a,button,[role="button"]')).map((el) => ({
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    text: (el.innerText || el.textContent || '').trim(),
                    href: el.href || el.getAttribute('href') || '',
                    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                }))"""
            )
            state = extract_place_reservation_state(apollo_state, rendered_dom=links)
            return state, {"title": await page.title(), "link_count": len(links)}
        finally:
            await browser.close()


async def collect_place_reservation_sample(
    fetcher: PopupFetcher,
    url: str,
    *,
    browser_fallback_enabled: bool = False,
    request_profile: str = "A",
    fallback_strategy: str = "reinforce",
    monitor_proxy_enabled: bool = False,
) -> dict[str, Any]:
    checked_at = datetime.now()
    states: list[ReservationState] = []
    source_meta: dict[str, Any] = {}
    errors: list[str] = []
    http_result: PopupFetchResult | None = None

    try:
        http_state, http_meta, http_result = await fetch_http_reservation_state(
            fetcher,
            url,
            request_profile=request_profile,
            fallback_strategy=fallback_strategy,
            monitor_proxy_enabled=monitor_proxy_enabled,
        )
        states.append(http_state)
        source_meta["http"] = http_meta
    except Exception as exc:
        errors.append(f"http: {exc}")

    if browser_fallback_enabled:
        try:
            playwright_state, playwright_meta = await fetch_playwright_reservation_state(url)
            states.append(playwright_state)
            source_meta["playwright"] = playwright_meta
        except Exception as exc:
            errors.append(f"playwright: {exc}")

    if not states:
        return {
            "checked_at": checked_at.isoformat(),
            "ok": False,
            "errors": errors,
            "source": source_meta,
            "http_result": http_result,
        }

    state = merge_reservation_states(states)
    return {
        "checked_at": checked_at.isoformat(),
        "ok": True,
        "errors": errors,
        "source": source_meta,
        "reservation_state": state.to_dict(),
        "signals": [signal.to_dict() for signal in state.signals],
        "state_hash": reservation_state_hash(state),
        "http_result": http_result,
    }

