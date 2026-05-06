"""Unit tests for scripts/migrations/archive_index_backfill.py (RIGHT-BICEP + CORRECT)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "migrations"))

import archive_index_backfill as m  # noqa: E402


# ---------- extract_meta ----------

def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_extract_meta_R_normal(tmp_path):
    p = _write(
        tmp_path,
        "2026-03-20_foo.md",
        "# 제목입니다\n\n> 메타\n\n첫 단락입니다.\n",
    )
    meta = m.extract_meta(p)
    assert meta["date"] == "2026-03-20"
    assert meta["title"] == "제목입니다"
    assert meta["one_liner"] == "첫 단락입니다."


def test_extract_meta_B_no_h1(tmp_path):
    p = _write(tmp_path, "2026-01-01_bar.md", "본문만 있음\n")
    meta = m.extract_meta(p)
    assert meta["title"] == "2026-01-01_bar"  # 파일명 stem 폴백


def test_extract_meta_B_long_one_liner(tmp_path):
    long_line = "가" * 200
    p = _write(tmp_path, "2026-01-01_x.md", f"# t\n\n{long_line}\n")
    meta = m.extract_meta(p)
    # 80자 + ellipsis
    assert len(meta["one_liner"]) <= 81


def test_extract_meta_E_invalid_filename(tmp_path):
    p = _write(tmp_path, "no-date.md", "# t\n")
    with pytest.raises(ValueError):
        m.extract_meta(p)


# ---------- extract_tags ----------

WHITELIST = {
    "pipeline", "skill", "worker", "watchdog", "frontend",
    "dev-server", "crawler", "untagged", "test",
}


def test_extract_tags_R_match():
    tags = m.extract_tags(
        "2026-01-01_watchdog-fix.md",
        "watchdog architecture fix",
        "worker process killed",
        WHITELIST,
    )
    assert "watchdog" in tags
    assert "worker" in tags


def test_extract_tags_B_no_match():
    tags = m.extract_tags("2026-01-01_xyz.md", "random title", "body", WHITELIST)
    assert tags == ["untagged"]


def test_extract_tags_Co_whitelist_only():
    """CORRECT/Conformance: 화이트리스트 외 단어는 결과에 포함되지 않음."""
    tags = m.extract_tags(
        "2026-01-01_redis-thing.md",
        "redis cache kubernetes helm",  # 모두 화이트리스트 밖
        "",
        WHITELIST,
    )
    assert tags == ["untagged"]
    assert "redis" not in tags
    assert "kubernetes" not in tags


def test_extract_tags_E_empty_whitelist():
    tags = m.extract_tags("2026-01-01_x.md", "pipeline", "", set())
    assert tags == ["untagged"]


# ---------- load_whitelist ----------

def test_load_whitelist_R_parse(tmp_path):
    schema = _write(
        tmp_path,
        "wiki-schema.md",
        "blah\n## 3. 태그 Vocabulary\n\n```\npipeline skill\nworker watchdog\nuntagged\n```\n",
    )
    wl = m.load_whitelist(schema)
    assert {"pipeline", "skill", "worker", "watchdog", "untagged"} <= wl


def test_load_whitelist_E_section_missing(tmp_path):
    schema = _write(tmp_path, "x.md", "# no vocabulary\n")
    with pytest.raises(ValueError):
        m.load_whitelist(schema)


def test_load_whitelist_E_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        m.load_whitelist(tmp_path / "nope.md")


# ---------- render_row / replace_marker_block ----------

def _row(d, tags=("pipeline",), title="t", one="o", path="docs/archive/x.md"):
    return m.ArchiveRow(date=d, tags=tags, title=title, one_liner=one, path=path)


def test_replace_marker_block_E_missing():
    with pytest.raises(ValueError):
        m.replace_marker_block("no markers", "<!-- BEGIN -->", "<!-- END -->", "x")


# ---------- scan_archive order ----------

def test_scan_archive_O_same_date_filename_asc(tmp_path):
    """CORRECT/Ordering: 동일 날짜는 파일명 사전순 (내부 정렬 안정성)."""
    _write(tmp_path, "2026-03-20_b.md", "# B\n\n본문\n")
    _write(tmp_path, "2026-03-20_a.md", "# A\n\n본문\n")
    rows = m.scan_archive(tmp_path, WHITELIST)
    assert len(rows) == 2
    # date desc 우선, 동일 날짜 내에서 파일명 asc
    names = [Path(r.path).name for r in rows]
    assert names == ["2026-03-20_a.md", "2026-03-20_b.md"]
