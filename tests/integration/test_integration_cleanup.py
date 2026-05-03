"""Deterministic tests for HTTP integration cleanup helpers."""

from tests.integration.conftest import IntegrationResourceCleanup


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeHttpClient:
    def __init__(self, statuses=None, exception_at=None):
        self.calls: list[tuple[str, float]] = []
        self.statuses = list(statuses or [])
        self.exception_at = exception_at

    def delete(self, url: str, timeout: float):
        self.calls.append((url, timeout))
        if self.exception_at is not None and len(self.calls) == self.exception_at:
            raise RuntimeError("delete failed")
        status = self.statuses.pop(0) if self.statuses else 204
        return FakeResponse(status)


def test_cleanup_deletes_items_before_businesses_and_dedupes_ids():
    http = FakeHttpClient()
    cleanup = IntegrationResourceCleanup("http://testserver/", http_client=http, timeout=1.5)

    cleanup.add_business(10)
    cleanup.add_business("10")
    cleanup.add_item(20)
    cleanup.add_item("21")
    cleanup.add_item(20)

    failures = cleanup.cleanup()

    assert failures == []
    assert http.calls == [
        ("http://testserver/api/v1/items/21", 1.5),
        ("http://testserver/api/v1/items/20", 1.5),
        ("http://testserver/api/v1/businesses/10", 1.5),
    ]


def test_cleanup_accepts_import_url_response_payload():
    http = FakeHttpClient()
    cleanup = IntegrationResourceCleanup("http://testserver", http_client=http)

    cleanup.add_import_result({"business_id": "10", "item_id": "20"})

    cleanup.cleanup()

    assert [url for url, _timeout in http.calls] == [
        "http://testserver/api/v1/items/20",
        "http://testserver/api/v1/businesses/10",
    ]


def test_cleanup_boundary_404_is_ok():
    http = FakeHttpClient(statuses=[404, 404])
    cleanup = IntegrationResourceCleanup("http://testserver", http_client=http)
    cleanup.add_item(20)
    cleanup.add_business(10)

    failures = cleanup.cleanup()

    assert failures == []


def test_cleanup_rejects_unexpected_success_status():
    http = FakeHttpClient(statuses=[200])
    cleanup = IntegrationResourceCleanup("http://testserver", http_client=http)
    cleanup.add_item(20)

    failures = cleanup.cleanup()

    assert len(failures) == 1
    assert failures[0].path == "/api/v1/items/20"
    assert failures[0].error == "status_code=200"


def test_cleanup_is_fail_safe_and_reports_failures_for_explicit_checks():
    http = FakeHttpClient(statuses=[500], exception_at=2)
    cleanup = IntegrationResourceCleanup("http://testserver", http_client=http)
    cleanup.add_item(20)
    cleanup.add_business(10)

    failures = cleanup.cleanup()

    assert [failure.path for failure in failures] == [
        "/api/v1/items/20",
        "/api/v1/businesses/10",
    ]
    assert all(failure.method == "DELETE" for failure in failures)
