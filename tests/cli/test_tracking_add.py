from datetime import datetime

import pytest

from app.cli import tracking_add


NOW = datetime(2026, 4, 30, 9, 15, 30)


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status: {self.status_code}")


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, params))
        if path.endswith("/by-path"):
            return FakeResponse({"id": 41})
        return FakeResponse([{"id": 42}])


def test_resolve_date_token_R_relative_weeks():
    assert tracking_add.resolve_date_token("2w", NOW) == "2026-05-14T09:15:30"


def test_resolve_date_token_R_relative_months():
    assert tracking_add.resolve_date_token("1mo", datetime(2026, 1, 31, 9, 0, 0)) == "2026-02-28T09:00:00"


def test_resolve_date_token_R_absolute_iso():
    assert tracking_add.resolve_date_token("2026-05-31T18:00", NOW) == "2026-05-31T18:00:00"
    assert tracking_add.resolve_date_token("2026-05-31", NOW) == "2026-05-31T00:00:00"


def test_resolve_date_token_E_invalid_token():
    with pytest.raises(tracking_add.CliError, match="토큰 형식이 잘못됨"):
        tracking_add.resolve_date_token("two-weeks", NOW)


def test_resolve_date_token_B_zero_value():
    with pytest.raises(tracking_add.CliError, match="토큰 형식이 잘못됨"):
        tracking_add.resolve_date_token("0d", NOW)


def test_cli_E_missing_both_dates(capsys):
    exit_code = tracking_add.main(["--title", "T", "--dry-run"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert tracking_add.MISSING_DATE_MESSAGE in captured.err


def test_cli_R_dry_run_payload(capsys):
    exit_code = tracking_add.main(["--title", "T", "--wait-until", "2w", "--dry-run"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"title": "T"' in captured.out
    assert '"start_at"' in captured.out
    assert "시작가능일(start_at)" in captured.out
    assert "마감기한(due_at) = <없음>" in captured.out


def test_cli_R_dry_run_deadline(capsys):
    exit_code = tracking_add.main(["--title", "T", "--deadline", "2026-05-31", "--dry-run"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"due_at": "2026-05-31T00:00:00"' in captured.out
    assert "마감기한(due_at) = 2026-05-31T00:00:00" in captured.out


def test_cli_C_earliest_check_alias():
    parser = tracking_add.build_parser()
    args = parser.parse_args(["--title", "T", "--earliest-check", "3d"])
    assert args.wait_until == "3d"


def test_lookup_plan_record_id_prefers_by_path_for_paths():
    client = FakeClient()
    assert tracking_add.lookup_plan_record_id(client, "docs/plan/foo.md") == 41
    assert client.calls == [
        ("/api/v1/plans/records/by-path", {"file_path": "docs/plan/foo.md"})
    ]


def test_lookup_plan_record_id_uses_search_for_basenames():
    client = FakeClient()
    assert tracking_add.lookup_plan_record_id(client, "foo.md") == 42
    assert client.calls == [
        ("/api/v1/plans/records", {"q": "foo.md", "limit": 10})
    ]
