"""Timezone helpers with Windows-friendly KST fallback."""

from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


KST_ZONEINFO_KEY = "Asia/Seoul"
_KST_ALIASES = {
    "asia/seoul",
    "kst",
    "korea standard time",
}
_KST_FIXED = timezone(timedelta(hours=9), "KST")


def get_timezone(name: str | None, default: str = KST_ZONEINFO_KEY) -> tzinfo:
    """Return an IANA timezone, falling back to fixed KST when tzdata is absent."""
    normalized = (name or default).strip()
    canonical = KST_ZONEINFO_KEY if normalized.lower() in _KST_ALIASES else normalized
    try:
        return ZoneInfo(canonical)
    except ZoneInfoNotFoundError:
        if canonical == KST_ZONEINFO_KEY:
            return _KST_FIXED
        raise
