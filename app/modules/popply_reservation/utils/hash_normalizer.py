"""Normalize POPPLY reservation hash values for scheduleGroup matching."""

from urllib.parse import unquote


def normalize_schedule_group_hash(value: str) -> str:
    raw = (value or "").strip()
    if "%25" in raw:
        return unquote(raw)
    return raw
