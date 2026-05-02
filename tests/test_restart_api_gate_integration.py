from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gate_close_blocks_api_fetch_before_backend_status_request():
    hook = read("frontend/src/hooks.client.ts")
    assert "GATE_BLOCK_PATTERN.test(url.pathname)" in hook
    assert "apiGate.state !== 'open'" in hook
    assert "new ApiGateClosedError()" in hook


def test_gate_auto_open_after_ready_recovery_contract():
    state = read("frontend/src/lib/server/api-gate-state.ts")
    assert "const REQUIRED_READY_SUCCESSES = 3" in state
    assert "readySuccessCount >= REQUIRED_READY_SUCCESSES" in state
    assert "openGate('auto-recovery')" in state
    assert "payload?.ready === true" in state


def test_gate_close_open_full_cycle_routes_exist():
    close_route = read("frontend/src/routes/__local/api-gate/close/+server.ts")
    open_route = read("frontend/src/routes/__local/api-gate/open/+server.ts")
    status_route = read("frontend/src/routes/__local/api-gate/status/+server.ts")
    stream_route = read("frontend/src/routes/__local/api-gate/stream/+server.ts")

    assert "assertLocalRequest(event)" in close_route
    assert "closeGate(apiPort, reason)" in close_route
    assert "already_closed" in close_route
    assert "assertLocalRequest(event)" in open_route
    assert "openGate(reason)" in open_route
    assert "getGateSnapshot()" in status_route
    assert "gate_state" in stream_route
