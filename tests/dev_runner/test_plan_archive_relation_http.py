"""HTTP contract coverage for Plan Archive relation endpoints."""

from tests.dev_runner.test_plan_archive_relation_api import _make_client


def test_get_record_relations_outgoing_http_contract():
    client, engine, source_id, _target_id = _make_client()
    try:
        response = client.get(f"/api/v1/plans/records/{source_id}/relations?direction=outgoing")
        assert response.status_code == 200
        assert response.json()[0]["direction"] == "outgoing"
    finally:
        engine.dispose()


def test_get_relation_statistics_http_contract():
    client, engine, _source_id, _target_id = _make_client()
    try:
        response = client.get("/api/v1/plans/statistics/relations")
        assert response.status_code == 200
        assert response.json()["relation_counts"]["unresolved_followup"] == 1
    finally:
        engine.dispose()


def test_relation_type_filter_http_contract():
    client, engine, source_id, _target_id = _make_client()
    try:
        response = client.get(
            f"/api/v1/plans/records/{source_id}/relations?direction=outgoing&relation_type=unresolved_followup"
        )
        assert response.status_code == 200
        assert {item["relation_type"] for item in response.json()} == {"unresolved_followup"}
    finally:
        engine.dispose()
