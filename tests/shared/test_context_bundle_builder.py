"""
context_bundle_builder.py 이관 동치 TC

Phase T1: 19번 항목
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.shared.context_bundle_builder import (
    collect_files,
    concat_files,
    estimate_tokens,
    render_tree,
)


# ─── collect_files TC ─────────────────────────────────────────────────────────

def test_collect_files_R_basic_glob(tmp_path):
    """R: glob 패턴에 매칭되는 파일 수집."""
    (tmp_path / "a.py").write_text("# a")
    (tmp_path / "b.py").write_text("# b")
    (tmp_path / "c.txt").write_text("hello")

    result = collect_files(["*.py"], excludes=[], root=tmp_path)
    names = [p.name for p in result]
    assert "a.py" in names
    assert "b.py" in names
    assert "c.txt" not in names


def test_collect_files_B_empty_includes(tmp_path):
    """B: includes 빈 리스트 → 결과 없음."""
    (tmp_path / "a.py").write_text("# a")
    result = collect_files([], excludes=[], root=tmp_path)
    assert result == []


def test_collect_files_E_nonexistent_root():
    """E: root가 존재하지 않으면 FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        collect_files(["*.py"], excludes=[], root=Path("/nonexistent/path"))


def test_collect_files_excludes_default_dirs(tmp_path):
    """R: __pycache__, .git 내부 파일은 제외."""
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "cached.py").write_text("cached")
    (tmp_path / "real.py").write_text("real")

    result = collect_files(["**/*.py"], excludes=[], root=tmp_path)
    names = [p.name for p in result]
    assert "cached.py" not in names
    assert "real.py" in names


def test_collect_files_excludes_pattern(tmp_path):
    """R: excludes 패턴에 매칭되는 파일 제외."""
    (tmp_path / "keep.py").write_text("keep")
    (tmp_path / "skip.py").write_text("skip")

    result = collect_files(["*.py"], excludes=["skip.py"], root=tmp_path)
    names = [p.name for p in result]
    assert "keep.py" in names
    assert "skip.py" not in names


# ─── render_tree TC ───────────────────────────────────────────────────────────

def test_render_tree_R_nested_paths(tmp_path):
    """R: 중첩된 경로를 트리로 표현."""
    sub = tmp_path / "sub"
    sub.mkdir()
    paths = [tmp_path / "a.py", sub / "b.py"]
    result = render_tree(paths, root=tmp_path)
    assert "a.py" in result
    assert "b.py" in result
    assert "sub" in result


def test_render_tree_B_empty_list(tmp_path):
    """B: 빈 리스트 → '(파일 없음)' 반환."""
    result = render_tree([], root=tmp_path)
    assert result == "(파일 없음)"


# ─── concat_files TC ─────────────────────────────────────────────────────────

def test_concat_files_R_with_lang_map(tmp_path):
    """R: Python 파일 → python 언어 블록 포함."""
    f = tmp_path / "test.py"
    f.write_text("x = 1")
    result = concat_files([f], root=tmp_path)
    assert "```python" in result
    assert "x = 1" in result


def test_concat_files_B_binary_skipped(tmp_path):
    """B: 바이너리 파일은 스킵 (null 바이트 포함)."""
    binary_file = tmp_path / "data.bin"
    binary_file.write_bytes(b"binary\x00data")
    text_file = tmp_path / "text.py"
    text_file.write_text("normal")

    result = concat_files([binary_file, text_file], root=tmp_path)
    assert "normal" in result
    # 바이너리는 제외되었으므로 길이 검증 (binary 내용 없음)
    assert "binary" not in result


# ─── estimate_tokens TC ──────────────────────────────────────────────────────

def test_estimate_tokens_R_matches_dumptruck_formula():
    """Cross-check: dumptruck_builder.estimate_tokens 결과와 동치."""
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).parent.parent.parent / "scripts"))
    try:
        from dumptruck_builder import estimate_tokens as orig_estimate
        text = "hello world " * 100
        assert estimate_tokens(text) == orig_estimate(text)
    except ImportError:
        # 스크립트 경로 접근 불가 시 공식만 검증
        text = "a" * 400
        assert estimate_tokens(text) == 100
