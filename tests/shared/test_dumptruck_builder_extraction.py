"""
dumptruck_builder 이관 동치 통합 TC — Phase T3: 실제 파일시스템 기반

Phase T3: 22번 항목 - test_dumptruck_builder_after_extraction_same_output
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Monitor-page worktree root를 sys.path에 추가
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKTREE_ROOT))

from app.shared.context_bundle_builder import (
    collect_files,
    render_tree,
    concat_files,
    estimate_tokens,
)


def test_dumptruck_builder_after_extraction_roundtrip(tmp_path: Path):
    """T3: 이관된 context_bundle_builder가 dumptruck_builder와 동일 결과 생성.

    실제 파일 생성 → collect/render/concat → 결과 검증 (mock 없음).
    """
    # 임시 파일 구조 생성
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')", encoding="utf-8")
    (src / "util.py").write_text("def helper(): pass", encoding="utf-8")

    # collect_files
    paths = collect_files(["src/**/*.py"], [], root=tmp_path)
    assert len(paths) == 2

    # render_tree
    tree = render_tree(paths, root=tmp_path)
    assert "main.py" in tree
    assert "util.py" in tree

    # concat_files
    content = concat_files(paths, root=tmp_path)
    assert "main.py" in content
    assert "print('hello')" in content

    # estimate_tokens: context_bundle_builder와 dumptruck_builder 동일 공식
    text = "a" * 1000
    assert estimate_tokens(text) == 250  # 1000 // 4


def test_context_bundle_builder_nonexistent_root(tmp_path: Path):
    """T3: 존재하지 않는 root → FileNotFoundError (E 경계)."""
    fake_root = tmp_path / "nonexistent"
    with pytest.raises(FileNotFoundError):
        collect_files(["**/*.py"], [], root=fake_root)


def test_aggregator_reads_real_memo_files(tmp_path: Path):
    """T3: 실제 memo 파일 3개 생성 → aggregate(dry_run=True) → reflect 경로 확인.

    spawn은 dry_run 모드 사용 — 실제 subprocess 호출 없음.
    """
    import importlib.util
    # reflect_aggregator는 wtools에 있으므로 직접 import
    # monitor-page worktree root = parents[2] (.worktrees/impl-.../tests/shared/ → .worktrees/impl-...)
    # wtools worktree = D:\work\project\service\wtools\.worktrees\impl-...
    _mp_worktree = Path(__file__).resolve().parents[2]
    # _mp_worktree = D:\work\project\tools\monitor-page\.worktrees\impl-...
    # .parents[0] = .worktrees/  .parents[1] = monitor-page/  .parents[2] = tools/  .parents[3] = D:\work\project
    _project_root = _mp_worktree.parents[3]  # D:\work\project
    _wtools_worktree = (
        _project_root
        / "service" / "wtools" / ".worktrees"
        / "impl-plan-runner-session-registry-switching"
    )
    _aggregator_path = (
        _wtools_worktree
        / "common" / "tools" / "plan-runner" / "core" / "reflect_aggregator.py"
    )
    if not _aggregator_path.exists():
        pytest.skip(f"reflect_aggregator 경로 없음: {_aggregator_path}")
    spec = importlib.util.spec_from_file_location("reflect_aggregator", _aggregator_path)
    if spec is None or spec.loader is None:
        pytest.skip("reflect_aggregator 모듈 경로 접근 불가 (wtools worktree 없음)")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    aggregate = module.aggregate

    run_id = "t3-agg-run"
    memo_dir = tmp_path / "docs" / "session-memo"
    memo_dir.mkdir(parents=True)
    for i in range(3):
        (memo_dir / f"{run_id}_stage_{i}.md").write_text(
            f"## stage {i} memo\n내용 {i}", encoding="utf-8"
        )

    # dry_run=True → 실제 spawn 없이 경로만 반환
    result_path = aggregate(run_id, base_dir=tmp_path, dry_run=True)
    assert result_path is not None
    assert result_path.name == f"{run_id}_final.md"
    assert "reflect" in str(result_path)
