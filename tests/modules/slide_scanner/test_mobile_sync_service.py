from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.services import mobile_sync


def test_list_connected_devices_R_two_devices_detected(fake_adb_path: Path):
    devices = mobile_sync.list_connected_devices(fake_adb_path)

    assert len(devices) == 2
    assert devices[0]["serial"] == "FAKE001"
    assert devices[1]["serial"] == "FAKE002"
    assert all(device["is_online"] is True for device in devices)


def test_pull_images_B_same_filename_different_devices(
    fake_adb_path: Path,
    fake_adb_add_remote_file,
    slide_scanner_test_dirs: dict[str, Path],
    monkeypatch,
):
    monkeypatch.setattr(settings, "ADB_PATH", fake_adb_path)

    remote_file = "/sdcard/DCIM/Camera/IMG_1000.jpg"
    fake_adb_add_remote_file("FAKE001", remote_file, b"device-a-image")
    fake_adb_add_remote_file("FAKE002", remote_file, b"device-b-image")

    items_a = [
        {
            "device_id": "phone-a",
            "device_serial": "FAKE001",
            "source_uri": remote_file,
            "original_filename": "IMG_1000.jpg",
        }
    ]
    items_b = [
        {
            "device_id": "phone-b",
            "device_serial": "FAKE002",
            "source_uri": remote_file,
            "original_filename": "IMG_1000.jpg",
        }
    ]

    pulled_a = mobile_sync.pull_images("FAKE001", items_a, slide_scanner_test_dirs["inbox_dir"])
    pulled_b = mobile_sync.pull_images("FAKE002", items_b, slide_scanner_test_dirs["inbox_dir"])

    assert pulled_a[0]["pull_ok"] is True
    assert pulled_b[0]["pull_ok"] is True
    assert pulled_a[0]["original_filename"] == "IMG_1000.jpg"
    assert pulled_b[0]["original_filename"] == "IMG_1000.jpg"
    assert pulled_a[0]["pc_inbox_path"] != pulled_b[0]["pc_inbox_path"]
    assert Path(pulled_a[0]["pc_inbox_path"]).exists()
    assert Path(pulled_b[0]["pc_inbox_path"]).exists()


def test_run_sync_once_E_adb_timeout_records_failed(slide_scanner_session, monkeypatch):
    monkeypatch.setattr(
        mobile_sync,
        "list_connected_devices",
        lambda _adb_path: [{"serial": "FAKE001", "is_online": True, "state": "device"}],
    )
    monkeypatch.setattr(
        mobile_sync,
        "list_remote_images",
        lambda _serial, _roots: [
            {
                "device_id": "phone-a",
                "device_serial": "FAKE001",
                "source_uri": "/sdcard/DCIM/Camera/IMG_TIMEOUT.jpg",
                "original_filename": "IMG_TIMEOUT.jpg",
            }
        ],
    )
    monkeypatch.setattr(
        mobile_sync,
        "pull_images",
        lambda _serial, _items, _inbox: [
            {
                "device_id": "phone-a",
                "device_serial": "FAKE001",
                "source_uri": "/sdcard/DCIM/Camera/IMG_TIMEOUT.jpg",
                "original_filename": "IMG_TIMEOUT.jpg",
                "pull_ok": False,
                "error_message": "adb timeout",
                "ingested_at": datetime.now(timezone.utc),
            }
        ],
    )

    result = mobile_sync.run_sync_once(slide_scanner_session)

    assert result["status"] == "ok"
    assert result["pulled"] == 0
    assert result["failed"] == 1
    assert result["pull_failed"] == 1

