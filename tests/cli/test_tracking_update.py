from argparse import Namespace
from datetime import datetime

import pytest

from app.cli import tracking_update


NOW = datetime(2026, 4, 30, 9, 15, 30)


def _args(**overrides):
    values = {
        "id": 3,
        "title": None,
        "description": None,
        "wait_until": None,
        "deadline": None,
        "clear_wait_until": False,
        "clear_deadline": False,
        "dry_run": False,
        "api_base": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_build_update_payload_R_clear_deadline_emits_null():
    payload = tracking_update.build_update_payload(_args(clear_deadline=True), now=NOW)
    assert "due_at" in payload
    assert payload["due_at"] is None


def test_build_update_payload_R_omits_unspecified():
    payload = tracking_update.build_update_payload(_args(title="T"), now=NOW)
    assert payload == {"title": "T"}
    assert "start_at" not in payload
    assert "due_at" not in payload


def test_build_update_payload_R_wait_until_token():
    payload = tracking_update.build_update_payload(_args(wait_until="2w"), now=NOW)
    assert payload["start_at"] == "2026-05-14T09:15:30"


def test_build_update_payload_R_combined_set_and_clear():
    payload = tracking_update.build_update_payload(
        _args(wait_until="2w", clear_deadline=True),
        now=NOW,
    )
    assert payload["start_at"] == "2026-05-14T09:15:30"
    assert payload["due_at"] is None


def test_cli_E_missing_id():
    parser = tracking_update.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--wait-until", "2w"])
    assert exc_info.value.code == 2


def test_cli_E_clear_and_set_conflict(capsys):
    exit_code = tracking_update.main(
        ["--id", "3", "--clear-deadline", "--deadline", "2026-05-31"]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "`--clear-deadline`과 `--deadline`은 동시에 지정할 수 없습니다." in captured.err


def test_cli_E_no_fields_to_update(capsys):
    exit_code = tracking_update.main(["--id", "3"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert tracking_update.NO_FIELDS_MESSAGE in captured.err


def test_cli_C_earliest_check_alias():
    parser = tracking_update.build_parser()
    args = parser.parse_args(["--id", "3", "--earliest-check", "2w"])
    assert args.wait_until == "2w"


def test_cli_R_dry_run_no_http_call(monkeypatch, capsys):
    def fail_client(*_args, **_kwargs):
        raise AssertionError("dry-run must not create an HTTP client")

    monkeypatch.setattr(tracking_update.httpx, "Client", fail_client)
    exit_code = tracking_update.main(["--id", "3", "--wait-until", "2w", "--dry-run"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DRY-RUN: tracking item update payload" in captured.out
    assert "item id=3" in captured.out
    assert "시작가능일(start_at)" in captured.out
    assert "마감기한(due_at) = <변경 없음>" in captured.out
    assert '"start_at"' in captured.out
