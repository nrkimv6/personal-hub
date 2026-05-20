"""runner UI 가시성 판별 — 단일 진실 원천 (Single Source of Truth)

runner가 dev-runner UI에 표시되어야 하는지 판별하는 유일한 함수.

설계 원칙:
- 화이트리스트 방식: "표시"가 명시된 트리거만 visible (fail-closed)
- executor_service.py (REST) 와 event_service.py (SSE) 모두 이 함수를 호출
- 이 파일을 수정하면 두 경로가 동시에 반영됨
"""
from __future__ import annotations

from pathlib import Path


_USER_VISIBLE_TRIGGERS = {"user", "user:all"}
_SYNTHETIC_PLAN_BASENAMES = {
    "test.md",
    "blocked-plan.md",
    "approval-t5.md",
    "approval-t5b.md",
    "orphan.md",
}
_SYNTHETIC_PATH_MARKERS = (
    ".dev-runner-smoke",
    "pytest-",
    "pytest-of-",
    "fakeredis",
)


def is_visible_runner(trigger: str | None, runner_id: str) -> bool:
    """runner가 UI에 표시되어야 하는지 판별한다.

    화이트리스트 + 이중 방어 방식:
    1. runner_id가 "tc-pytest-" 접두사면 → 항상 False (pytest 러너 이중 방어)
    2. trigger가 "user" 또는 "user:all"이면 → True
    3. 그 외 (None, "", "api", "tc:*", "manual" 등) → False

    Args:
        trigger: Redis에서 읽은 trigger 값 (None 허용)
        runner_id: Redis runner ID

    Returns:
        True면 UI 탭에 표시, False면 숨김
    """
    if runner_id.startswith("tc-pytest-"):
        return False
    return bool(trigger and trigger in _USER_VISIBLE_TRIGGERS)


def is_visible_runner_evidence(
    *,
    runner_id: str,
    trigger: str | None,
    plan_file: str | None = None,
    worktree_path: str | None = None,
    branch: str | None = None,
    redis_missing: bool | None = None,
    status: str | None = None,
    test_source: str | None = None,
    log_file: str | None = None,
) -> bool:
    """Evidence-aware runtime UI visibility gate.

    Legacy ``is_visible_runner()`` remains a trigger helper for old call sites and
    script parity. Runtime read surfaces must also prove that the runner belongs
    to a real plan, because tests can directly seed Redis/DB rows with
    ``trigger=user``.
    """
    del redis_missing, status  # reserved evidence fields; callers pass them for parity.
    if not is_visible_runner(trigger, runner_id):
        return False
    if test_source:
        return False
    if _has_synthetic_negative_evidence(plan_file, worktree_path, branch):
        return False
    has_plan_evidence = _has_real_plan_evidence(plan_file)
    if not has_plan_evidence and _has_synthetic_negative_evidence(log_file):
        return False
    return has_plan_evidence


def _has_synthetic_negative_evidence(*values: str | None) -> bool:
    for value in values:
        if not value:
            continue
        normalized = str(value).replace("\\", "/").lower()
        if Path(normalized).name in _SYNTHETIC_PLAN_BASENAMES:
            return True
        if any(marker in normalized for marker in _SYNTHETIC_PATH_MARKERS):
            return True
    return False


def _has_real_plan_evidence(plan_file: str | None) -> bool:
    if not plan_file:
        return False
    text = str(plan_file).strip()
    if not text or text == "__ALL_PLANS__":
        return False
    if _has_synthetic_negative_evidence(text):
        return False
    return any(candidate.is_file() for candidate in _plan_file_candidates(text))


def _plan_file_candidates(plan_file: str) -> list[Path]:
    raw = Path(plan_file)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        root = _project_root()
        normalized = Path(plan_file.replace("\\", "/"))
        for repo_root in _repo_roots(root):
            candidates.extend(
                [
                    repo_root / normalized,
                    repo_root / ".worktrees" / "plans" / normalized,
                ]
            )
    return candidates


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _repo_roots(root: Path) -> list[Path]:
    roots = [root]
    if root.parent.name == ".worktrees":
        roots.append(root.parent.parent)
    return roots
