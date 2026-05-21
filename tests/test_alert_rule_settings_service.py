from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.schemas.notification import AlertRuleOverrideUpdate
from app.services.alert_rule_settings_service import (
    ensure_alert_rule_settings_table,
    get_effective_alert_rules,
    update_alert_rule_override,
)
from app.services.failure_alert_policy import AlertRule, AlertSeverity


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)
    db = Session()
    ensure_alert_rule_settings_table(db)
    return db


def _registry():
    return {
        "critical_rule": AlertRule(
            source="critical_rule",
            default_severity=AlertSeverity.CRITICAL,
        ),
        "warning_rule": AlertRule(
            source="warning_rule",
            default_severity=AlertSeverity.WARNING,
        ),
    }


def test_get_effective_alert_rules_right_merges_registry_and_override():
    db = _session()
    registry = _registry()

    update_alert_rule_override(
        db,
        "warning_rule",
        AlertRuleOverrideUpdate(
            enabled=False,
            severity_override="record_only",
            channel_override="desktop",
            cooldown_seconds=60,
            burst_threshold=4,
        ),
        registry=registry,
    )

    rules = {rule.rule_id: rule for rule in get_effective_alert_rules(db, registry)}

    assert rules["warning_rule"].enabled is False
    assert rules["warning_rule"].effective_severity == "record_only"
    assert rules["warning_rule"].effective_channel == "desktop"
    assert rules["warning_rule"].cooldown_seconds == 60
    assert rules["warning_rule"].burst_threshold == 4


def test_get_effective_alert_rules_boundary_no_override_uses_defaults():
    db = _session()

    rules = {rule.rule_id: rule for rule in get_effective_alert_rules(db, _registry())}

    assert rules["critical_rule"].enabled is True
    assert rules["critical_rule"].effective_severity == "critical"
    assert rules["critical_rule"].effective_channel == "telegram"


def test_update_alert_rule_override_error_locked_critical_disable_rejected():
    db = _session()

    try:
        update_alert_rule_override(
            db,
            "critical_rule",
            AlertRuleOverrideUpdate(enabled=False),
            registry=_registry(),
        )
        raised = None
    except ValueError as exc:
        raised = str(exc)

    assert raised == "LOCKED_CRITICAL_RULE"


def test_update_alert_rule_override_error_locked_critical_downgrade_rejected():
    db = _session()

    try:
        update_alert_rule_override(
            db,
            "critical_rule",
            AlertRuleOverrideUpdate(severity_override="warning"),
            registry=_registry(),
        )
        raised = None
    except ValueError as exc:
        raised = str(exc)

    assert raised == "LOCKED_CRITICAL_RULE"


def test_get_effective_alert_rules_reference_stale_override_visible():
    db = _session()
    db.execute(text("""
        INSERT INTO alert_rule_settings (
            rule_id, enabled, severity_override, channel_override,
            cooldown_seconds, burst_threshold, version
        )
        VALUES ('deleted_rule', 1, 'warning', 'telegram', 120, 3, 7)
    """))
    db.commit()

    rules = {rule.rule_id: rule for rule in get_effective_alert_rules(db, _registry())}

    assert rules["deleted_rule"].stale is True
    assert rules["deleted_rule"].effective_severity == "warning"
    assert rules["deleted_rule"].version == 7


def test_update_alert_rule_override_ordering_version_mismatch_rejected():
    db = _session()
    registry = _registry()
    first = update_alert_rule_override(
        db,
        "warning_rule",
        AlertRuleOverrideUpdate(enabled=True),
        registry=registry,
    )

    try:
        update_alert_rule_override(
            db,
            "warning_rule",
            AlertRuleOverrideUpdate(enabled=False, expected_version=(first.version or 0) - 1),
            registry=registry,
        )
        raised = None
    except ValueError as exc:
        raised = str(exc)

    assert raised == "ALERT_RULE_STALE_WRITE"
