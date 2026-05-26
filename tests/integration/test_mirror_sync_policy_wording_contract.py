from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

POLICY_DOCS = [
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "docs/dev-guide/root-branch-guard.md",
    REPO_ROOT / "docs/dev-guide/troubleshooting.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_receiver_policy_does_not_reintroduce_blanket_pull_ban() -> None:
    combined = "\n".join(_read(path) for path in POLICY_DOCS)

    forbidden = (
        "root receiver divergence",
        "receiver divergence",
        "root `main`이 `origin/main`과 diverge된 상태에서 plain `git pull` 금지",
        "literal `git pull --ff-only` 수신만 허용한다",
    )
    for phrase in forbidden:
        assert phrase not in combined


def test_receiver_policy_uses_state_matrix_and_narrow_mirror_ban() -> None:
    combined = "\n".join(_read(path) for path in POLICY_DOCS)

    required = (
        "git rev-list --left-right --count HEAD...origin/main",
        "behind-only",
        "ahead-only",
        "diverged",
        "push-first",
        "자동화",
        "wtools source owner flow",
        "root에서 conflict를 resolve하거나 local sync merge를 만들어 닫지 않는다",
        "mirror-only sync merge",
    )
    for phrase in required:
        assert phrase in combined


def test_receiver_policy_requires_guarded_candidate_tip_receive() -> None:
    guide = _read(REPO_ROOT / "docs/dev-guide/root-branch-guard.md")

    required = (
        "scripts/services/pull-main-guarded.ps1",
        "scripts/diagnostics/check-candidate-tip.ps1",
        "duplicate_patch_blocked",
        "stale_ancestry_blocked",
        "ROOT_GUARD_ALLOW_MAIN_REBASE",
        "plain `git pull`",
    )
    for phrase in required:
        assert phrase in guide

