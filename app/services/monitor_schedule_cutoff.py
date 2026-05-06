from datetime import datetime, timedelta, timezone
from typing import Optional

_KST = timezone(timedelta(hours=9))


def get_today_kst_iso(now: Optional[datetime] = None) -> str:
    """KST 기준 오늘 날짜 ISO 문자열(YYYY-MM-DD)을 반환한다.

    monitor_schedules.date(TEXT, ISO format) 비교용 cutoff.
    """
    if now is None:
        now = datetime.now(_KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_KST)
    else:
        now = now.astimezone(_KST)
    return now.date().isoformat()
