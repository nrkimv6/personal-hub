from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


REPORT_TYPE_NIGHTLY_REPO_SYNC = "nightly_repo_sync"

STAGE_COLLECT = "collect"
STAGE_PLANS_COMMIT = "plans_commit"
STAGE_MAIN_FF_SYNC = "main_ff_sync"
STAGE_SYNC_WORKTREE_RESOLVE = "sync_worktree_resolve"
STAGE_MAIN_MERGE_PUSH = "main_merge_push"
STAGE_PLANS_PUSH = "plans_push"
STAGE_REPORT = "report"

BLOCK_ROOT_DIRTY = "root_dirty"
BLOCK_PLANS_POLICY_CHANGE = "plans_policy_change"
BLOCK_MIRROR_CONFLICT = "mirror_conflict"
BLOCK_DIVERGED_UNRESOLVED = "diverged_unresolved"
BLOCK_VERIFICATION_FAILED = "verification_failed"
BLOCK_PUSH_REJECTED = "push_rejected"
BLOCK_LOCK_HELD = "lock_held"
BLOCK_ROOT_GUARD_SENTINEL = "root_guard_sentinel"
BLOCK_SYNC_WORKTREE_EXISTS = "sync_worktree_exists"
BLOCK_RESOLVER_UNAVAILABLE = "resolver_unavailable"

MIRROR_SURFACES = (".agents/", ".agent/", ".claude/", ".gemini/")
PLANS_COMMIT_WHITELIST = ("docs/plan/", "docs/archive/", "docs/history/", "TODO.md", "docs/DONE.md")
DESTRUCTIVE_GIT_PATTERNS = (
    ("reset", "--hard"),
    ("clean", "-fd"),
    ("clean", "-xdf"),
    ("checkout", "."),
    ("restore", "."),
)


@dataclass
class SyncActionResult:
    stage: str
    status: str
    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    block_reason: str | None = None


@dataclass
class BranchSyncState:
    name: str | None = None
    head: str | None = None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    dirty: bool = False
    dirty_files: list[str] = field(default_factory=list)

    @property
    def diverged(self) -> bool:
        return self.ahead > 0 and self.behind > 0


@dataclass
class PlansCommitDecision:
    allowed: bool
    dirty_files: list[str] = field(default_factory=list)
    blocked_files: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    commit_created: bool = False
    commit_sha: str | None = None
    block_reason: str | None = None


@dataclass
class TrackingReportDecision:
    status: str
    title: str
    description: str
    block_reason: str | None = None


@dataclass
class RepoSyncSnapshot:
    repo_root: str
    collected_at: str
    root: BranchSyncState
    plans: BranchSyncState | None = None
    fetch: SyncActionResult | None = None
    actions: list[SyncActionResult] = field(default_factory=list)
    plans_commit: PlansCommitDecision | None = None
    tracking: TrackingReportDecision | None = None


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def is_mirror_surface_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(normalized == surface.rstrip("/") or normalized.startswith(surface) for surface in MIRROR_SURFACES)


