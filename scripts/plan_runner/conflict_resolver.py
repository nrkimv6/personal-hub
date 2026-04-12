"""
[DEPRECATED] conflict_resolver.py — plan-runner resolve 서브커맨드로 대체됨 (2026-03-05).
ConflictAnalyzer, ResolveResult, _record_resolution은 계속 사용.
try_resolve()의 claude --print 호출은 사용 중단.

이 모듈의 try_resolve()는 claude --print 모드를 사용하는데, --print 모드는
Read/Edit/Bash tool 사용이 불가능하여 conflict markers를 실제로 수정할 수 없다.
plan-runner resolve 서브커맨드(--dangerously-skip-permissions + stream-json)로 대체.
"""

from __future__ import annotations

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import json
import logging
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
import traceback as _tb
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ConflictBlock:
    file_path: str
    ours: str
    theirs: str
    marker_start: int
    marker_end: int


@dataclass
class ResolveResult:
    success: bool
    resolved_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    reason: str = ""


class ConflictAnalyzer:
    @staticmethod
    def get_conflict_files(project_root: Path) -> list[str]:
        """git diff --name-only --diff-filter=U 로 충돌 파일 목록 반환"""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        return [f for f in result.stdout.splitlines() if f.strip()]

    @staticmethod
    def parse_conflict_markers(file_path: Path) -> list[ConflictBlock]:
        """파일에서 conflict markers 파싱 → ConflictBlock 리스트 반환"""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return []

        lines = content.splitlines(keepends=True)
        blocks: list[ConflictBlock] = []
        i = 0
        while i < len(lines):
            if lines[i].startswith("<<<<<<<"):
                marker_start = i
                ours_lines: list[str] = []
                theirs_lines: list[str] = []
                j = i + 1
                # ours 수집
                while j < len(lines) and not lines[j].startswith("======="):
                    ours_lines.append(lines[j])
                    j += 1
                sep = j
                j += 1
                # theirs 수집
                while j < len(lines) and not lines[j].startswith(">>>>>>>"):
                    theirs_lines.append(lines[j])
                    j += 1
                marker_end = j
                blocks.append(ConflictBlock(
                    file_path=str(file_path),
                    ours="".join(ours_lines),
                    theirs="".join(theirs_lines),
                    marker_start=marker_start,
                    marker_end=marker_end,
                ))
                i = marker_end + 1
            else:
                i += 1
        return blocks

    @staticmethod
    def is_resolvable(
        conflict_files: list[str], max_files: int = 5
    ) -> tuple[bool, str]:
        """해결 가능 여부 판단"""
        if len(conflict_files) > max_files:
            return False, f"충돌 파일 {len(conflict_files)}개 > 최대 {max_files}개"

        binary_exts = {
            ".lock", ".min.js", ".min.css",
            ".png", ".jpg", ".gif",
            ".woff", ".woff2", ".ttf",
            ".ico", ".db",
        }
        bad = [f for f in conflict_files if Path(f).suffix in binary_exts]
        if bad:
            return False, f"바이너리/생성 파일 포함: {bad}"

        return True, ""

    @staticmethod
    def get_base_content(project_root: Path, file_path: str) -> str:
        """git merge base 스테이지(:1:)에서 파일 내용 반환.

        신규 파일이거나 merge 중이 아닌 경우 빈 문자열 반환 (예외 없음).
        """
        try:
            result = subprocess.run(
                ["git", "show", f":1:{file_path}"],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout
            return ""
        except Exception:
            return ""


class ConflictResolver:
    def __init__(
        self,
        project_root: Path,
        redis_client=None,
        python_path: Optional[str] = None,
    ):
        self.project_root = project_root
        self.redis_client = redis_client
        self.python_path = python_path or "python"
        self.logger = logging.getLogger(__name__)

    def _build_prompt(
        self,
        conflict_files: list[str],
        conflict_blocks: dict[str, list[ConflictBlock]],
        branch: str,
    ) -> str:
        lines = [
            f"PROJECT_ROOT: {self.project_root}",
            f"BRANCH: {branch}",
            f"CONFLICT_FILES: {json.dumps(conflict_files, ensure_ascii=False)}",
            "",
        ]
        for file_path in conflict_files:
            lines.append(f"## {file_path}")
            blocks = conflict_blocks.get(file_path, [])
            for i, block in enumerate(blocks, 1):
                lines.append(f"### 충돌 블록 {i}")
                lines.append("#### OURS (HEAD/main)")
                lines.append(block.ours or "(비어있음)")
                lines.append("#### THEIRS (branch)")
                lines.append(block.theirs or "(비어있음)")

            # 최근 커밋 메시지
            try:
                log_result = subprocess.run(
                    ["git", "log", "--oneline", "-3", branch, "--", file_path],
                    capture_output=True,
                    text=True,
                    cwd=str(self.project_root),
                    timeout=10,
                )
                if (log_result.stdout or "").strip():
                    lines.append(f"### 최근 커밋 ({branch})")
                    lines.append((log_result.stdout or "").strip())
            except Exception:
                pass
            lines.append("")
        return "\n".join(lines)

    def _verify_resolution(self) -> bool:
        """conflict markers 잔존 여부 검사"""
        # git diff --check
        check = subprocess.run(
            ["git", "diff", "--check"],
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
        )
        if check.returncode != 0:
            return False
        # git grep
        grep = subprocess.run(
            ["git", "grep", "<<<<<<<"],
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
        )
        if grep.returncode == 0 and (grep.stdout or "").strip():
            return False
        return True

    def _record_resolution(
        self,
        runner_id: str,
        branch: str,
        conflict_files: list[str],
        result: ResolveResult,
        duration_ms: int,
    ) -> None:
        try:
            db_path = self.project_root / "data" / "monitor.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                """INSERT INTO conflict_resolutions
                   (runner_id, branch, conflict_files, resolved_files, failed_files,
                    strategy, success, duration_ms, error_message)
                   VALUES (?, ?, ?, ?, ?, 'auto', ?, ?, ?)""",
                (
                    runner_id,
                    branch,
                    json.dumps(conflict_files, ensure_ascii=False),
                    json.dumps(result.resolved_files, ensure_ascii=False),
                    json.dumps(result.failed_files, ensure_ascii=False),
                    int(result.success),
                    duration_ms,
                    result.reason or None,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"[ConflictResolver] 이력 기록 실패 (무시): {e}")

    def try_resolve(self, runner_id: str, branch: str) -> ResolveResult:
        """[DEPRECATED] claude --print 모드는 tool(Read/Edit/Bash) 사용 불가.
        plan-runner resolve 서브커맨드 사용할 것. 이 메서드는 호환성 유지만."""
        start_time = time.time()
        try:
            # 1. 충돌 파일 목록
            files = ConflictAnalyzer.get_conflict_files(self.project_root)
            if not files:
                result = ResolveResult(success=False, reason="충돌 파일 없음")
                return result

            # 2. 해결 가능성 검사
            ok, reason = ConflictAnalyzer.is_resolvable(files)
            if not ok:
                result = ResolveResult(success=False, failed_files=files, reason=reason)
                duration_ms = int((time.time() - start_time) * 1000)
                self._record_resolution(runner_id, branch, files, result, duration_ms)
                return result

            # 3. 파일별 파싱
            conflict_blocks: dict[str, list[ConflictBlock]] = {}
            for file_path in files:
                abs_path = self.project_root / file_path
                conflict_blocks[file_path] = ConflictAnalyzer.parse_conflict_markers(abs_path)

            # 4. 프롬프트 생성
            prompt = self._build_prompt(files, conflict_blocks, branch)

            # 5. Claude 에이전트 호출
            proc = subprocess.run(
                [
                    "claude",
                    "--agent", "auto-conflict-resolver",
                    "--print",
                    "--output-format", "text",
                    "-p", prompt,
                ],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=300,
            )

            # 6. 결과 블록 파싱
            stdout = proc.stdout or ""
            match = re.search(
                r"===AUTO-CONFLICT-RESULT===\s*(.*?)\s*===END===",
                stdout,
                re.DOTALL,
            )
            if not match:
                self.logger.warning("[ConflictResolver] 결과 블록 없음")
                early_result = ResolveResult(success=False, failed_files=files, reason="Claude 에이전트 결과 블록 없음")
                duration_ms = int((time.time() - start_time) * 1000)
                self._record_resolution(runner_id, branch, files, early_result, duration_ms)
                return early_result

            # 7. 해결 검증
            if self._verify_resolution():
                result = ResolveResult(success=True, resolved_files=files)
            else:
                result = ResolveResult(
                    success=False,
                    failed_files=files,
                    reason="conflict markers 잔존",
                )

            duration_ms = int((time.time() - start_time) * 1000)
            self._record_resolution(runner_id, branch, files, result, duration_ms)
            return result

        except Exception as e:
            self.logger.error(f"[ConflictResolver] 예외: {e}\n{_tb.format_exc()}")
            result = ResolveResult(success=False, reason=str(e))
            duration_ms = int((time.time() - start_time) * 1000)
            try:
                files_for_record = locals().get("files", [])
                self._record_resolution(runner_id, branch, files_for_record, result, duration_ms)
            except Exception:
                pass
            return result
