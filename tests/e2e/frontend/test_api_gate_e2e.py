import json
import time

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _snapshot(state: str, reason: str = "e2e gate", api_port: int | None = 8001) -> dict:
    return {
        "state": state,
        "reason": "" if state == "open" else reason,
        "since": None if state == "open" else int(time.time() * 1000),
        "apiPort": None if state == "open" else api_port,
        "recentEvents": [],
    }


def _install_gate_stream(page: Page, initial_snapshot: dict) -> None:
    initial_json = json.dumps(initial_snapshot)
    script = """
        (() => {{
            const initialSnapshot = __INITIAL_SNAPSHOT__;
            const gateListeners = new Set();
            window.__emitApiGateSnapshot = (snapshot) => {
                const event = { data: JSON.stringify(snapshot) };
                for (const listener of gateListeners) listener(event);
            };

            window.EventSource = class MockEventSource {
                constructor() {
                    setTimeout(() => window.__emitApiGateSnapshot(initialSnapshot), 0);
                }

                addEventListener(type, listener) {
                    if (type === 'gate_state') gateListeners.add(listener);
                }

                close() {}
            };
        }})();
        """.replace("__INITIAL_SNAPSHOT__", initial_json)
    page.add_init_script(script)


def _emit_gate_snapshot(page: Page, snapshot: dict) -> None:
    page.evaluate("(snapshot) => window.__emitApiGateSnapshot(snapshot)", snapshot)


def test_restart_api_shows_gate_overlay(page: Page, frontend_url: str):
    _install_gate_stream(page, _snapshot("recovering", "e2e close"))

    page.goto(f"{frontend_url}/")

    expect(page.get_by_text("API 서버 재시작 중").first).to_be_visible(timeout=10000)


def test_gate_overlay_clears_after_recovery(page: Page, frontend_url: str):
    _install_gate_stream(page, _snapshot("recovering", "e2e close"))
    page.goto(f"{frontend_url}/")
    expect(page.get_by_text("API 서버 재시작 중").first).to_be_visible(timeout=10000)

    _emit_gate_snapshot(page, _snapshot("open"))

    expect(page.get_by_text("API 서버 재시작 중")).to_have_count(0, timeout=10000)


def test_manual_gate_open_clears_overlay(page: Page, frontend_url: str):
    _install_gate_stream(page, _snapshot("closed", "manual e2e close"))
    page.goto(f"{frontend_url}/")
    expect(page.get_by_text("API 서버 재시작 중").first).to_be_visible(timeout=10000)

    _emit_gate_snapshot(page, _snapshot("open"))

    expect(page.get_by_text("API 서버 재시작 중")).to_have_count(0, timeout=10000)
