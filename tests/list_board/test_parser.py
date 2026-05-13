"""Parser 단위 TC."""
import pytest
from pathlib import Path

from app.modules.list_board.parser import parse_markdown_table, _parse_duration

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_duration_minutes():
    assert _parse_duration("30 minutes") == 30

def test_parse_duration_mins():
    assert _parse_duration("45 mins") == 45

def test_parse_duration_hour():
    assert _parse_duration("1 hour") == 60

def test_parse_duration_hours_minutes():
    assert _parse_duration("1 hour 45 minutes") == 105

def test_parse_duration_hours_min():
    assert _parse_duration("8 hours 30 min") == 510

def test_parse_duration_number_only():
    assert _parse_duration("30") == 30

def test_parse_duration_invalid():
    assert _parse_duration("unknown") is None


def test_parse_skill_badge_rows():
    text = (FIXTURES_DIR / "skill_badge_sample.md").read_text(encoding="utf-8")
    result = parse_markdown_table(text)
    assert len(result.items) == 3
    assert result.items[0].url == "https://www.skills.google/course_templates/60"
    assert result.items[0].duration_minutes == 90
    assert result.errors == []


def test_parse_completion_mixed():
    text = (FIXTURES_DIR / "completion_badge_mixed_sample.md").read_text(encoding="utf-8")
    result = parse_markdown_table(text)
    urls = [i.url for i in result.items]
    # 유효 URL만 추출됨 (중복 포함)
    assert "https://www.skills.google/course_templates/631" in urls
    assert "https://www.skills.google/course_templates/199" in urls
    # 불완전 행은 errors
    assert len(result.errors) >= 1


def test_parse_no_url_row_goes_to_errors():
    text = "| No url here | 30 minutes |\n|---|---|\n| Also no url | 1 hour |"
    result = parse_markdown_table(text)
    assert len(result.items) == 0
    assert len(result.errors) >= 1
