from __future__ import annotations

from app.modules.slide_scanner.routers import mobile_sync as mobile_sync_router


def test_mobile_sync_run_R_returns_counts(slide_scanner_client, monkeypatch):
    monkeypatch.setattr(
        mobile_sync_router,
        "run_sync_once",
        lambda _db: {
            "status": "ok",
            "pulled": 2,
            "inserted": 2,
            "skipped": 0,
            "failed": 0,
        },
    )

    response = slide_scanner_client.post("/api/v1/ss/mobile-sync/run", json={"background": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["inserted"] == 2
    assert payload["failed"] == 0


def test_mobile_sync_devices_E_adb_unavailable_degraded(slide_scanner_client, monkeypatch):
    def _raise(*_args, **_kwargs):
        raise RuntimeError("adb not found")

    monkeypatch.setattr(mobile_sync_router, "list_connected_devices", _raise)

    response = slide_scanner_client.get("/api/v1/ss/mobile-sync/devices")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["devices"] == []
    assert "adb not found" in (payload["error"] or "")


def test_mobile_sync_status_T_last_run_timestamp_updated(slide_scanner_client, monkeypatch):
    monkeypatch.setattr(
        mobile_sync_router,
        "get_sync_status",
        lambda: {
            "is_running": False,
            "last_started_at": "2026-04-03T11:00:00+00:00",
            "last_finished_at": "2026-04-03T11:00:05+00:00",
            "last_result": {"status": "ok"},
            "last_error": None,
        },
    )

    response = slide_scanner_client.get("/api/v1/ss/mobile-sync/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["last_started_at"] == "2026-04-03T11:00:00+00:00"
    assert payload["last_finished_at"] == "2026-04-03T11:00:05+00:00"

