"""plan \uc644\ub8cc \ucc98\ub9ac \uc11c\ube44\uc2a4 \u2014 done \uc6cc\ud06c\ud50c\ub85c\uc6b0, \uc544\uce74\uc774\ube0c, git commit"""

import asyncio
import logging
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import List, Optional

from app.modules.dev_runner.schemas import PlanFileResponse
from app.modules.dev_runner.services.archive_service import archive_plan_bundle
from app.modules.dev_runner.services.git_utils import check_branch_exists, check_worktree_exists
from app.modules.dev_runner.services.log_service import publish_log, log_service
from app.modules.dev_runner.services.plan_path_resolver import PathRuleError

logger = logging.getLogger(__name__)


class PlanDoneService:
    """plan \uc644\ub8cc \ucc98\ub9ac \uc11c\ube44\uc2a4.

    \ucc45\uc784:
    - run_done: \ub2e8\uc77c plan \uc644\ub8cc \ucc98\ub9ac (\ud5e4\ub354 \uac31\uc2e0, \uc544\uce74\uc774\ube0c, TODO\u2192DONE, git commit)
    - batch_done: \uc644\ub8cc \uac00\ub2a5\ud55c plan \uc77c\uad04 \ucc98\ub9ac
    - verify_completion: \uccb4\ud06c\ubc15\uc2a4 \uc644\ub8cc \uc5ec\ubd80 \ud310\uc815
    - \ubcf4\uc870: _archive_plan, _update_todo_done, _archive_done_if_needed, _git_commit

    \uc758\uc874\uc131:
    - PlanScanner: \uc9c4\ud589\ub960/\uc0c1\ud0dc \uc870\ud68c, \ud30c\uc2f1
    - PlanPathRegistry: \uacbd\ub85c \uc870\ud68c
    - log_service.publish_log: Redis \ub85c\uae45
    - plan_record_service: DB \uae30\ub85d (lazy import)
    """

    COMMIT_SH = Path("D:/work/project/tools/common/commit.sh")

    # \uc644\ub8cc \uacc4\uc5f4 \uc0c1\ud0dc (batch_done \ud310\ub2e8\uc6a9, PlanScanner._DONE_STATUSES\uc640 \ub3d9\uc77c)
    _DONE_STATUSES = {"구현완료", "완료", "수정 완료", "배포완료", "수정완료"}

    def __init__(self, scanner, registry):
        """
        Args:
            scanner: PlanScanner \uc778\uc2a4\ud134\uc2a4 \u2014 \uc9c4\ud589\ub960/\uc0c1\ud0dc \uc870\ud68c, \ud30c\uc2f1
            registry: PlanPathRegistry \uc778\uc2a4\ud134\uc2a4 \u2014 \uacbd\ub85c \uc870\ud68c
        """
        self.scanner = scanner
        self.registry = registry

    # ========== done \ub3c4\uc6b0\ubbf8 ==========

    @staticmethod
    def _update_manual_tasks(
        project_dir: Path, items: List[str], plan_filename: str
    ) -> None:
        """\ubbf8\uc644\ub8cc \uccb4\ud06c\ubc15\uc2a4\ub97c MANUAL_TASKS.md\ub85c \uc774\uad00"""
        manual_path = project_dir / "MANUAL_TASKS.md"
        today = date.today().isoformat()

        if manual_path.exists():
            existing = manual_path.read_text(encoding="utf-8")
        else:
            existing = ""

        # \uc911\ubcf5 \uccb4\ud06c: \uc774\ubbf8 \uc774 plan\uc5d0\uc11c \uc774\uad00\ub41c \ud56d\ubaa9\uc774 \uc788\uc73c\uba74 \uc2a4\ud0b5
        if f"from: {plan_filename}" in existing:
            return

        # \uc0c8 \ud56d\ubaa9 \uc0dd\uc131
        new_lines = []
        for item in items:
            new_lines.append(f"- [ ] {item} — from: {plan_filename} ({today})")

        if not existing:
            # \ud30c\uc77c \uc2e0\uaddc \uc0dd\uc131
            content = (
                "# MANUAL_TASKS\n\n"
                "> \uc790\ub3d9\ud654\uac00 \uc5b4\ub835\uac70\ub098 \uc0ac\ub78c\uc758 \ud310\ub2e8\uc774 \ud544\uc694\ud55c \uc218\ub3d9 \uc791\uc5c5 \ubaa9\ub85d\n\n"
                "## \ubbf8\uc644\ub8cc\n\n"
                + "\n".join(new_lines) + "\n\n"
                "## \uc644\ub8cc\n"
            )
            manual_path.write_text(content, encoding="utf-8")
        else:
            # \uae30\uc874 \ud30c\uc77c\uc758 ## \ubbf8\uc644\ub8cc \uc139\uc158 \uc9c1\ud6c4\uc5d0 \uc0bd\uc785
            lines = existing.splitlines()
            insert_idx = None
            for i, line in enumerate(lines):
                if line.strip() == "## \ubbf8\uc644\ub8cc":
                    insert_idx = i + 1
                    # \ube48 \uc904 \uac74\ub108\ub700
                    while insert_idx < len(lines) and lines[insert_idx].strip() == "":
                        insert_idx += 1
                    break
            if insert_idx is not None:
                for j, item_line in enumerate(new_lines):
                    lines.insert(insert_idx + j, item_line)
                manual_path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _extract_plan_title(content: str) -> str:
        """\uccab \ubc88\uc9f8 # \ud5e4\ub354\uc5d0\uc11c \uc81c\ubaa9 \ucd94\ucd9c"""
        match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "Unknown Plan"

    @staticmethod
    def _resolve_project_dir(plan_path: str) -> Optional[Path]:
        """plan \uacbd\ub85c\uc5d0\uc11c \ud504\ub85c\uc81d\ud2b8 \ub514\ub809\ud1a0\ub9ac \ucd94\ub860

        - docs/plan \ud328\ud134 \uac10\uc9c0 \u2192 plan \ub514\ub809\ud1a0\ub9ac\uc758 3\ub2e8\uacc4 \uc704 (file \u2192 plan \u2192 docs \u2192 project_root)
        - \ud328\ud134 \ubd88\uc77c\uce58 \uc2dc \ud30c\uc77c \uae30\uc900 \uc0c1\uc704 3\ub2e8\uacc4 fallback
        """
        p = Path(plan_path).resolve()
        parts = p.parts
        for i, part in enumerate(parts):
            if part == "plan" and i > 0 and parts[i - 1] == "docs":
                # parts[0..i-2] = project root
                project_root = Path(*parts[:i - 1])
                if project_root.exists():
                    return project_root
        # fallback: \ud30c\uc77c \uae30\uc900 \uc0c1\uc704 3\ub2e8\uacc4
        try:
            candidate = p.parent.parent.parent
            if candidate.exists():
                return candidate
        except Exception:
            pass
        return None

    @staticmethod
    def _validate_done_preconditions(file_path: str, content: str) -> list:
        """done 처리 전 사전 검증. 실패 사유 리스트 반환 (빈 리스트 = 통과)"""
        errors = []
        if re.search(r">\s*(branch|worktree(-owner)?):", content[:2000]):
            errors.append("branch/worktree 필드 잔존 — /merge-test 먼저 실행 필요")
        name = Path(file_path).name
        is_fix = "_fix-" in name or "_fix_" in name
        if not is_fix:
            for line in content.split("\n")[:5]:
                if line.startswith("# fix") and len(line) > 5 and line[5] in (":", "-", " "):
                    is_fix = True
                    break
            if not is_fix and re.search(r">\s*유형:\s*fix", content[:1000]):
                is_fix = True
        if is_fix:
            has_pr = "Phase R" in content or "재발 경로 분석" in content
            if not has_pr:
                errors.append("fix plan Phase R 섹션 필수 — /implement에서 Phase R 먼저 실행")
            elif has_pr:
                m = re.search(r"### Phase R.*?(?=\n### |\Z)", content, re.DOTALL)
                if m:
                    section = re.sub(r"```.*?```", "", m.group(0), flags=re.DOTALL)
                    if "미방어" in section:
                        errors.append("Phase R에 미방어 경로 잔존 — 모든 경로 방어 완료 필요")
        return errors

    @staticmethod
    def _update_plan_headers(content: str, total: int) -> str:
        """\uc0c1\ud0dc\u2192구현완료, \uc9c4\ud589\ub960\u2192100%, [\u2192ID]\u2192[x] \uce58\ud658, \ud478\ud130 \uac31\uc2e0"""
        content = re.sub(r'^(>\s*\uc0c1\ud0dc:\s*).*$', r'\1구현완료', content, flags=re.MULTILINE)
        # branch/worktree \ud5e4\ub354 \uc81c\uac70 \u2014 \uc794\uc874 \uc2dc /done \uc2a4\ud0ac 2.5\ub2e8\uacc4\uc5d0\uc11c \ucc28\ub2e8\ub428 (post-merge \uc774\ud6c4\uc774\ub974\ub85c \uc0ad\uc81c \uc548\uc804)
        content = re.sub(r'^>\s*(branch|worktree(-owner)?):.*\n?', '', content, flags=re.MULTILINE)
        content = re.sub(
            r'^(>\s*\uc9c4\ud589\ub960:\s*)[\d/\s()%]+$',
            f'> \uc9c4\ud589\ub960: {total}/{total} (100%)',
            content, flags=re.MULTILINE
        )
        # [\u2192ID] \ud615\ud0dc \u2192 [x]
        content = re.sub(r'\[→[^\]]*\]', '[x]', content)
        # \ud478\ud130 \uac31\uc2e0: *\uc0c1\ud0dc: ... | \uc9c4\ud589\ub960: ...*
        content = re.sub(
            r'\*\uc0c1\ud0dc:[^|*]+\|[^*]*\uc9c4\ud589\ub960:[^*]*\*',
            f'*\uc0c1\ud0dc: 구현완료 | \uc9c4\ud589\ub960: {total}/{total} (100%)*',
            content
        )
        return content

    async def _archive_plan(self, plan_path: str, content: str) -> tuple:
        """공통 archive 로직으로 plan/_todo를 이동한다."""
        try:
            archive_path, todo_archive_path, _ = await archive_plan_bundle(
                plan_path=plan_path,
                content=content,
                find_todo_file=self.scanner._find_todo_file,
            )
            return archive_path, todo_archive_path
        except PathRuleError as path_err:
            raise ValueError(str(path_err)) from path_err

    @staticmethod
    def _update_todo_done(project_dir: Path, plan_title: str) -> None:
        """TODO.md\uc5d0\uc11c plan_title \uad00\ub828 \ud56d\ubaa9 \uc81c\uac70, DONE.md \uc0c1\ub2e8\uc5d0 \ucd94\uac00"""
        today = date.today().isoformat()

        # TODO.md: plan_title\uc744 \ud3ec\ud568\ud558\ub294 \uccb4\ud06c\ubc15\uc2a4 \uc904 \uc81c\uac70
        todo_path = project_dir / "TODO.md"
        if todo_path.exists():
            lines = todo_path.read_text(encoding="utf-8").splitlines(keepends=True)
            filtered = [
                l for l in lines
                if not (plan_title in l and re.search(r'\[[ x→]\]', l))
            ]
            if len(filtered) < len(lines):
                todo_path.write_text("".join(filtered), encoding="utf-8")

        # DONE.md \uc0c1\ub2e8\uc5d0 \ucd94\uac00
        done_path = project_dir / "docs" / "DONE.md"
        done_path.parent.mkdir(parents=True, exist_ok=True)
        new_entry = f"- [x] {today}: {plan_title}\n"

        if done_path.exists():
            existing = done_path.read_text(encoding="utf-8")
            header_match = re.match(r'(#[^\n]+\n\n?)', existing)
            if header_match:
                pos = header_match.end()
                done_path.write_text(existing[:pos] + new_entry + existing[pos:], encoding="utf-8")
            else:
                done_path.write_text(new_entry + existing, encoding="utf-8")
        else:
            done_path.write_text(f"# DONE (\uc5ec\uae30\uc11c 20\uac1c)\n\n{new_entry}", encoding="utf-8")

    @staticmethod
    def _archive_done_if_needed(done_path: Path) -> None:
        """DONE.md \ud56d\ubaa9 5\uac1c \ucd08\uacfc \uc2dc \uc6d4\ubcc4 \uc544\uce74\uc774\ube0c"""
        if not done_path.exists():
            return

        content = done_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        item_lines = [l for l in lines if re.match(r'^-\s*\[', l)]

        if len(item_lines) <= 5:
            return

        keep = item_lines[:5]
        overflow = item_lines[5:]

        today = date.today()
        archive_dir = done_path.parent / "history"
        archive_dir.mkdir(parents=True, exist_ok=True)
        week_str = f"{today.year}-W{today.isocalendar()[1]:02d}"
        archive_path = archive_dir / f"DONE-{week_str}.md"

        if archive_path.exists():
            archive_path.write_text(
                archive_path.read_text(encoding="utf-8") + "".join(overflow),
                encoding="utf-8"
            )
        else:
            archive_path.write_text(
                f"# DONE Archive {week_str}\n\n" + "".join(overflow),
                encoding="utf-8"
            )

        # DONE.md \uac31\uc2e0 (\ucd5c\uadfc 5\uac1c\ub9cc \uc720\uc9c0)
        header_match = re.match(r'(#[^\n]+\n\n?)', content)
        header = header_match.group(1) if header_match else "# DONE (\uc5ec\uae30\uc11c 20\uac1c)\n\n"
        done_path.write_text(header + "".join(keep), encoding="utf-8")

    async def _git_commit(
        self, project_dir: Optional[Path], files_to_add: List[Path], commit_msg: str
    ) -> str:
        """git add + commit.sh \ud638\ucd9c"""
        if not self.COMMIT_SH.exists():
            return f"commit.sh not found: {self.COMMIT_SH}"

        # \uc874\uc7ac\ud558\ub294 \ud30c\uc77c(\uc2e0\uaddc/\uc218\uc815) + \uc0ad\uc81c\ub41c \ud30c\uc77c(git mv\ub85c \uc774\ubbf8 staged\ub41c \uacbd\uc6b0\ub3c4 \ud3ec\ud568)\uc744 \ubaa8\ub450 add
        existing_files = [str(f) for f in files_to_add if f.exists()]
        deleted_files = [str(f) for f in files_to_add if not f.exists()]
        all_files = existing_files + deleted_files
        if not all_files:
            return "\ucf54\ubc0b\ud560 \ud30c\uc77c \uc5c6\uc74c"

        cwd = str(project_dir) if project_dir and project_dir.exists() else None

        # git add
        add_proc = await asyncio.create_subprocess_exec(
            "git", "-c", "safe.directory=*", "add", *all_files,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await add_proc.communicate()

        # commit.sh
        commit_proc = await asyncio.create_subprocess_exec(
            "bash", str(self.COMMIT_SH), commit_msg,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(commit_proc.communicate(), timeout=60)
        return stdout.decode("utf-8", errors="replace") if stdout else ""

    async def run_done(self, plan_path: str) -> dict:
        """Python \ub124\uc774\ud2f0\ube0c plan \uc644\ub8cc \ucc98\ub9ac (\uc544\uce74\uc774\ube0c, TODO\u2192DONE, git commit)"""
        path = Path(plan_path)
        if not path.exists():
            return {"success": False, "message": f"Plan file not found: {plan_path}", "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

        pre_progress = self.scanner.get_plan_progress(path)
        pre_status = self.scanner.get_plan_status(path)

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            title = self._extract_plan_title(content)
            total = pre_progress.total

            # 0. 사전 검증 (구현완료 설정 전 게이트)
            precondition_errors = self._validate_done_preconditions(plan_path, content)
            if precondition_errors:
                raise ValueError(f"done 사전 검증 실패: {'; '.join(precondition_errors)}")

            # 1. \ud5e4\ub354/\ud478\ud130 \uac31\uc2e0
            updated_content = self._update_plan_headers(content, total)

            # 2. \ubbf8\uc644\ub8cc \uccb4\ud06c\ubc15\uc2a4 \u2192 MANUAL_TASKS.md \uc774\uad00
            project_dir = self._resolve_project_dir(plan_path)
            pending_items = self.scanner._extract_pending_checkboxes(updated_content)
            has_manual = False
            if pending_items and project_dir:
                self._update_manual_tasks(project_dir, pending_items, path.name)
                has_manual = True

            # 3. \uc544\uce74\uc774\ube0c \uc774\ub3d9
            archive_path, todo_archive_path = await self._archive_plan(plan_path, updated_content)

            # 4. TODO.md / DONE.md \uc5c5\ub370\uc774\ud2b8
            if project_dir:
                self._update_todo_done(project_dir, title)
                done_path = project_dir / "docs" / "DONE.md"
                self._archive_done_if_needed(done_path)

            # 5. git commit
            files_to_commit: List[Path] = [archive_path]
            if todo_archive_path:
                files_to_commit.append(todo_archive_path)
            if project_dir:
                files_to_commit += [
                    project_dir / "TODO.md",
                    project_dir / "docs" / "DONE.md",
                ]
                if has_manual:
                    files_to_commit.append(project_dir / "MANUAL_TASKS.md")
            commit_output = await self._git_commit(
                project_dir, files_to_commit, f"docs: {title} \uc644\ub8cc \ucc98\ub9ac"
            )

            # 6. \uc2a4\uce90\ub108 \uce90\uc2dc \ubb34\ud6a8\ud654
            self.scanner.invalidate_plans_cache()

            # 7. DB \uae30\ub85d: plan_records\uc5d0 archive \uc644\ub8cc \uae30\ub85d
            try:
                from app.database import SessionLocal
                from app.modules.dev_runner.services.plan_record_service import PlanRecordService
                with SessionLocal() as db:
                    svc = PlanRecordService(db)
                    svc.update_status(plan_path, "completed")
                    svc.mark_archived(plan_path, str(archive_path))
                    db.commit()
            except Exception as db_err:
                logger.warning(f"plan_record DB \uae30\ub85d \uc2e4\ud328 (\ubb34\uc2dc): {db_err}")

            # 8. Redis pub/sub \ud2b8\ub9ac\uac70: plan:archived \ucc44\ub110\uc5d0 \uc544\uce74\uc774\ube0c \uacbd\ub85c \ubc1c\ud589
            try:
                publish_log("plan", f"archived: {archive_path}")
                log_service.redis_client.publish("plan:archived", str(archive_path))
            except Exception as redis_err:
                logger.debug(f"plan:archived publish \uc2e4\ud328 (\ubb34\uc2dc): {redis_err}")

            return {
                "success": True,
                "message": "\uc644\ub8cc \ucc98\ub9ac \uc131\uacf5",
                "output": f"\uc544\uce74\uc774\ube0c: {archive_path}\n{commit_output}",
                "remaining_tasks": pre_progress.total - pre_progress.done,
                "total_tasks": pre_progress.total,
                "plan_status": pre_status,
            }

        except Exception as e:
            logger.error(f"run_done \uc2e4\ud328: {e}")
            return {"success": False, "message": str(e), "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

    # ========== \uc77c\uad04 \uc644\ub8cc ==========

    def verify_completion(self, plan_path: Path) -> "VerifyResult":
        """\ucf54\ub4dc\ubca0\uc774\uc2a4\uc640 \uacc4\ud68d\uc11c\ub97c \ub300\uc870\ud558\uc5ec \uc644\ub8cc \uc5ec\ubd80 \ud310\uc815"""
        from app.modules.dev_runner.schemas import VerifyResult

        # archive \uacbd\ub85c\uc774\uba74 \uc989\uc2dc can_done=False
        if "archive" in str(plan_path):
            return VerifyResult(total=0, verified=0, unverified_items=[], percent=0.0, can_done=False)

        detail = self.scanner.parse_plan_items(plan_path)

        # \uccb4\ud06c\ubc15\uc2a4\uac00 \uc5c6\ub294 \ubb38\uc11c(\ubd84\uc11d\uc11c, \ubcf4\uace0\uc11c \ub4f1): \uc544\uce74\uc774\ube0c \ud5c8\uc6a9
        if not detail.phases or all(len(p.items) == 0 for p in detail.phases):
            progress = self.scanner.get_plan_progress(plan_path)
            if progress.total == 0:
                return VerifyResult(total=0, verified=0, unverified_items=[], percent=100.0, can_done=True)

        total = 0
        verified = 0
        unverified_items: list = []

        def process_item(item) -> None:
            nonlocal total, verified
            total += 1
            if item.file_path:
                if Path(item.file_path).exists():
                    verified += 1
                else:
                    unverified_items.append(item.text)
            else:
                if item.checked:
                    verified += 1
                else:
                    unverified_items.append(item.text)
            for child in item.children:
                process_item(child)

        for phase in detail.phases:
            for item in phase.items:
                process_item(item)

        percent = round(verified / total * 100, 1) if total > 0 else 0.0
        can_done = total > 0 and verified == total

        return VerifyResult(
            total=total,
            verified=verified,
            unverified_items=unverified_items,
            percent=percent,
            can_done=can_done,
        )

    # _check_branch_exists, _check_worktree_exists → git_utils로 이전 (safe.directory 방어 포함)

    def _can_done(self, plan: PlanFileResponse) -> bool:
        """plan\uc774 done \ucc98\ub9ac \uac00\ub2a5\ud55c\uc9c0 \ud310\ub2e8 \u2014 \uccb4\ud06c\ubc15\uc2a4 \uc804\uccb4 \uc644\ub8cc OR \uc0c1\ud0dc \ud5e4\ub354 \uc644\ub8cc \uacc4\uc5f4 OR \uccb4\ud06c\ubc15\uc2a4 \uc5c6\uc74c"""
        if "archive" in plan.path:
            return False

        # worktree/branch \uc874\uc7ac \uc5ec\ubd80 \ud655\uc778 \u2014 \uc0b4\uc544\uc788\uc73c\uba74 done \ubd88\uac00
        try:
            p = Path(plan.path)
            if p.exists():
                top20 = ""
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        if i >= 20:
                            break
                        top20 += line
                branch_match = re.search(r'^>\s*branch:\s*(.+)', top20, re.MULTILINE)
                if branch_match and check_branch_exists(branch_match.group(1).strip()):
                    return False
                worktree_match = re.search(r'^>\s*worktree:\s*(.+)', top20, re.MULTILINE)
                if worktree_match and check_worktree_exists(worktree_match.group(1).strip()):
                    return False
        except Exception:
            pass  # \ud30c\uc77c \uc77d\uae30 \uc2e4\ud328 \uc2dc \uae30\uc874 \ub85c\uc9c1\uc73c\ub85c \uc9c4\ud589

        progress = plan.progress
        if progress is None:
            progress = self.scanner.get_plan_progress(Path(plan.path))
        # \uac00\uc774\ub4dc \ubb38\uc11c\ub294 done \ubd88\uac00
        if plan.status == "\uac00\uc774\ub4dc":
            return False
        # \uccb4\ud06c\ubc15\uc2a4 \uc5c6\ub294 \ubb38\uc11c(\ubd84\uc11d\uc11c, \ubcf4\uace0\uc11c \ub4f1): \uc544\uce74\uc774\ube0c \ud5c8\uc6a9
        if progress.total == 0:
            return True
        if progress.total > 0 and progress.done == progress.total:
            return True
        if plan.status in self._DONE_STATUSES:
            return True
        return False

    async def batch_done(self) -> dict:
        """\uc644\ub8cc \uac00\ub2a5\ud55c plan\uc744 \uc77c\uad04 done \ucc98\ub9ac"""
        all_plans = self.scanner.list_plans(include_ignored=True)
        targets = [p for p in all_plans if self._can_done(p)]

        if not targets:
            return {"total": 0, "success": 0, "failed": 0, "results": []}

        results = []
        success_count = 0
        failed_count = 0

        filenames = ",".join(p.filename for p in targets)
        publish_log("BATCH", f"PLAN_LIST {filenames}")

        for plan in targets:
            publish_log("BATCH", f"PLAN_START {plan.filename}")
            result = await self.run_done(plan.path)
            results.append({
                "path": plan.path,
                "filename": plan.filename,
                "success": result["success"],
                "message": result["message"],
            })
            if result["success"]:
                success_count += 1
                publish_log("BATCH", f"PLAN_DONE {plan.filename}")
            else:
                failed_count += 1
                publish_log("BATCH", f"PLAN_FAILED {plan.filename}")
                publish_log("ERROR", f"{plan.filename}: {result['message']}")

        publish_log("INFO", f"\uc77c\uad04\uc644\ub8cc \uc885\ub8cc: {success_count}\uac1c \uc131\uacf5, {failed_count}\uac1c \uc2e4\ud328")

        return {
            "total": len(targets),
            "success": success_count,
            "failed": failed_count,
            "results": results,
        }


# \uc2f1\uae00\ud134 \uc778\uc2a4\ud134\uc2a4 \u2014 plan_scanner, plan_path_registry \ucd08\uae30\ud654 \ud6c4 \uc0dd\uc131
from app.modules.dev_runner.services.plan_scanner import plan_scanner
from app.modules.dev_runner.services.plan_path_registry import plan_path_registry

plan_done_service = PlanDoneService(plan_scanner, plan_path_registry)

