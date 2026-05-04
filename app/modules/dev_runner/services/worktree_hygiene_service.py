from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


REPORT_TYPE_WORKTREE_HYGIENE = "worktree_hygiene"
INTEREST_ACTIVE = "active"
INTEREST_NEEDS_OWNER_REVIEW = "needs_owner_review"
INTEREST_STALE_CLEANUP_CANDIDATE = "stale_cleanup_candidate"
INTEREST_STALE_LOCKED_REVIEW = "stale_locked_review"
INTEREST_KEEP_SYSTEM = "keep_system"

SOURCE_EXTENSIONS = {
    ".bat",
    ".cjs",
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sql",
    ".svelte",
    ".ts",
    ".tsx",
    ".toml",
    ".yaml",
    ".yml",
}
CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


@dataclass
class PlanHeader:
    path: str
    title: str | None = None
    status: str | None = None
    branch: str | None = None
    worktree: str | None = None
    worktree_owner: str | None = None
    archived: bool = False
    progress: str | None = None
    archive_evidence: dict[str, bool] = field(default_factory=dict)


@dataclass
class RegisteredWorktreeSnapshot:
    path: str
    branch: str | None
    head: str | None = None
    exists: bool = True
    is_root: bool = False
    is_plans: bool = False
    locked: bool = False
    locked_reason: str | None = None
    lock_age_days: int | None = None
    prunable: bool = False
    dirty_count: int = 0
    dirty_files: list[str] = field(default_factory=list)
    ahead: int = 0
    behind: int = 0
    main_includes_branch: bool | None = None
    upstream_ahead: int | None = None
    upstream_behind: int | None = None
    created_at: str | None = None
    modified_at: str | None = None
    last_commit_at: str | None = None
    plan_file: str | None = None
    plan_status: str | None = None
    archived: bool = False
    interest_level: str = INTEREST_NEEDS_OWNER_REVIEW
    cleanup_recommendation: str = "review"
    cleanable_reason: str | None = None
    required_plan_update: str = "none"
    plan_status_action: str = "none"
    risk_type: str | None = None


@dataclass
class ResidueSnapshot:
    path: str
    kind: str
    action_hint: str
    file_count: int = 0
    source_file_count: int = 0
    size_bytes: int = 0
    age_days: int | None = None
    modified_at: str | None = None
    top_level_children: list[str] = field(default_factory=list)
    delete_attempted: bool = False
    delete_status: str | None = None
    delete_error: str | None = None


@dataclass
class PlansHygieneSnapshot:
    exists: bool = False
    git_status: list[str] = field(default_factory=list)
    docs_changes: list[str] = field(default_factory=list)
    archive_changes: list[str] = field(default_factory=list)
    untracked_runtime: list[str] = field(default_factory=list)
    policy_changes: list[str] = field(default_factory=list)
    logs_gitignore_warning: bool = False
    upstream_ahead: int = 0
    upstream_behind: int = 0
    push_needed: bool = False
    header_drifts: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TrackingCandidate:
    risk_type: str
    confidence: str
    plan_path: str
    plan_title: str | None
    plan_status: str | None
    worktree_path: str
    branch: str | None
    head: str | None
    dirty_count: int
    ahead: int
    behind: int
    locked_reason: str | None = None
    main_includes_branch: bool | None = None
    archive_evidence: dict[str, bool] = field(default_factory=dict)


@dataclass
class WorktreeHygieneSnapshot:
    repo_root: str
    collected_at: str
    registered_worktrees: list[RegisteredWorktreeSnapshot] = field(default_factory=list)
    residues: list[ResidueSnapshot] = field(default_factory=list)
    plans: PlansHygieneSnapshot = field(default_factory=PlansHygieneSnapshot)
    tracking_candidates: list[TrackingCandidate] = field(default_factory=list)
    statistics: dict[str, Any] = field(default_factory=dict)


