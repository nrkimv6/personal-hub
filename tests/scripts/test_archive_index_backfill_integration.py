"""Integration tests (실물 파일, mock 금지).

INDEX.md 쓰기·write_index·INDEX_BEGIN/END 관련 TC는 제거됨 (2026-04-24 archive INDEX.md 제거).
유지: load_whitelist, scan_archive, extract_tags, backfill_guide_blocks (가이드 AUTO 블록).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "migrations"))

import archive_index_backfill as m  # noqa: E402


def test_load_whitelist_real_schema():
    wl = m.load_whitelist()
    # 핵심 태그가 실제 wiki-schema.md에 등록되어 있어야 함
    assert {"pipeline", "worker", "watchdog", "frontend", "untagged"} <= wl


def test_backfill_real_small_sample():
    """실제 .worktrees/plans/docs/archive에서 최근 몇 건 추출 — date/title/tags 정상 필드 여부."""
    wl = m.load_whitelist()
    rows = m.scan_archive(m.ARCHIVE_DIR, wl)
    assert len(rows) >= 1
    # date 형식 검증
    for r in rows[:20]:
        assert len(r.date) == 10 and r.date[4] == "-" and r.date[7] == "-"
        assert r.title
        assert r.tags
    # 화이트리스트 외 태그 금지
    whitelist_with_untagged = wl
    for r in rows:
        for t in r.tags:
            assert t in whitelist_with_untagged, f"stray tag {t} in {r.path}"


def test_backfill_watchdog_tag_matches():
    """실제 archive에서 'watchdog' 포함 파일이 watchdog 태그를 받는지 확인."""
    wl = m.load_whitelist()
    rows = m.scan_archive(m.ARCHIVE_DIR, wl)
    watchdog_rows = [r for r in rows if "watchdog" in Path(r.path).name.lower()]
    assert watchdog_rows, "샘플에 watchdog 파일이 하나는 있어야 정상 archive 상태"
    for r in watchdog_rows:
        assert "watchdog" in r.tags


def test_backfill_guide_blocks_with_real_meta(tmp_path):
    """실제 _meta.yaml을 사용해 AUTO 블록 갱신 — 화이트리스트 외 태그 유출 없음."""
    import yaml

    meta = yaml.safe_load(m.META_PATH.read_text(encoding="utf-8"))
    # 가이드 파일 하나만 tmp로 복사 (pipeline-overview.md)
    guide_dir = tmp_path / "dev-guide"
    guide_dir.mkdir()
    src = m.DEV_GUIDE_DIR / "pipeline-overview.md"
    shutil.copy2(src, guide_dir / "pipeline-overview.md")

    wl = m.load_whitelist()
    rows = m.scan_archive(m.ARCHIVE_DIR, wl)
    partial_meta = {"pipeline-overview.md": meta["pipeline-overview.md"]}
    result = m.backfill_guide_blocks(
        rows, partial_meta, guide_dir=guide_dir, cutoff_days=365
    )
    assert "pipeline-overview.md" in result
    # last_archive_scan 갱신 확인
    assert partial_meta["pipeline-overview.md"]["last_archive_scan"] is not None
