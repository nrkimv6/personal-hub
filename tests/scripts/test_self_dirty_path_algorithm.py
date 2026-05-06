"""dry-run TC: path-level self dirty 분류 알고리즘 검증."""
from typing import Set


def classify_dirty(baseline: Set[str], touched: Set[str], current_dirty: Set[str]) -> dict:
    """self dirty를 commit 후보와 무시 목록으로 분류한다.

    - commit_candidates: current_dirty ∩ touched (agent가 직접 수정한 dirty)
    - ignored: (current_dirty ∩ baseline) - touched (baseline에 있었고 agent가 안 건드린 dirty)
    """
    commit_candidates = current_dirty & touched
    ignored = (current_dirty & baseline) - touched
    return {"commit_candidates": commit_candidates, "ignored": ignored}


def test_preexisting_untouched_is_ignored():
    result = classify_dirty({"a.txt"}, set(), {"a.txt"})
    assert result["commit_candidates"] == set()
    assert result["ignored"] == {"a.txt"}


def test_baseline_touched_residual_is_commit_candidate():
    result = classify_dirty({"TODO.md"}, {"TODO.md"}, {"TODO.md"})
    assert "TODO.md" in result["commit_candidates"]


def test_new_untracked_touched_is_commit_candidate():
    result = classify_dirty(set(), {"docs/plan/new.md"}, {"docs/plan/new.md"})
    assert "docs/plan/new.md" in result["commit_candidates"]


def test_unrelated_dirty_not_in_commit_candidates():
    result = classify_dirty({"other.txt"}, {"TODO.md"}, {"other.txt", "TODO.md"})
    assert result["commit_candidates"] == {"TODO.md"}
    assert result["ignored"] == {"other.txt"}
