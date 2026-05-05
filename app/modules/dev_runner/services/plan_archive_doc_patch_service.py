"""Preview/apply workflow for Plan Archive document patch proposals."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.models.plan_archive_doc_patch import PlanArchiveDocPatchProposal
from app.models.plan_record import PlanRecord

CommitRunner = Callable[[Path, str], str]
VALID_STATUSES = {"draft", "previewed", "applied", "rejected", "failed"}


class PlanArchiveDocPatchService:
    def __init__(
        self,
        db: Session,
        *,
        archive_dir: Path | None = None,
        plans_worktree_dir: Path | None = None,
        commit_runner: CommitRunner | None = None,
    ):
        self.db = db
        self.archive_dir = archive_dir or PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "archive"
        self.plans_worktree_dir = plans_worktree_dir or PROJECT_ROOT / ".worktrees" / "plans"
        self.commit_runner = commit_runner

    def preview(
        self,
        *,
        record_id: int,
        patch_text: str,
        insight_report_id: int | None = None,
        target_path: str | None = None,
    ) -> dict[str, Any]:
        record = self._get_record(record_id)
        target = self._resolve_target_path(target_path or record.file_path)
        content = self._read_content(record, target)
        preview_text, summary = self._apply_structured_patch(content, patch_text, strict=False)
        proposal = PlanArchiveDocPatchProposal(
            plan_record_id=record.id,
            insight_report_id=insight_report_id,
            status="previewed",
            target_path=str(target),
            patch_text=patch_text or "",
            preview_text=preview_text,
            changed_lines_summary=summary,
        )
        self.db.add(proposal)
        self.db.commit()
        self.db.refresh(proposal)
        return self.serialize(proposal)

    def apply(self, proposal_id: int, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ValueError("CONFIRM_REQUIRED")
        proposal = self._get_proposal(proposal_id)
        if proposal.status not in {"previewed", "failed"}:
            raise ValueError("PATCH_NOT_PREVIEWED")
        target = self._resolve_target_path(proposal.target_path)
        original = target.read_text(encoding="utf-8")
        try:
            new_content, summary = self._apply_structured_patch(original, proposal.patch_text, strict=True)
            target.write_text(new_content, encoding="utf-8")
            commit_hash = self._commit_target(target, f"docs: apply plan archive doc patch {proposal.id}")
        except Exception as exc:
            target.write_text(original, encoding="utf-8")
            proposal.status = "failed"
            proposal.error_message = str(exc)
            proposal.updated_at = datetime.now()
            self.db.commit()
            raise
        proposal.status = "applied"
        proposal.preview_text = new_content
        proposal.changed_lines_summary = summary
        proposal.applied_commit = commit_hash
        proposal.error_message = None
        proposal.applied_at = datetime.now()
        proposal.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(proposal)
        return self.serialize(proposal)

    def reject(self, proposal_id: int) -> dict[str, Any]:
        proposal = self._get_proposal(proposal_id)
        if proposal.status == "applied":
            raise ValueError("ALREADY_APPLIED")
        proposal.status = "rejected"
        proposal.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(proposal)
        return self.serialize(proposal)

    def serialize(self, proposal: PlanArchiveDocPatchProposal) -> dict[str, Any]:
        return {
            "id": proposal.id,
            "plan_record_id": proposal.plan_record_id,
            "insight_report_id": proposal.insight_report_id,
            "status": proposal.status,
            "target_path": proposal.target_path,
            "patch_text": proposal.patch_text,
            "preview_text": proposal.preview_text,
            "changed_lines_summary": proposal.changed_lines_summary or [],
            "applied_commit": proposal.applied_commit,
            "error_message": proposal.error_message,
            "created_at": proposal.created_at,
            "updated_at": proposal.updated_at,
            "applied_at": proposal.applied_at,
        }

    def _get_record(self, record_id: int) -> PlanRecord:
        record = self.db.query(PlanRecord).filter_by(id=record_id).first()
        if not record:
            raise LookupError("RECORD_NOT_FOUND")
        return record

    def _get_proposal(self, proposal_id: int) -> PlanArchiveDocPatchProposal:
        proposal = self.db.query(PlanArchiveDocPatchProposal).filter_by(id=proposal_id).first()
        if not proposal:
            raise LookupError("PROPOSAL_NOT_FOUND")
        return proposal

    def _resolve_target_path(self, path: str) -> Path:
        target = Path(path)
        if not target.is_absolute():
            target = self.plans_worktree_dir / path
        target = target.resolve()
        archive_root = self.archive_dir.resolve()
        try:
            target.relative_to(archive_root)
        except ValueError as exc:
            raise ValueError("TARGET_OUTSIDE_ARCHIVE") from exc
        return target

    @staticmethod
    def _read_content(record: PlanRecord, target: Path) -> str:
        if record.raw_content:
            return record.raw_content
        if not target.exists():
            raise FileNotFoundError("TARGET_NOT_FOUND")
        return target.read_text(encoding="utf-8")

    @staticmethod
    def _apply_structured_patch(content: str, patch_text: str, *, strict: bool) -> tuple[str, list[dict[str, Any]]]:
        if not patch_text or not patch_text.strip():
            return content, [{"type": "noop", "count": 0}]
        try:
            payload = json.loads(patch_text)
        except json.JSONDecodeError as exc:
            raise ValueError("MALFORMED_PATCH") from exc
        replacements = payload.get("replacements") if isinstance(payload, dict) else None
        if not replacements:
            return content, [{"type": "noop", "count": 0}]
        result = content
        summary: list[dict[str, Any]] = []
        for item in replacements:
            old = str(item.get("old", ""))
            new = str(item.get("new", ""))
            if not old:
                raise ValueError("MALFORMED_PATCH")
            count = result.count(old)
            if strict and count == 0:
                raise ValueError("PATCH_TARGET_NOT_FOUND")
            result = result.replace(old, new)
            summary.append({"type": "replace", "old": old, "new": new, "count": count})
        return result, summary

    def _commit_target(self, target: Path, message: str) -> str:
        if self.commit_runner:
            return self.commit_runner(target, message)
        commit_script = PROJECT_ROOT.parent / "common" / "commit.ps1"
        if not commit_script.exists():
            raise FileNotFoundError("COMMIT_SCRIPT_NOT_FOUND")
        relative = target.relative_to(self.plans_worktree_dir.resolve())
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.plans_worktree_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if staged:
            raise RuntimeError("PLAN_WORKTREE_STAGED_DIRTY")
        subprocess.run(["git", "add", "--", str(relative)], cwd=self.plans_worktree_dir, check=True)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(commit_script), message],
            cwd=self.plans_worktree_dir,
            check=True,
        )
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=self.plans_worktree_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()
