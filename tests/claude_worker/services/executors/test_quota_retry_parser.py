from datetime import datetime

from app.modules.claude_worker.services.executors.claude_executor import (
    _parse_quota_reset_until,
    _parse_quota_retry_ms,
)


def test_parse_retry_delay_ms_has_priority():
    text = "rate_limit_error retryDelayMs: 120000 resets 5:20pm (Asia/Seoul)"

    assert _parse_quota_retry_ms(text, now=datetime(2026, 5, 5, 16, 0)) == 120000


def test_parse_reset_wall_clock_pm_kst_same_day():
    now = datetime(2026, 5, 5, 16, 0)

    assert _parse_quota_reset_until("Claude usage limit resets 5:20pm (Asia/Seoul)", now=now) == datetime(
        2026, 5, 5, 17, 20
    )
    assert _parse_quota_retry_ms("resets 5:20pm (Asia/Seoul)", now=now) == 80 * 60 * 1000


def test_parse_reset_wall_clock_am_rolls_to_next_day():
    now = datetime(2026, 5, 5, 23, 30)

    assert _parse_quota_reset_until("resets 12:10am", now=now) == datetime(2026, 5, 6, 0, 10)


def test_parse_reset_after_relative_text_still_supported():
    assert _parse_quota_retry_ms("reset after 1h2m3s") == 3_723_000
