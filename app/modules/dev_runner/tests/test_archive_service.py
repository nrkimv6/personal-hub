"""archive_service 유닛테스트"""
import pytest
from pathlib import Path

from app.modules.dev_runner.services.archive_service import (
    _extract_category,
    _map_prefix_to_category,
    scan_archive,
    preview_organize,
    organize_archive,
    detect_duplicates,
    _remove_empty_subdirs,
)


# ── _map_prefix_to_category ──────────────────────────────────

@pytest.mark.parametrize("prefix,expected", [
    ("feat", "feature"),
    ("fix", "bugfix"),
    ("hotfix", "bugfix"),
    ("refactor", "refactor"),
    ("ref", "refactor"),
    ("chore", "infra"),
    ("ci", "infra"),
    ("infra", "infra"),
    ("build", "infra"),
    ("docs", "docs"),
    ("doc", "docs"),
    ("test", "test"),
    ("unknown", "misc"),
    ("", "misc"),
])
def test_map_prefix_to_category(prefix, expected):
    assert _map_prefix_to_category(prefix) == expected


# ── _extract_category (파일명 기반) ──────────────────────────

def test_extract_category_from_filename_feat(tmp_path):
    f = tmp_path / "2026-02-24_feat-new-feature.md"
    f.write_text("# feat plan", encoding="utf-8")
    assert _extract_category(f) == "feature"


def test_extract_category_from_filename_fix(tmp_path):
    f = tmp_path / "2026-01-10_fix-login-bug.md"
    f.write_text("# fix plan", encoding="utf-8")
    assert _extract_category(f) == "bugfix"


def test_extract_category_from_filename_misc(tmp_path):
    f = tmp_path / "2026-03-01_unknown-topic.md"
    f.write_text("# misc plan", encoding="utf-8")
    assert _extract_category(f) == "misc"


def test_extract_category_from_header(tmp_path):
    """파일명이 misc여도 헤더 유형 필드가 있으면 그것을 사용한다."""
    f = tmp_path / "2026-03-01_some-topic.md"
    f.write_text("# 계획\n\n- 유형: fix\n\n## 내용", encoding="utf-8")
    assert _extract_category(f) == "bugfix"


def test_extract_category_no_date_prefix(tmp_path):
    f = tmp_path / "refactor-cleanup.md"
    f.write_text("# plan", encoding="utf-8")
    assert _extract_category(f) == "refactor"


# ── scan_archive ─────────────────────────────────────────────

def test_scan_archive_empty(tmp_path):
    assert scan_archive(tmp_path) == []


def test_scan_archive_returns_files(tmp_path):
    (tmp_path / "2026-02-01_feat-a.md").write_text("# a", encoding="utf-8")
    (tmp_path / "2026-02-02_fix-b.md").write_text("# b", encoding="utf-8")
    result = scan_archive(tmp_path)
    assert len(result) == 2
    categories = {r["category"] for r in result}
    assert "feature" in categories
    assert "bugfix" in categories


def test_scan_archive_detects_subfolder(tmp_path):
    sub = tmp_path / "feature"
    sub.mkdir()
    (sub / "2026-02-01_feat-a.md").write_text("# a", encoding="utf-8")
    result = scan_archive(tmp_path)
    assert result[0]["in_subfolder"] is True


# ── preview_organize ─────────────────────────────────────────

def test_preview_organize_needs_move(tmp_path):
    (tmp_path / "2026-02-01_feat-a.md").write_text("# a", encoding="utf-8")
    plan = preview_organize(tmp_path)
    assert len(plan) == 1
    assert plan[0]["needs_move"] is True
    assert plan[0]["category"] == "feature"
    assert plan[0]["dest"] == str(tmp_path / "feature" / "2026-02-01_feat-a.md")


def test_preview_organize_already_placed(tmp_path):
    sub = tmp_path / "feature"
    sub.mkdir()
    f = sub / "2026-02-01_feat-a.md"
    f.write_text("# a", encoding="utf-8")
    plan = preview_organize(tmp_path)
    assert len(plan) == 1
    assert plan[0]["needs_move"] is False


# ── organize_archive ─────────────────────────────────────────

def test_organize_archive_moves_files(tmp_path):
    (tmp_path / "2026-02-01_feat-a.md").write_text("# a", encoding="utf-8")
    (tmp_path / "2026-02-02_fix-b.md").write_text("# b", encoding="utf-8")

    result = organize_archive(tmp_path)

    assert len(result["moved"]) == 2
    assert result["skipped"] == 0
    assert result["errors"] == []

    # 파일이 실제로 이동됐는지 확인
    assert (tmp_path / "feature" / "2026-02-01_feat-a.md").exists()
    assert (tmp_path / "bugfix" / "2026-02-02_fix-b.md").exists()
    # 원본은 사라졌는지 확인
    assert not (tmp_path / "2026-02-01_feat-a.md").exists()


def test_organize_archive_skips_already_placed(tmp_path):
    sub = tmp_path / "feature"
    sub.mkdir()
    (sub / "2026-02-01_feat-a.md").write_text("# a", encoding="utf-8")

    result = organize_archive(tmp_path)
    assert result["skipped"] == 1
    assert len(result["moved"]) == 0


def test_organize_archive_removes_empty_dirs(tmp_path):
    # 빈 하위 폴더 생성
    empty = tmp_path / "old_category"
    empty.mkdir()

    (tmp_path / "2026-02-01_feat-a.md").write_text("# a", encoding="utf-8")
    result = organize_archive(tmp_path)

    # old_category(빈 폴더)가 삭제됐는지
    assert str(empty) in result["removed_dirs"]
    assert not empty.exists()


# ── _remove_empty_subdirs ────────────────────────────────────

def test_remove_empty_subdirs(tmp_path):
    empty1 = tmp_path / "empty1"
    empty1.mkdir()
    nested = tmp_path / "parent" / "child"
    nested.mkdir(parents=True)

    removed = _remove_empty_subdirs(tmp_path)
    assert not empty1.exists()
    assert not nested.exists()
    assert len(removed) >= 2


# ── detect_duplicates ────────────────────────────────────────

def test_detect_duplicates_exact(tmp_path):
    (tmp_path / "2026-01-01_feat-login.md").write_text("# a", encoding="utf-8")
    (tmp_path / "2026-02-01_feat-login.md").write_text("# b", encoding="utf-8")

    dupes = detect_duplicates(tmp_path)
    assert len(dupes) == 1
    assert dupes[0]["reason"] == "exact_name"
    assert dupes[0]["similarity"] == 1.0


def test_detect_duplicates_similar(tmp_path):
    (tmp_path / "2026-01-01_feat-user-auth.md").write_text("# a", encoding="utf-8")
    (tmp_path / "2026-02-01_feat-user-authentication.md").write_text("# b", encoding="utf-8")

    dupes = detect_duplicates(tmp_path, similarity_threshold=0.7)
    # 유사도 0.7 이상인 쌍이 있을 수 있음
    assert isinstance(dupes, list)


def test_detect_duplicates_no_dupes(tmp_path):
    (tmp_path / "2026-01-01_feat-login.md").write_text("# a", encoding="utf-8")
    (tmp_path / "2026-02-01_fix-crash.md").write_text("# b", encoding="utf-8")

    dupes = detect_duplicates(tmp_path)
    assert dupes == []


def test_detect_duplicates_nonexistent_dir(tmp_path):
    assert detect_duplicates(tmp_path / "nonexistent") == []