def _run_git(repo_root: Path, *args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-c", "safe.directory=*", *args],
        cwd=str(cwd or repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _safe_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or "")
    except (TypeError, ValueError):
        return default


def _path_age_days(path: Path, now: datetime) -> int | None:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None
    return max(0, (now - mtime).days)


def _path_modified_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None


def _relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _parse_worktree_porcelain(output: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {
                "path": line.removeprefix("worktree ").strip(),
                "locked": False,
                "prunable": False,
            }
            continue
        if current is None:
            continue
        if line.startswith("HEAD "):
            current["head"] = line.removeprefix("HEAD ").strip()
        elif line.startswith("branch "):
            current["branch"] = line.removeprefix("branch ").strip().removeprefix("refs/heads/")
        elif line.startswith("locked"):
            current["locked"] = True
            reason = line.removeprefix("locked").strip()
            current["locked_reason"] = reason or None
        elif line.startswith("prunable"):
            current["prunable"] = True
        elif line == "detached":
            current["detached"] = True
    if current:
        entries.append(current)
    return entries


def _parse_plan_header(path: Path, repo_root: Path, archived: bool) -> PlanHeader | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    header = PlanHeader(path=_relative_to_repo(path, repo_root), archived=archived)
    for line in text.splitlines()[:80]:
        stripped = line.strip()
        if stripped.startswith("# ") and header.title is None:
            header.title = stripped.removeprefix("# ").strip()
        elif stripped.startswith("> 상태:"):
            header.status = stripped.split(":", 1)[1].strip() or None
        elif stripped.startswith("> branch:"):
            header.branch = stripped.split(":", 1)[1].strip() or None
        elif stripped.startswith("> worktree:"):
            header.worktree = stripped.split(":", 1)[1].strip() or None
        elif stripped.startswith("> worktree-owner:"):
            header.worktree_owner = stripped.split(":", 1)[1].strip() or None
        elif stripped.startswith("> 진행률:"):
            header.progress = stripped.split(":", 1)[1].strip() or None

    header.archive_evidence = {
        "merge_commit": "머지커밋" in text or "merge commit" in text.lower(),
        "cleanup_commit": "후속정리커밋" in text or "cleanup commit" in text.lower(),
        "test_evidence": "테스트" in text or "evidence" in text.lower(),
    }
    return header


def _scan_plan_headers(repo_root: Path) -> tuple[dict[str, PlanHeader], dict[str, PlanHeader], list[PlanHeader]]:
    by_branch: dict[str, PlanHeader] = {}
    by_worktree: dict[str, PlanHeader] = {}
    headers: list[PlanHeader] = []
    for base, archived in (
        (repo_root / ".worktrees" / "plans" / "docs" / "plan", False),
        (repo_root / ".worktrees" / "plans" / "docs" / "archive", True),
    ):
        if not base.exists():
            continue
        for plan_path in sorted(base.glob("*.md")):
            header = _parse_plan_header(plan_path, repo_root, archived)
            if header is None:
                continue
            headers.append(header)
            if header.branch:
                by_branch.setdefault(header.branch, header)
            if header.worktree:
                by_worktree.setdefault(header.worktree.replace("\\", "/"), header)
    return by_branch, by_worktree, headers


def _count_dirty(path: Path) -> tuple[int, list[str]]:
    if not path.exists():
        return 0, []
    rc, stdout, _stderr = _run_git(path, "status", "--porcelain=v1", cwd=path)
    if rc != 0 or not stdout:
        return 0, []
    files: list[str] = []
    for line in stdout.splitlines():
        if len(line) >= 4:
            files.append(line[3:])
    return len(files), files


def _ahead_behind(repo_root: Path, branch: str | None, base: str = "main") -> tuple[int, int]:
    if not branch:
        return 0, 0
    rc, stdout, _stderr = _run_git(repo_root, "rev-list", "--left-right", "--count", f"{base}...{branch}")
    if rc != 0:
        return 0, 0
    parts = stdout.split()
    if len(parts) != 2:
        return 0, 0
    return _safe_int(parts[1]), _safe_int(parts[0])


def _upstream_ahead_behind(repo_root: Path, branch: str | None) -> tuple[int | None, int | None]:
    if not branch:
        return None, None
    rc, upstream, _stderr = _run_git(repo_root, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
    if rc != 0 or not upstream:
        return None, None
    rc, stdout, _stderr = _run_git(repo_root, "rev-list", "--left-right", "--count", f"{upstream}...{branch}")
    if rc != 0:
        return None, None
    parts = stdout.split()
    if len(parts) != 2:
        return None, None
    return _safe_int(parts[1]), _safe_int(parts[0])


def _last_commit_at(repo_root: Path, branch: str | None) -> str | None:
    if not branch:
        return None
    rc, stdout, _stderr = _run_git(repo_root, "log", "-1", "--format=%ai", branch)
    return stdout or None if rc == 0 else None


def _created_at(repo_root: Path, branch: str | None) -> str | None:
    if not branch:
        return None
    rc, stdout, _stderr = _run_git(repo_root, "log", "main..%s" % branch, "--format=%ai", "--reverse")
    if rc != 0:
        return None
    for line in stdout.splitlines():
        if line.strip():
            return line.strip()
    return None


def _main_includes_branch(repo_root: Path, branch: str | None) -> bool | None:
    if not branch:
        return None
    rc, _stdout, _stderr = _run_git(repo_root, "merge-base", "--is-ancestor", branch, "main")
    if rc == 0:
        return True
    if rc == 1:
        return False
    return None


def _classify_registered(snapshot: RegisteredWorktreeSnapshot, header: PlanHeader | None, stale_days: int) -> None:
    if snapshot.is_root or snapshot.is_plans:
        snapshot.interest_level = INTEREST_KEEP_SYSTEM
        snapshot.cleanup_recommendation = "keep_system"
        snapshot.cleanable_reason = "root/plans worktree"
        return
    if not snapshot.exists:
        snapshot.interest_level = INTEREST_NEEDS_OWNER_REVIEW
        snapshot.cleanup_recommendation = "git_worktree_prune_review"
        snapshot.cleanable_reason = "missing_registered_path"
        return
    if snapshot.dirty_count > 0 or snapshot.ahead > 0:
        snapshot.interest_level = INTEREST_ACTIVE
        snapshot.cleanup_recommendation = "keep_dirty_or_ahead"
        snapshot.cleanable_reason = f"dirty={snapshot.dirty_count}, ahead={snapshot.ahead}"
        return
    if header and not header.archived:
        snapshot.interest_level = INTEREST_NEEDS_OWNER_REVIEW
        snapshot.cleanup_recommendation = "blocked_plan_update_required"
        snapshot.plan_status_action = "owner_decision_required"
        snapshot.required_plan_update = "active_plan_cleanup_outcome_required"
        snapshot.cleanable_reason = "active plan linked"
        return

    old_enough = snapshot.modified_at is not None
    if snapshot.locked:
        snapshot.interest_level = INTEREST_STALE_LOCKED_REVIEW if old_enough else INTEREST_NEEDS_OWNER_REVIEW
        snapshot.cleanup_recommendation = "review_lock_before_cleanup"
        snapshot.cleanable_reason = "locked clean ahead0"
        return

    snapshot.interest_level = INTEREST_STALE_CLEANUP_CANDIDATE
    snapshot.cleanup_recommendation = "registered_worktree_cleanup_candidate"
    snapshot.cleanable_reason = "clean + ahead0 + no active owner"


def _iter_residue_files(path: Path) -> tuple[int, int, int]:
    file_count = 0
    source_count = 0
    size = 0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        file_count += 1
        try:
            size += child.stat().st_size
        except OSError:
            pass
        ignored_cache = any(part in CACHE_DIR_NAMES for part in child.parts)
        if not ignored_cache and child.suffix.lower() in SOURCE_EXTENSIONS:
            source_count += 1
    return file_count, source_count, size


def _is_cache_only(path: Path, file_count: int, source_count: int) -> bool:
    if file_count == 0 or source_count > 0:
        return False
    for child in path.rglob("*"):
        if child.is_file() and not any(part in CACHE_DIR_NAMES for part in child.parts):
            return False
    return True


def _collect_residues(
    repo_root: Path,
    registered_paths: set[str],
    retention_days: int,
    auto_delete_residue: bool,
    now: datetime,
) -> list[ResidueSnapshot]:
    worktrees_dir = repo_root / ".worktrees"
    if not worktrees_dir.exists():
        return []

    residues: list[ResidueSnapshot] = []
    for child in sorted(worktrees_dir.iterdir(), key=lambda item: item.name):
        child_key = str(child.resolve()).lower()
        if child_key in registered_paths:
            continue
        rel_path = _relative_to_repo(child, repo_root)
        modified_at = _path_modified_at(child)
        age_days = _path_age_days(child, now)
        if child.is_file():
            residues.append(
                ResidueSnapshot(
                    path=rel_path,
                    kind="file_artifact",
                    action_hint="report_only",
                    file_count=1,
                    source_file_count=1 if child.suffix.lower() in SOURCE_EXTENSIONS else 0,
                    size_bytes=child.stat().st_size,
                    age_days=age_days,
                    modified_at=modified_at,
                )
            )
            continue
        if not child.is_dir():
            residues.append(ResidueSnapshot(path=rel_path, kind="not_directory", action_hint="report_only"))
            continue
        if (child / ".git").exists():
            residues.append(ResidueSnapshot(path=rel_path, kind="git_marker_unregistered", action_hint="needs_review"))
            continue

        file_count, source_count, size = _iter_residue_files(child)
        top_children = sorted(item.name for item in child.iterdir())
        if file_count == 0:
            kind = "empty_residue"
            action = "safe_delete_candidate"
        elif _is_cache_only(child, file_count, source_count):
            kind = "cache_only_residue"
            action = "safe_delete_candidate"
        elif source_count == 0:
            kind = "data_only_residue"
            action = "safe_delete_candidate"
        else:
            kind = "source_residue"
            action = "needs_review"

        residue = ResidueSnapshot(
            path=rel_path,
            kind=kind,
            action_hint=action,
            file_count=file_count,
            source_file_count=source_count,
            size_bytes=size,
            age_days=age_days,
            modified_at=modified_at,
            top_level_children=top_children,
        )
        if auto_delete_residue and action == "safe_delete_candidate" and (age_days or 0) >= retention_days:
            residue.delete_attempted = True
            try:
                _delete_residue(repo_root, child)
                residue.delete_status = "removed" if not child.exists() else "delete_failed_or_busy"
            except Exception as exc:
                residue.delete_status = "failed"
                residue.delete_error = str(exc)
        residues.append(residue)
    return residues


def _delete_residue(repo_root: Path, target: Path) -> None:
    worktrees_dir = (repo_root / ".worktrees").resolve()
    resolved = target.resolve()
    if resolved.parent != worktrees_dir:
        raise ValueError("residue deletion must target direct .worktrees child")
    if (resolved / ".git").exists():
        raise ValueError("refusing to delete directory with .git marker")
    if not resolved.exists():
        return
    shutil.rmtree(resolved)


def _collect_plans_hygiene(
    repo_root: Path,
    registered_paths: set[str],
    plan_headers: list[PlanHeader],
) -> PlansHygieneSnapshot:
    plans_path = repo_root / ".worktrees" / "plans"
    snapshot = PlansHygieneSnapshot(exists=plans_path.exists())
    if not plans_path.exists():
        return snapshot

    rc, stdout, _stderr = _run_git(repo_root, "status", "--short", cwd=plans_path)
    if rc == 0 and stdout:
        snapshot.git_status = stdout.splitlines()
        for line in snapshot.git_status:
            path = line[3:] if len(line) > 3 else line
            normalized = path.replace("\\", "/")
            if normalized.startswith("docs/plan/"):
                snapshot.docs_changes.append(path)
            elif normalized.startswith("docs/archive/"):
                snapshot.archive_changes.append(path)
            elif normalized.startswith("logs/"):
                snapshot.untracked_runtime.append(path)
            else:
                snapshot.policy_changes.append(path)

    gitignore = plans_path / ".gitignore"
    if not gitignore.exists() or "logs/" not in gitignore.read_text(encoding="utf-8", errors="ignore"):
        snapshot.logs_gitignore_warning = True

    rc, branch, _stderr = _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD", cwd=plans_path)
    if rc == 0 and branch:
        ahead, behind = _upstream_ahead_behind(plans_path, branch)
        snapshot.upstream_ahead = ahead or 0
        snapshot.upstream_behind = behind or 0
        snapshot.push_needed = snapshot.upstream_ahead > 0

    for header in plan_headers:
        if header.archived or not header.worktree:
            continue
        worktree_path = (repo_root / header.worktree).resolve()
        if str(worktree_path).lower() not in registered_paths:
            snapshot.header_drifts.append(
                {
                    "plan_file": header.path,
                    "branch": header.branch or "",
                    "worktree": header.worktree,
                    "reason": "active_header_worktree_missing",
                }
            )
    return snapshot


def _build_tracking_candidates(
    registered: list[RegisteredWorktreeSnapshot],
    branch_headers: dict[str, PlanHeader],
) -> list[TrackingCandidate]:
    candidates: list[TrackingCandidate] = []
    for item in registered:
        header = branch_headers.get(item.branch or "")
        if not header or not header.archived:
            continue
        if header.status != "구현완료":
            continue
        if item.main_includes_branch is True:
            continue
        candidate = TrackingCandidate(
            risk_type="archive_merge_gap",
            confidence="medium" if item.dirty_count == 0 else "high",
            plan_path=header.path,
            plan_title=header.title,
            plan_status=header.status,
            worktree_path=item.path,
            branch=item.branch,
            head=item.head,
            dirty_count=item.dirty_count,
            ahead=item.ahead,
            behind=item.behind,
            locked_reason=item.locked_reason,
            main_includes_branch=item.main_includes_branch,
            archive_evidence=header.archive_evidence,
        )
        item.risk_type = candidate.risk_type
        candidates.append(candidate)
    return candidates


def _build_statistics(snapshot: WorktreeHygieneSnapshot) -> dict[str, Any]:
    stats = {
        "registered_count": len(snapshot.registered_worktrees),
        "residue_count": len(snapshot.residues),
        "tracking_candidate_count": len(snapshot.tracking_candidates),
        "plans_push_needed": snapshot.plans.push_needed,
        "plans_dirty_docs_count": len(snapshot.plans.docs_changes),
        "plans_untracked_runtime_count": len(snapshot.plans.untracked_runtime),
        "stale_locked_review_count": 0,
        "stale_cleanup_candidate_count": 0,
        "cache_only_residue_count": 0,
        "empty_residue_count": 0,
        "removed_residue_count": 0,
    }
    for item in snapshot.registered_worktrees:
        if item.interest_level == INTEREST_STALE_LOCKED_REVIEW:
            stats["stale_locked_review_count"] += 1
        if item.interest_level == INTEREST_STALE_CLEANUP_CANDIDATE:
            stats["stale_cleanup_candidate_count"] += 1
    for item in snapshot.residues:
        if item.kind == "cache_only_residue":
            stats["cache_only_residue_count"] += 1
        if item.kind == "empty_residue":
            stats["empty_residue_count"] += 1
        if item.delete_status == "removed":
            stats["removed_residue_count"] += 1
    return stats


class WorktreeHygieneService:
    def __init__(self, repo_root: Path | str | None = None):
        self.repo_root = Path(repo_root or Path(__file__).parents[4]).resolve()

    def collect(
        self,
        *,
        residue_retention_days: int = 14,
        auto_delete_residue: bool = False,
        stale_worktree_days: int = 14,
    ) -> WorktreeHygieneSnapshot:
        now = datetime.now()
        branch_headers, worktree_headers, plan_headers = _scan_plan_headers(self.repo_root)
        registered = self.collect_registered_worktrees(self.repo_root, stale_worktree_days=stale_worktree_days)
        registered_paths = {str(Path(item.path).resolve()).lower() for item in registered if item.exists}

        for item in registered:
            header = branch_headers.get(item.branch or "")
            if header is None:
                normalized = _relative_to_repo(Path(item.path), self.repo_root).replace("\\", "/")
                header = worktree_headers.get(normalized)
            if header is not None:
                item.plan_file = header.path
                item.plan_status = header.status
                item.archived = header.archived
                if header.archived:
                    item.required_plan_update = "none"
                    item.plan_status_action = "already_archived"
            _classify_registered(item, header, stale_worktree_days)

        residues = _collect_residues(
            self.repo_root,
            registered_paths,
            residue_retention_days,
            auto_delete_residue,
            now,
        )
        plans = _collect_plans_hygiene(self.repo_root, registered_paths, plan_headers)
        snapshot = WorktreeHygieneSnapshot(
            repo_root=str(self.repo_root),
            collected_at=now.isoformat(timespec="seconds"),
            registered_worktrees=registered,
            residues=residues,
            plans=plans,
        )
        snapshot.tracking_candidates = _build_tracking_candidates(registered, branch_headers)
        snapshot.statistics = _build_statistics(snapshot)
        return snapshot

    @staticmethod
    def collect_registered_worktrees(
        repo_root: Path | str,
        *,
        stale_worktree_days: int = 14,
    ) -> list[RegisteredWorktreeSnapshot]:
        root = Path(repo_root).resolve()
        rc, stdout, _stderr = _run_git(root, "worktree", "list", "--porcelain")
        if rc != 0:
            return []
        merged_rc, merged_stdout, _ = _run_git(root, "branch", "--merged", "main", "--format=%(refname:short)")
        merged_branches = set(merged_stdout.splitlines()) if merged_rc == 0 else set()

        snapshots: list[RegisteredWorktreeSnapshot] = []
        for entry in _parse_worktree_porcelain(stdout):
            path = Path(entry["path"]).resolve()
            branch = entry.get("branch")
            dirty_count, dirty_files = _count_dirty(path)
            ahead, behind = _ahead_behind(root, branch)
            upstream_ahead, upstream_behind = _upstream_ahead_behind(root, branch)
            rel_or_abs = str(path)
            snapshot = RegisteredWorktreeSnapshot(
                path=rel_or_abs,
                branch=branch,
                head=entry.get("head"),
                exists=path.exists(),
                is_root=path == root,
                is_plans=path == (root / ".worktrees" / "plans").resolve(),
                locked=bool(entry.get("locked")),
                locked_reason=entry.get("locked_reason"),
                prunable=bool(entry.get("prunable")),
                dirty_count=dirty_count,
                dirty_files=dirty_files,
                ahead=ahead,
                behind=behind,
                main_includes_branch=branch in merged_branches if branch else None,
                upstream_ahead=upstream_ahead,
                upstream_behind=upstream_behind,
                created_at=_created_at(root, branch),
                modified_at=_path_modified_at(path),
                last_commit_at=_last_commit_at(root, branch),
            )
            snapshots.append(snapshot)
        return snapshots


def collect_registered_worktrees(repo_root: Path) -> list[RegisteredWorktreeSnapshot]:
    return WorktreeHygieneService.collect_registered_worktrees(repo_root)


def render_worktree_hygiene_report(snapshot: WorktreeHygieneSnapshot) -> str:
    lines = [
        "# Worktree Hygiene Report",
        "",
        f"- repo: `{snapshot.repo_root}`",
        f"- collected_at: `{snapshot.collected_at}`",
        f"- registered: {len(snapshot.registered_worktrees)}",
        f"- residue: {len(snapshot.residues)}",
        f"- tracking candidates: {len(snapshot.tracking_candidates)}",
        "",
        "## 관심 낮음 후보",
        "",
        "| branch/path | interest | why safe to consider | why not auto-delete | next action |",
        "|---|---|---|---|---|",
    ]
    low_interest = [
        item
        for item in snapshot.registered_worktrees
        if item.interest_level in {INTEREST_STALE_CLEANUP_CANDIDATE, INTEREST_STALE_LOCKED_REVIEW}
    ]
    if not low_interest:
        lines.append("| - | - | - | - | - |")
    for item in low_interest:
        why_not = "locked" if item.locked else "report-first policy"
        lines.append(
            f"| `{item.branch or item.path}` | {item.interest_level} | {item.cleanable_reason or ''} | {why_not} | {item.cleanup_recommendation} |"
        )

    lines.extend([
        "",
        "## 등록 Worktree",
        "",
        "| branch | dirty | ahead | locked | plan | interest | recommendation | required_plan_update |",
        "|---|---:|---:|---|---|---|---|---|",
    ])
    for item in snapshot.registered_worktrees:
        lines.append(
            f"| `{item.branch or '-'}` | {item.dirty_count} | {item.ahead} | {item.locked} | `{item.plan_file or '-'}` | {item.interest_level} | {item.cleanup_recommendation} | {item.required_plan_update} |"
        )

    lines.extend([
        "",
        "## Residue",
        "",
        "| path | kind | files | sourceFiles | action | delete_status |",
        "|---|---|---:|---:|---|---|",
    ])
    if not snapshot.residues:
        lines.append("| - | - | 0 | 0 | - | - |")
    for item in snapshot.residues:
        lines.append(
            f"| `{item.path}` | {item.kind} | {item.file_count} | {item.source_file_count} | {item.action_hint} | {item.delete_status or '-'} |"
        )

    lines.extend([
        "",
        "## Plans Worktree",
        "",
        f"- exists: {snapshot.plans.exists}",
        f"- push_needed: {snapshot.plans.push_needed} (ahead={snapshot.plans.upstream_ahead}, behind={snapshot.plans.upstream_behind})",
        f"- docs_changes: {len(snapshot.plans.docs_changes)}",
        f"- archive_changes: {len(snapshot.plans.archive_changes)}",
        f"- untracked_runtime: {len(snapshot.plans.untracked_runtime)}",
        f"- logs_gitignore_warning: {snapshot.plans.logs_gitignore_warning}",
        "",
        "## Header Drift",
        "",
        "| plan | branch | worktree | reason |",
        "|---|---|---|---|",
    ])
    if not snapshot.plans.header_drifts:
        lines.append("| - | - | - | - |")
    for drift in snapshot.plans.header_drifts:
        lines.append(
            f"| `{drift['plan_file']}` | `{drift['branch']}` | `{drift['worktree']}` | {drift['reason']} |"
        )

    lines.extend([
        "",
        "## Tracking Candidates",
        "",
        "| risk | plan | branch | dirty | ahead | next action |",
        "|---|---|---|---:|---:|---|",
    ])
    if not snapshot.tracking_candidates:
        lines.append("| - | - | - | 0 | 0 | - |")
    for item in snapshot.tracking_candidates:
        lines.append(
            f"| {item.risk_type} | `{item.plan_path}` | `{item.branch or '-'}` | {item.dirty_count} | {item.ahead} | user_confirmation_required |"
        )
    return "\n".join(lines) + "\n"


def render_tracking_memo(candidate: TrackingCandidate) -> str:
    evidence = candidate.archive_evidence or {}
    return "\n".join(
        [
            "판단 필요: archive 구현완료 plan의 live worktree",
            "",
            f"risk_type: {candidate.risk_type}",
            f"confidence: {candidate.confidence}",
            "",
            "## why_flagged",
            f"- plan_status: {candidate.plan_status}",
            f"- worktree_path: `{candidate.worktree_path}`",
            f"- branch: `{candidate.branch or '-'}`",
            f"- main_includes_branch: {candidate.main_includes_branch}",
            "",
            "## why_not_auto_merge",
            "- archive 상태는 merge 승인 evidence가 아니며 user_confirmation_required=true",
            "- dirty/ahead/main 포함 여부를 사람이 확인해야 함",
            "",
            "## state",
            f"| field | value |\n|---|---|\n| plan | `{candidate.plan_path}` |\n| title | {candidate.plan_title or '-'} |\n| head | `{candidate.head or '-'}` |\n| dirty_count | {candidate.dirty_count} |\n| main_ahead | {candidate.ahead} |\n| main_behind | {candidate.behind} |\n| locked_reason | {candidate.locked_reason or '-'} |",
            "",
            "## archive_evidence",
            f"- merge_commit: {bool(evidence.get('merge_commit'))}",
            f"- cleanup_commit: {bool(evidence.get('cleanup_commit'))}",
            f"- test_evidence: {bool(evidence.get('test_evidence'))}",
            "",
            "## recommended_next_action",
            "- main 포함됨 -> cleanup",
            "- main 미포함 + evidence 있음 -> 사용자 확인 후 merge 후보",
            "- dirty 있음 -> diff 검토",
            "- 폐기/outdated -> merge 금지",
            "",
            "user_confirmation_required=true",
        ]
    )


def snapshot_to_statistics_json(snapshot: WorktreeHygieneSnapshot) -> str:
    return json.dumps(snapshot.statistics, ensure_ascii=False, sort_keys=True)


def snapshot_to_dict(snapshot: WorktreeHygieneSnapshot) -> dict[str, Any]:
    return asdict(snapshot)
