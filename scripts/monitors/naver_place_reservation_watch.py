from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.naver_popup_monitor.services.fetcher import PopupFetcher
from app.modules.naver_popup_monitor.services.place_reservation import (
    ReservationSignal,
    ReservationState,
    build_place_reservation_url,
    extract_place_reservation_state,
)
from app.modules.naver_popup_monitor.services.place_reservation_monitor import (
    collect_place_reservation_sample,
    merge_reservation_states,
    reservation_state_from_payload,
)
from app.shared.notification import NotificationService


KST = ZoneInfo("Asia/Seoul")
DEFAULT_DURATION_HOURS = 18.0
DEFAULT_INTERVAL_SECONDS = 30.0
DEFAULT_LOG_DIR = Path("logs/naver-place-reservation-watch")

logger = logging.getLogger("naver_place_reservation_watch")


@dataclass(frozen=True)
class WatchWindow:
    started_at: datetime
    deadline: datetime
    duration_hours: float
    timezone: str = "Asia/Seoul"

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "deadline": self.deadline.isoformat(),
            "duration_hours": self.duration_hours,
            "timezone": self.timezone,
        }


def build_place_url(place_id: str) -> str:
    return build_place_reservation_url(place_id)


def parse_until(value: str, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(KST)
    raw = value.strip()
    if raw.endswith("Z"):
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        parsed = datetime.fromisoformat(raw)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    else:
        parsed = parsed.astimezone(KST)

    if parsed <= now:
        raise ValueError("--until must be in the future")
    return parsed


def compute_watch_window(
    *,
    started_at: datetime | None = None,
    duration_hours: float = DEFAULT_DURATION_HOURS,
    until: str | None = None,
) -> WatchWindow:
    started_at = started_at or datetime.now(KST)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=KST)
    else:
        started_at = started_at.astimezone(KST)

    if duration_hours <= 0:
        raise ValueError("--duration-hours must be greater than zero")

    if until:
        deadline = parse_until(until, now=started_at)
        duration_hours = (deadline - started_at).total_seconds() / 3600
    else:
        deadline = started_at + timedelta(hours=duration_hours)

    return WatchWindow(
        started_at=started_at,
        deadline=deadline,
        duration_hours=duration_hours,
    )


def state_hash(state: ReservationState) -> str:
    payload = json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        stream.write("\n")


def should_alert(previous_state: dict[str, Any] | None, current: ReservationState) -> bool:
    previous_available = bool((previous_state or {}).get("available"))
    return not previous_available and current.available


def build_alert_message(source_url: str, state: ReservationState) -> str:
    signal_lines = []
    for signal in state.signals:
        detail = signal.url or signal.value
        signal_lines.append(f"- {signal.kind}: {detail}")
    signal_text = "\n".join(signal_lines) if signal_lines else "- signal: available"
    return (
        "[네이버 Place 예약 신호 감지]\n"
        f"- url: {source_url}\n"
        f"- bookingBusinessId: {state.booking_business_id or '-'}\n"
        f"- bookingUrl: {state.booking_url or '-'}\n"
        f"- ticket_count: {state.ticket_count}\n"
        f"{signal_text}"
    )


def state_from_payload(payload: dict[str, Any]) -> ReservationState:
    return reservation_state_from_payload(payload)


async def fetch_http_state(fetcher: PopupFetcher, url: str) -> tuple[ReservationState, dict[str, Any]]:
    result = await fetcher.fetch_popup_html(url=url)
    if not result.success:
        raise RuntimeError(result.error or f"HTTP {result.status}")
    state = extract_place_reservation_state(result.html)
    return state, {
        "status": result.status,
        "final_url": result.final_url,
        "request_profile": result.request_profile,
        "proxy_url": result.proxy_url,
        "fallback_applied": result.fallback_applied,
    }


async def fetch_playwright_state(url: str) -> tuple[ReservationState, dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - environment-specific optional dependency
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


def merge_states(states: list[ReservationState]) -> ReservationState:
    return merge_reservation_states(states)


async def collect_sample(fetcher: PopupFetcher, url: str) -> dict[str, Any]:
    sample = await collect_place_reservation_sample(
        fetcher,
        url,
        browser_fallback_enabled=True,
    )
    if not sample.get("ok"):
        return {
            "checked_at": sample["checked_at"],
            "ok": False,
            "errors": sample.get("errors") or [],
        }

    return {
        "checked_at": sample["checked_at"],
        "ok": True,
        "errors": sample.get("errors") or [],
        "source": sample.get("source") or {},
        "state": sample["reservation_state"],
        "state_hash": sample["state_hash"],
    }


async def run_watch(args: argparse.Namespace) -> int:
    source_url = args.url or build_place_url(args.place_id)
    log_dir = Path(args.log_dir)
    state_path = log_dir / "state.json"
    samples_path = log_dir / "samples.jsonl"
    alerts_path = log_dir / "alerts.jsonl"

    window = compute_watch_window(
        duration_hours=args.duration_hours,
        until=args.until,
    )
    persisted = load_state(state_path)
    if args.force_baseline:
        persisted = {}
    persisted.update(window.to_dict())
    persisted["source_url"] = source_url
    save_state(state_path, persisted)

    notification_service = NotificationService()
    fetcher = PopupFetcher()
    try:
        while datetime.now(KST) < window.deadline:
            sample = await collect_sample(fetcher, source_url)
            append_jsonl(samples_path, sample)

            if sample.get("ok"):
                current_payload = sample["state"]
                current_state = state_from_payload(current_payload)
                previous_state = persisted.get("last_normal_state")

                if should_alert(previous_state, current_state):
                    message = build_alert_message(source_url, merge_states([current_state]))
                    await notification_service.send_notification_message(
                        message,
                        send_desktop=True,
                        force_send=True,
                    )
                    alert_payload = {
                        "sent_at": datetime.now(KST).isoformat(),
                        "message": message,
                        "state": current_payload,
                    }
                    append_jsonl(alerts_path, alert_payload)
                    persisted["last_alert_state"] = current_payload

                persisted["last_normal_state"] = current_payload
                persisted["last_normal_hash"] = sample.get("state_hash")
                save_state(state_path, persisted)

            await asyncio.sleep(args.interval_seconds)
    finally:
        await fetcher.close()

    persisted["finished_at"] = datetime.now(KST).isoformat()
    save_state(state_path, persisted)
    logger.info("watch finished source_url=%s deadline=%s", source_url, window.deadline.isoformat())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch Naver Place reservation signals.")
    parser.add_argument("--place-id", default="2003552546")
    parser.add_argument("--url")
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--duration-hours", type=float, default=DEFAULT_DURATION_HOURS)
    parser.add_argument("--until")
    parser.add_argument("--force-baseline", action="store_true")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = build_parser().parse_args()
    return asyncio.run(run_watch(args))


if __name__ == "__main__":
    raise SystemExit(main())
