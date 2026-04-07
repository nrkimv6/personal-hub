"""Integration tests (실물 파일, mock 금지)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import archive_index_backfill as m  # noqa: E402


def test_load_whitelist_real_schema():
    wl = m.load_whitelist()
    # 핵심 태그가 실제 wiki-schema.md에 등록되어 있어야 함
    assert {"pipeline", "worker", "watchdog", "frontend", "untagged"} <= wl


def test_backfill_real_small_sample():
    """실제 docs/archive에서 최근 몇 건 추출 — date/title/tags 정상 필드 여부."""
    wl = m.load_whitelist()
    rows = m.scan_archive(m.ARCHIVE_DIR, wl)
    assert len(rows) >= 10  # 826건이 있으니 충분히 많음
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


def test_backfill_idempotent(tmp_path):
    """동일 입력 2회 실행 시 INDEX.md 바이트 동등 (idempotent)."""
    # 실 archive 5개 샘플을 tmp로 복사
    samples = sorted(m.ARCHIVE_DIR.glob("*.md"))[:5]
    assert len(samples) == 5
    arc = tmp_path / "archive"
    arc.mkdir()
    for s in samples:
        shutil.copy2(s, arc / s.name)

    idx = arc / "INDEX.md"
    idx.write_text(f"# I\n\n{m.INDEX_BEGIN}\n{m.INDEX_END}\n", encoding="utf-8")

    wl = m.load_whitelist()
    rows1 = m.scan_archive(arc, wl, root=tmp_path)
    m.write_index(rows1, idx)
    first = idx.read_bytes()

    rows2 = m.scan_archive(arc, wl, root=tmp_path)
    m.write_index(rows2, idx)
    second = idx.read_bytes()

    assert first == second


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


def test_apply_end_to_end(tmp_path, monkeypatch):
    """CLI --apply 실행 시 exit code 0 + INDEX.md 갱신."""
    # 테스트 격리를 위해 tmp에 최소 환경 구성
    arc = tmp_path / "archive"
    arc.mkdir()
    # 샘플 10건 복사
    for s in sorted(m.ARCHIVE_DIR.glob("*.md"))[:10]:
        shutil.copy2(s, arc / s.name)
    idx = arc / "INDEX.md"
    idx.write_text(f"{m.INDEX_BEGIN}\n{m.INDEX_END}\n", encoding="utf-8")

    monkeypatch.setattr(m, "ARCHIVE_DIR", arc)
    monkeypatch.setattr(m, "INDEX_PATH", idx)
    # 가이드는 건드리지 않도록 빈 dict
    monkeypatch.setattr(m, "load_meta_yaml", lambda: {})
    monkeypatch.setattr(m, "save_meta_yaml", lambda d, path=None: None)

    rc = m.main(["--apply"])
    assert rc == 0
    text = idx.read_text()
    assert "2026" in text or "2025" in text  # 행이 생성됨
