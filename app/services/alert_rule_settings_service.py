"""Alert rule settings service.

The failure alert registry is code-owned. This service stores and reads only
operator overrides, then returns an effective read model for the UI and sender.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.notification import AlertRuleOverrideUpdate, AlertRuleSettingsResponse
from app.services.failure_alert_policy import AlertRule, AlertSeverity, build_failure_alert_registry

ALERT_RULE_SETTINGS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS alert_rule_settings (
    rule_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    severity_override TEXT,
    channel_override TEXT,
    cooldown_seconds INTEGER,
    burst_threshold INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

ALERT_RULE_CHANNELS = {"telegram", "desktop", "ui_only"}
ALERT_RULE_SEVERITIES = {severity.value for severity in AlertSeverity}
DEFAULT_ALERT_RULE_CHANNEL = "telegram"
DEFAULT_COOLDOWN_SECONDS = 300


@dataclass(frozen=True)
class AlertRulePolicy:
    rule_id: str
    enabled: bool
    severity: AlertSeverity
    severity_override: AlertSeverity | None
    channel: str
    cooldown_seconds: int
    burst_threshold: int | None
    locked: bool
    stale: bool = False


def ensure_alert_rule_settings_table(db: Session) -> None:
    db.execute(text(ALERT_RULE_SETTINGS_TABLE_DDL))


def get_effective_alert_rules(
    db: Session,
    registry: dict[str, AlertRule] | None = None,
) -> list[AlertRuleSettingsResponse]:
    """Return registry defaults merged with persisted overrides."""
    ensure_alert_rule_settings_table(db)
    registry = registry or build_failure_alert_registry()
    overrides = _load_overrides(db)

    rows: list[AlertRuleSettingsResponse] = []
    for rule_id in sorted(registry):
        rows.append(_build_response(rule_id, registry[rule_id], overrides.get(rule_id), stale=False))

    for stale_rule_id in sorted(set(overrides) - set(registry)):
        rows.append(_build_stale_response(stale_rule_id, overrides[stale_rule_id]))

    return rows


def get_effective_alert_rule_policy(
    db: Session,
    rule_id: str,
    registry: dict[str, AlertRule] | None = None,
) -> AlertRulePolicy | None:
    rules = get_effective_alert_rules(db, registry=registry)
    for rule in rules:
        if rule.rule_id == rule_id:
            return AlertRulePolicy(
                rule_id=rule.rule_id,
                enabled=rule.enabled,
                severity=AlertSeverity(rule.effective_severity),
                severity_override=AlertSeverity(rule.severity_override) if rule.severity_override else None,
                channel=rule.effective_channel,
                cooldown_seconds=rule.cooldown_seconds,
                burst_threshold=rule.burst_threshold,
                locked=rule.locked,
                stale=rule.stale,
            )
    return None


def update_alert_rule_override(
    db: Session,
    rule_id: str,
    payload: AlertRuleOverrideUpdate,
    expected_version: int | None = None,
    registry: dict[str, AlertRule] | None = None,
) -> AlertRuleSettingsResponse:
    """Persist a user override and return the effective rule."""
    ensure_alert_rule_settings_table(db)
    registry = registry or build_failure_alert_registry()
    rule = registry.get(rule_id)
    if rule is None:
        raise ValueError("ALERT_RULE_NOT_FOUND")

    current = _load_overrides(db).get(rule_id)
    _validate_expected_version(current, expected_version, payload)
    _validate_payload(rule, payload)

    merged = {
        "enabled": int(payload.enabled if payload.enabled is not None else _row_bool(current, "enabled", True)),
        "severity_override": payload.severity_override if payload.severity_override is not None else _row_value(current, "severity_override"),
        "channel_override": payload.channel_override if payload.channel_override is not None else _row_value(current, "channel_override"),
        "cooldown_seconds": payload.cooldown_seconds if payload.cooldown_seconds is not None else _row_value(current, "cooldown_seconds"),
        "burst_threshold": payload.burst_threshold if payload.burst_threshold is not None else _row_value(current, "burst_threshold"),
    }

    if current is None:
        version = 1
        db.execute(text("""
            INSERT INTO alert_rule_settings (
                rule_id, enabled, severity_override, channel_override,
                cooldown_seconds, burst_threshold, version, updated_at
            )
            VALUES (
                :rule_id, :enabled, :severity_override, :channel_override,
                :cooldown_seconds, :burst_threshold, :version, CURRENT_TIMESTAMP
            )
        """), {"rule_id": rule_id, "version": version, **merged})
    else:
        version = int(current["version"] or 0) + 1
        db.execute(text("""
            UPDATE alert_rule_settings
            SET enabled = :enabled,
                severity_override = :severity_override,
                channel_override = :channel_override,
                cooldown_seconds = :cooldown_seconds,
                burst_threshold = :burst_threshold,
                version = :version,
                updated_at = CURRENT_TIMESTAMP
            WHERE rule_id = :rule_id
        """), {"rule_id": rule_id, "version": version, **merged})

    db.commit()
    updated = _load_overrides(db).get(rule_id)
    return _build_response(rule_id, rule, updated, stale=False)


def _load_overrides(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.execute(text("""
        SELECT rule_id, enabled, severity_override, channel_override,
               cooldown_seconds, burst_threshold, version, updated_at
        FROM alert_rule_settings
    """)).mappings().all()
    return {str(row["rule_id"]): dict(row) for row in rows}


def _build_response(
    rule_id: str,
    rule: AlertRule,
    override: dict[str, Any] | None,
    *,
    stale: bool,
) -> AlertRuleSettingsResponse:
    default_severity = rule.default_severity.value
    severity_override = _valid_severity(_row_value(override, "severity_override"))
    channel_override = _valid_channel(_row_value(override, "channel_override"))
    cooldown_seconds = _int_or_default(_row_value(override, "cooldown_seconds"), DEFAULT_COOLDOWN_SECONDS)
    burst_threshold = _int_or_none(_row_value(override, "burst_threshold"))
    enabled = _row_bool(override, "enabled", True)

    effective_severity = severity_override or default_severity
    effective_channel = channel_override or DEFAULT_ALERT_RULE_CHANNEL

    return AlertRuleSettingsResponse(
        rule_id=rule_id,
        source=rule.source,
        enabled=enabled,
        default_severity=default_severity,
        effective_severity=effective_severity,
        default_channel=DEFAULT_ALERT_RULE_CHANNEL,
        effective_channel=effective_channel,
        severity_override=severity_override,
        channel_override=channel_override,
        cooldown_seconds=cooldown_seconds,
        burst_threshold=burst_threshold,
        locked=_is_locked(rule),
        stale=stale,
        has_override=override is not None,
        version=_int_or_none(_row_value(override, "version")),
        updated_at=_timestamp_or_none(_row_value(override, "updated_at")),
    )


def _build_stale_response(rule_id: str, override: dict[str, Any]) -> AlertRuleSettingsResponse:
    severity_override = _valid_severity(_row_value(override, "severity_override"))
    channel_override = _valid_channel(_row_value(override, "channel_override"))
    return AlertRuleSettingsResponse(
        rule_id=rule_id,
        source=rule_id,
        enabled=_row_bool(override, "enabled", True),
        default_severity="record_only",
        effective_severity=severity_override or "record_only",
        default_channel=DEFAULT_ALERT_RULE_CHANNEL,
        effective_channel=channel_override or DEFAULT_ALERT_RULE_CHANNEL,
        severity_override=severity_override,
        channel_override=channel_override,
        cooldown_seconds=_int_or_default(_row_value(override, "cooldown_seconds"), DEFAULT_COOLDOWN_SECONDS),
        burst_threshold=_int_or_none(_row_value(override, "burst_threshold")),
        locked=False,
        stale=True,
        has_override=True,
        version=_int_or_none(_row_value(override, "version")),
        updated_at=_timestamp_or_none(_row_value(override, "updated_at")),
    )


def _validate_expected_version(
    current: dict[str, Any] | None,
    expected_version: int | None,
    payload: AlertRuleOverrideUpdate,
) -> None:
    expected = expected_version if expected_version is not None else payload.expected_version
    if expected is not None:
        current_version = _int_or_none(_row_value(current, "version"))
        if current_version != expected:
            raise ValueError("ALERT_RULE_STALE_WRITE")

    if payload.expected_updated_at is not None:
        current_updated_at = _timestamp_or_none(_row_value(current, "updated_at"))
        if current_updated_at != payload.expected_updated_at:
            raise ValueError("ALERT_RULE_STALE_WRITE")


def _validate_payload(rule: AlertRule, payload: AlertRuleOverrideUpdate) -> None:
    if payload.severity_override is not None and payload.severity_override not in ALERT_RULE_SEVERITIES:
        raise ValueError("INVALID_ALERT_RULE_SEVERITY")
    if payload.channel_override is not None and payload.channel_override not in ALERT_RULE_CHANNELS:
        raise ValueError("INVALID_ALERT_RULE_CHANNEL")
    if _is_locked(rule):
        if payload.enabled is False:
            raise ValueError("LOCKED_CRITICAL_RULE")
        if payload.severity_override in {AlertSeverity.WARNING.value, AlertSeverity.RECORD_ONLY.value}:
            raise ValueError("LOCKED_CRITICAL_RULE")


def _is_locked(rule: AlertRule) -> bool:
    return rule.default_severity == AlertSeverity.CRITICAL or bool(rule.critical_kinds)


def _row_value(row: dict[str, Any] | None, key: str) -> Any:
    if not row:
        return None
    return row.get(key)


def _row_bool(row: dict[str, Any] | None, key: str, default: bool) -> bool:
    value = _row_value(row, key)
    if value is None:
        return default
    return bool(value)


def _valid_severity(value: Any) -> str | None:
    if value in ALERT_RULE_SEVERITIES:
        return str(value)
    return None


def _valid_channel(value: Any) -> str | None:
    if value in ALERT_RULE_CHANNELS:
        return str(value)
    return None


def _int_or_default(value: Any, default: int) -> int:
    parsed = _int_or_none(value)
    return default if parsed is None else parsed


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
