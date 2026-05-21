from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.middleware import is_admin_only_read_path
from app.routes.notification import router


def _client_with_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.routes.notification.SessionLocal", Session)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_GET_alert_rules_right_returns_effective_rules(monkeypatch):
    client = _client_with_db(monkeypatch)

    response = client.get("/api/v1/notification/alert-rules")

    assert response.status_code == 200
    data = response.json()
    assert any(rule["rule_id"] == "worker_orchestrator" for rule in data)
    assert all("effective_severity" in rule for rule in data)
    assert all("effective_channel" in rule for rule in data)


def test_PUT_alert_rule_right_preserves_channel_severity_cooldown(monkeypatch):
    client = _client_with_db(monkeypatch)

    response = client.put(
        "/api/v1/notification/alert-rules/llm_requests",
        json={
            "enabled": True,
            "severity_override": "warning",
            "channel_override": "desktop",
            "cooldown_seconds": 45,
            "burst_threshold": 2,
        },
    )

    assert response.status_code == 200
    rule = response.json()["rule"]
    assert rule["effective_severity"] == "warning"
    assert rule["effective_channel"] == "desktop"
    assert rule["cooldown_seconds"] == 45
    assert rule["burst_threshold"] == 2


def test_PUT_alert_rule_error_locked_critical_returns_400(monkeypatch):
    client = _client_with_db(monkeypatch)

    response = client.put(
        "/api/v1/notification/alert-rules/worker_orchestrator",
        json={"enabled": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "LOCKED_CRITICAL_RULE"


def test_notification_alert_rules_reference_admin_only_gate():
    assert is_admin_only_read_path("/api/v1/notification/alert-rules") is True