def is_plans_commit_whitelisted(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(normalized == prefix or normalized.startswith(prefix) for prefix in PLANS_COMMIT_WHITELIST)


def _is_destructive_git_command(args: Iterable[str]) -> bool:
    tokens = tuple(str(arg) for arg in args)
    return any(all(part in tokens for part in pattern) for pattern in DESTRUCTIVE_GIT_PATTERNS)


def _parse_short_status_path(line: str) -> str:
    if len(line) <= 2:
        return line.strip()
    path = line[3:] if len(line) > 3 and line[2] == " " else line[2:].lstrip()
    if " -> " in path:
        return path.split(" -> ", 1)[1]
    return _normalize_path(path.strip())


class NightlyRepoSyncService:
    def __init__(
        self,
        repo_root: str | Path,
        *,
        commit_script: str | Path | None = None,
        resolver_command: Sequence[str] | None = None,
        sync_stamp: str | None = None,
    ):
        self.repo_root = Path(repo_root).resolve()
        self.plans_root = self.repo_root / ".worktrees" / "plans"
        self.commit_script = Path(commit_script or r"D:\work\project\tools\common\commit.ps1")
        self.resolver_command = list(resolver_command or [])
        self.sync_stamp = sync_stamp

    def run(self, *, allow_mutation: bool = True) -> RepoSyncSnapshot:
        snapshot = self.collect_snapshot(fetch=True)
        if not allow_mutation:
            snapshot.actions.append(SyncActionResult(stage=STAGE_REPORT, status="report_only"))
            snapshot.tracking = build_tracking_decision(snapshot)
            return snapshot

        snapshot.plans_commit = self.commit_plans_changes()
        snapshot.actions.append(self.sync_main_ff_or_push(snapshot.root))
        if snapshot.root.diverged:
            snapshot.actions.append(self.resolve_main_divergence())
        if snapshot.plans is not None:
            snapshot.actions.append(self.sync_plans_push_or_pull())
        snapshot.tracking = build_tracking_decision(snapshot)
        return snapshot

    def collect_snapshot(self, *, fetch: bool = True) -> RepoSyncSnapshot:
        fetch_result = self._run_git(self.repo_root, "fetch", "--all", "--prune") if fetch else None
        root_state = self._collect_branch_state(self.repo_root)
        plans_state = self._collect_branch_state(self.plans_root) if self.plans_root.exists() else None
        return RepoSyncSnapshot(
            repo_root=str(self.repo_root),
            collected_at=datetime.now().isoformat(timespec="seconds"),
            root=root_state,
            plans=plans_state,
            fetch=fetch_result,
        )

    def commit_plans_changes(self) -> PlansCommitDecision:
        if not self.plans_root.exists():
            return PlansCommitDecision(allowed=False, block_reason="plans_worktree_missing")
        dirty_files = self._status_paths(self.plans_root)
        if not dirty_files:
            return PlansCommitDecision(allowed=True)
        blocked = [path for path in dirty_files if not is_plans_commit_whitelisted(path)]
        if blocked:
            return PlansCommitDecision(
                allowed=False,
                dirty_files=dirty_files,
                blocked_files=blocked,
                block_reason=BLOCK_PLANS_POLICY_CHANGE,
            )

        for path in dirty_files:
            result = self._run_git(self.plans_root, "add", "--", path)
            if result.exit_code != 0:
                return PlansCommitDecision(
                    allowed=False,
                    dirty_files=dirty_files,
                    staged_files=dirty_files,
                    block_reason=BLOCK_PLANS_POLICY_CHANGE,
                )

        staged = self._staged_paths(self.plans_root)
        if sorted(staged) != sorted(dirty_files):
            return PlansCommitDecision(
                allowed=False,
                dirty_files=dirty_files,
                staged_files=staged,
                block_reason=BLOCK_PLANS_POLICY_CHANGE,
            )

        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.commit_script), "docs: nightly plans sync"],
            cwd=str(self.plans_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            return PlansCommitDecision(
                allowed=False,
                dirty_files=dirty_files,
                staged_files=staged,
                block_reason=BLOCK_PLANS_POLICY_CHANGE,
            )
        head = self._run_git(self.plans_root, "rev-parse", "--short=9", "HEAD")
        return PlansCommitDecision(
            allowed=True,
            dirty_files=dirty_files,
            staged_files=staged,
            commit_created=True,
            commit_sha=head.stdout.strip() if head.exit_code == 0 else None,
        )

    def sync_main_ff_or_push(self, root_state: BranchSyncState | None = None) -> SyncActionResult:
        state = root_state or self._collect_branch_state(self.repo_root)
        if self._root_guard_sentinel_exists():
            return SyncActionResult(stage=STAGE_MAIN_FF_SYNC, status="blocked", block_reason=BLOCK_ROOT_GUARD_SENTINEL)
        if state.dirty:
            return SyncActionResult(stage=STAGE_MAIN_FF_SYNC, status="blocked", block_reason=BLOCK_ROOT_DIRTY)
        if state.diverged:
            return SyncActionResult(stage=STAGE_MAIN_FF_SYNC, status="handoff", block_reason=BLOCK_DIVERGED_UNRESOLVED)
        if state.behind > 0:
            return self._run_git(self.repo_root, "pull", "--ff-only", stage=STAGE_MAIN_FF_SYNC)
        if state.ahead > 0:
            result = self._run_git(self.repo_root, "push", "origin", "main", stage=STAGE_MAIN_FF_SYNC)
            if result.exit_code != 0:
                result.status = "blocked"
                result.block_reason = BLOCK_PUSH_REJECTED
            return result
        return SyncActionResult(stage=STAGE_MAIN_FF_SYNC, status="noop")

    def sync_plans_push_or_pull(self) -> SyncActionResult:
        if not self.plans_root.exists():
            return SyncActionResult(stage=STAGE_PLANS_PUSH, status="blocked", block_reason="plans_worktree_missing")
        state = self._collect_branch_state(self.plans_root)
        if state.dirty:
            return SyncActionResult(stage=STAGE_PLANS_PUSH, status="blocked", block_reason=BLOCK_PLANS_POLICY_CHANGE)
        if state.diverged:
            return SyncActionResult(stage=STAGE_PLANS_PUSH, status="blocked", block_reason=BLOCK_DIVERGED_UNRESOLVED)
        if state.behind > 0:
            return self._run_git(self.plans_root, "pull", "--ff-only", stage=STAGE_PLANS_PUSH)
        if state.ahead > 0:
            result = self._run_git(self.plans_root, "push", "origin", "plans", stage=STAGE_PLANS_PUSH)
            if result.exit_code != 0:
                result.status = "blocked"
                result.block_reason = BLOCK_PUSH_REJECTED
            return result
        return SyncActionResult(stage=STAGE_PLANS_PUSH, status="noop")

    def resolve_main_divergence(self) -> SyncActionResult:
        """Resolve root main divergence in an isolated sync worktree.

        The sync worktree starts from local main and merges origin/main there.
        Only a clean merge can be fast-forwarded back into the root checkout.
        Mirror-surface conflicts or mirror diffs are reported as blockers.
        """
        state = self._collect_branch_state(self.repo_root)
        if self._root_guard_sentinel_exists():
            return SyncActionResult(stage=STAGE_SYNC_WORKTREE_RESOLVE, status="blocked", block_reason=BLOCK_ROOT_GUARD_SENTINEL)
        if state.dirty:
            return SyncActionResult(stage=STAGE_SYNC_WORKTREE_RESOLVE, status="blocked", block_reason=BLOCK_ROOT_DIRTY)

        stamp = self._sync_stamp()
        branch = f"codex/nightly-main-sync-{stamp}"
        worktree = self.repo_root / ".worktrees" / f"nightly-main-sync-{stamp}"
        if worktree.exists() or self._branch_exists(branch):
            return SyncActionResult(
                stage=STAGE_SYNC_WORKTREE_RESOLVE,
                status="blocked",
                command=["git", "worktree", "add", "-b", branch, str(worktree), "main"],
                block_reason=BLOCK_SYNC_WORKTREE_EXISTS,
            )

        add_result = self._run_git(self.repo_root, "worktree", "add", "-b", branch, str(worktree), "main", stage=STAGE_SYNC_WORKTREE_RESOLVE)
        if add_result.exit_code != 0:
            add_result.status = "blocked"
            add_result.block_reason = BLOCK_DIVERGED_UNRESOLVED
            return add_result

        merge_result = self._run_git(
            worktree,
            "merge",
            "origin/main",
            "--no-ff",
            "-m",
            f"chore: nightly main sync {stamp}",
            stage=STAGE_SYNC_WORKTREE_RESOLVE,
        )
        if merge_result.exit_code != 0:
            conflict_files = self._unmerged_paths(worktree)
            if any(is_mirror_surface_path(path) for path in conflict_files):
                self._run_git(worktree, "merge", "--abort", stage=STAGE_SYNC_WORKTREE_RESOLVE)
                self._cleanup_sync_worktree(worktree, branch)
                merge_result.status = "blocked"
                merge_result.block_reason = BLOCK_MIRROR_CONFLICT
                merge_result.stderr = _append_detail(merge_result.stderr, f"mirror conflict files: {', '.join(conflict_files)}")
                return merge_result
            if not self.resolver_command:
                self._run_git(worktree, "merge", "--abort", stage=STAGE_SYNC_WORKTREE_RESOLVE)
                self._cleanup_sync_worktree(worktree, branch)
                merge_result.status = "blocked"
                merge_result.block_reason = BLOCK_RESOLVER_UNAVAILABLE
                merge_result.stderr = _append_detail(merge_result.stderr, f"conflict files: {', '.join(conflict_files)}")
                return merge_result
            resolver = self._run_resolver(worktree, conflict_files)
            if resolver.status != "ok":
                self._run_git(worktree, "merge", "--abort", stage=STAGE_SYNC_WORKTREE_RESOLVE)
                self._cleanup_sync_worktree(worktree, branch)
                return resolver
            unresolved = self._unmerged_paths(worktree)
            if unresolved or self._conflict_markers_present(worktree):
                self._run_git(worktree, "merge", "--abort", stage=STAGE_SYNC_WORKTREE_RESOLVE)
                self._cleanup_sync_worktree(worktree, branch)
                return SyncActionResult(
                    stage=STAGE_SYNC_WORKTREE_RESOLVE,
                    status="blocked",
                    block_reason=BLOCK_DIVERGED_UNRESOLVED,
                    stderr=f"resolver left unresolved files: {', '.join(unresolved)}",
                )
            commit = self._run_git(worktree, "commit", "--no-edit", stage=STAGE_SYNC_WORKTREE_RESOLVE)
            if commit.exit_code != 0:
                commit.status = "blocked"
                commit.block_reason = BLOCK_DIVERGED_UNRESOLVED
                return commit

        mirror_diff = self._mirror_diff_paths(worktree, "main", "HEAD")
        if mirror_diff:
            self._cleanup_sync_worktree(worktree, branch)
            return SyncActionResult(
                stage=STAGE_SYNC_WORKTREE_RESOLVE,
                status="blocked",
                block_reason=BLOCK_MIRROR_CONFLICT,
                stderr=f"mirror diff detected: {', '.join(mirror_diff)}",
            )

        ff_result = self._run_git(self.repo_root, "merge", "--ff-only", branch, stage=STAGE_MAIN_MERGE_PUSH)
        if ff_result.exit_code != 0:
            ff_result.status = "blocked"
            ff_result.block_reason = BLOCK_DIVERGED_UNRESOLVED
            return ff_result

        push_result = self._run_git(self.repo_root, "push", "origin", "main", stage=STAGE_MAIN_MERGE_PUSH)
        self._cleanup_sync_worktree(worktree, branch)
        if push_result.exit_code != 0:
            push_result.status = "blocked"
            push_result.block_reason = BLOCK_PUSH_REJECTED
            return push_result
        return SyncActionResult(
            stage=STAGE_MAIN_MERGE_PUSH,
            status="ok",
            command=["git", "merge", "--ff-only", branch, "&&", "git", "push", "origin", "main"],
            exit_code=0,
            stdout=_append_detail(ff_result.stdout, push_result.stdout),
        )

    def _collect_branch_state(self, cwd: Path) -> BranchSyncState:
        branch = self._run_git(cwd, "branch", "--show-current")
        head = self._run_git(cwd, "rev-parse", "--short=9", "HEAD")
        upstream = self._run_git(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        ahead, behind = self._ahead_behind(cwd)
        dirty_files = self._status_paths(cwd)
        return BranchSyncState(
            name=branch.stdout.strip() if branch.exit_code == 0 else None,
            head=head.stdout.strip() if head.exit_code == 0 else None,
            upstream=upstream.stdout.strip() if upstream.exit_code == 0 else None,
            ahead=ahead,
            behind=behind,
            dirty=bool(dirty_files),
            dirty_files=dirty_files,
        )

    def _ahead_behind(self, cwd: Path) -> tuple[int, int]:
        result = self._run_git(cwd, "rev-list", "--left-right", "--count", "HEAD...@{u}")
        if result.exit_code != 0:
            return 0, 0
        parts = result.stdout.split()
        if len(parts) != 2:
            return 0, 0
        return int(parts[0]), int(parts[1])

    def _status_paths(self, cwd: Path) -> list[str]:
        result = self._run_git(cwd, "status", "--short", "-uall")
        if result.exit_code != 0:
            return []
        return [_parse_short_status_path(line) for line in result.stdout.splitlines() if line.strip()]

    def _staged_paths(self, cwd: Path) -> list[str]:
        result = self._run_git(cwd, "diff", "--cached", "--name-only")
        if result.exit_code != 0:
            return []
        return [_normalize_path(line.strip()) for line in result.stdout.splitlines() if line.strip()]

    def _root_guard_sentinel_exists(self) -> bool:
        return (self.repo_root / ".git" / "root-branch-guard.violation").exists()

    def _sync_stamp(self) -> str:
        return self.sync_stamp or datetime.now().strftime("%Y%m%d-%H%M%S")

    def _branch_exists(self, branch: str) -> bool:
        result = self._run_git(self.repo_root, "rev-parse", "--verify", f"refs/heads/{branch}")
        return result.exit_code == 0

    def _unmerged_paths(self, cwd: Path) -> list[str]:
        result = self._run_git(cwd, "diff", "--name-only", "--diff-filter=U")
        if result.exit_code != 0:
            return []
        return [_normalize_path(line.strip()) for line in result.stdout.splitlines() if line.strip()]

    def _mirror_diff_paths(self, cwd: Path, before_ref: str, after_ref: str) -> list[str]:
        result = self._run_git(cwd, "diff", "--name-only", f"{before_ref}..{after_ref}", "--", *MIRROR_SURFACES)
        if result.exit_code != 0:
            return []
        return [_normalize_path(line.strip()) for line in result.stdout.splitlines() if line.strip()]

    def _conflict_markers_present(self, cwd: Path) -> bool:
        result = self._run_git(cwd, "grep", "-n", r"<<<<<<<\|=======\|>>>>>>>")
        return result.exit_code == 0

    def _run_resolver(self, cwd: Path, conflict_files: list[str]) -> SyncActionResult:
        proc = subprocess.run(
            self.resolver_command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return SyncActionResult(
            stage=STAGE_SYNC_WORKTREE_RESOLVE,
            status="ok" if proc.returncode == 0 else "blocked",
            command=list(self.resolver_command),
            exit_code=proc.returncode,
            stdout=proc.stdout.rstrip("\n"),
            stderr=_append_detail(proc.stderr.rstrip("\n"), f"conflict files: {', '.join(conflict_files)}"),
            block_reason=None if proc.returncode == 0 else BLOCK_DIVERGED_UNRESOLVED,
        )

    def _cleanup_sync_worktree(self, worktree: Path, branch: str) -> None:
        if worktree.exists():
            self._run_git(self.repo_root, "worktree", "remove", str(worktree), stage=STAGE_SYNC_WORKTREE_RESOLVE)
        if self._branch_exists(branch):
            self._run_git(self.repo_root, "branch", "-D", branch, stage=STAGE_SYNC_WORKTREE_RESOLVE)

    def _run_git(self, cwd: Path, *args: str, stage: str = STAGE_COLLECT) -> SyncActionResult:
        if _is_destructive_git_command(args):
            return SyncActionResult(
                stage=stage,
                status="blocked",
                command=["git", *args],
                block_reason=BLOCK_VERIFICATION_FAILED,
                stderr="destructive git command denied",
            )
        proc = subprocess.run(
            ["git", "-c", "safe.directory=*", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return SyncActionResult(
            stage=stage,
            status="ok" if proc.returncode == 0 else "failed",
            command=["git", *args],
            exit_code=proc.returncode,
            stdout=proc.stdout.rstrip("\n"),
            stderr=proc.stderr.rstrip("\n"),
        )


def _append_detail(base: str, detail: str) -> str:
    if not base:
        return detail
    if not detail:
        return base
    return f"{base}\n{detail}"


def build_tracking_decision(snapshot: RepoSyncSnapshot) -> TrackingReportDecision:
    blocked = next((action for action in snapshot.actions if action.status == "blocked"), None)
    if blocked:
        return TrackingReportDecision(
            status="blocked",
            title="nightly main/plans sync blocked",
            description=render_nightly_repo_sync_report(snapshot),
            block_reason=blocked.block_reason,
        )
    return TrackingReportDecision(
        status="completed",
        title="nightly main/plans sync completed",
        description=render_nightly_repo_sync_report(snapshot),
    )


def snapshot_to_statistics_json(snapshot: RepoSyncSnapshot) -> str:
    return json.dumps(asdict(snapshot), ensure_ascii=False, default=str)


def render_nightly_repo_sync_report(snapshot: RepoSyncSnapshot) -> str:
    root = snapshot.root
    plans = snapshot.plans
    lines = [
        f"# Nightly Repo Sync Report {snapshot.collected_at}",
        "",
        f"- repo_root: `{snapshot.repo_root}`",
        f"- root: branch={root.name}, ahead={root.ahead}, behind={root.behind}, dirty={root.dirty}",
    ]
    if plans is not None:
        lines.append(f"- plans: branch={plans.name}, ahead={plans.ahead}, behind={plans.behind}, dirty={plans.dirty}")
    if snapshot.plans_commit is not None:
        lines.append(
            "- plans_commit: "
            f"allowed={snapshot.plans_commit.allowed}, created={snapshot.plans_commit.commit_created}, "
            f"block={snapshot.plans_commit.block_reason or '-'}"
        )
    if snapshot.actions:
        lines.extend(["", "## Actions"])
        for action in snapshot.actions:
            command = " ".join(action.command) if action.command else "-"
            lines.append(
                f"- {action.stage}: status={action.status}, block={action.block_reason or '-'}, "
                f"exit={action.exit_code if action.exit_code is not None else '-'}, command=`{command}`"
            )
    return "\n".join(lines)
