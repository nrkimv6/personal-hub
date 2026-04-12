"""
WorkflowManager — dev-runner 워크플로우 영속화 관리
SQLite 직접 연결 (scripts/ 디렉토리는 독립 프로세스, SQLAlchemy 미사용)
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import sqlite3
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class WorkflowManager:
    def __init__(self, db_path):
        self.db_path = str(db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ──────────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────────

    def create(self, slug: str, plan_file: str = None) -> int:
        """새 워크플로우 레코드 생성 (status=planned) → workflow_id 반환"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "INSERT INTO workflows (slug, plan_file, status, created_at) VALUES (?, ?, 'planned', ?)",
                (slug, plan_file, datetime.now().isoformat()),
            )
            conn.commit()
            wf_id = cursor.lastrowid
            logger.info(f"[WorkflowManager] created workflow id={wf_id} slug={slug}")
            return wf_id
        finally:
            conn.close()

    def get_by_slug(self, slug: str) -> Optional[dict]:
        """slug로 워크플로우 조회 → dict 또는 None"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM workflows WHERE slug = ?", (slug,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_by_runner_id(self, runner_id: str) -> Optional[dict]:
        """runner_id로 워크플로우 조회 (최신순) → dict 또는 None"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM workflows WHERE runner_id = ? ORDER BY created_at DESC LIMIT 1",
                (runner_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_status(self, workflow_id: int, status: str, **kwargs) -> None:
        """상태 전이 + 타임스탬프 자동 업데이트

        kwargs 지원: runner_id, branch, worktree_path, engine,
                     commit_hash, error_message
        """
        now = datetime.now().isoformat()
        fields = {"status": status}

        # 상태별 타임스탬프 자동설정
        if status == "running":
            fields["started_at"] = now
        elif status in ("merged", "failed", "cancelled"):
            fields["finished_at"] = now
            if status == "merged":
                fields["merged_at"] = now

        # 추가 필드 병합
        allowed = {"runner_id", "branch", "worktree_path", "engine", "commit_hash", "error_message"}
        for key, val in kwargs.items():
            if key in allowed:
                fields[key] = val

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [workflow_id]

        conn = self._get_conn()
        try:
            conn.execute(
                f"UPDATE workflows SET {set_clause} WHERE id = ?",
                values,
            )
            conn.commit()
            logger.info(f"[WorkflowManager] updated workflow id={workflow_id} status={status}")
        finally:
            conn.close()

    def list_workflows(self, status: str = None, limit: int = 50, offset: int = 0) -> list:
        """워크플로우 목록 조회 (status 필터 옵션)"""
        conn = self._get_conn()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM workflows WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflows ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ──────────────────────────────────────────────
    # slug 유틸리티
    # ──────────────────────────────────────────────

    @staticmethod
    def _normalize_plan_key(plan_file: Optional[str]) -> str:
        """실행 순번 집계를 위한 plan key 정규화.

        - None/빈값/"ALL"/"__ALL_PLANS__" 는 동일 sentinel 그룹으로 취급
        - 파일 경로는 slash 표준화만 수행
        """
        if plan_file is None:
            return "__ALL_PLANS__"
        raw = str(plan_file).strip()
        if not raw or raw in {"ALL", "__ALL_PLANS__"}:
            return "__ALL_PLANS__"
        return raw.replace("\\", "/")

    @staticmethod
    def _slug_from_plan_file(plan_file: str) -> str:
        """plan 파일명에서 slug 추출 (e.g., 'docs/plan/2026-03-03_workflow-manager_todo.md' → '2026-03-03_workflow-manager')"""
        basename = os.path.splitext(os.path.basename(plan_file))[0]
        # _todo 접미사 제거
        if basename.endswith("_todo"):
            basename = basename[:-5]
        return basename

    @staticmethod
    def _slug_from_runner_id(runner_id: str) -> str:
        """runner_id에서 slug 생성 (plan_file 없을 때 fallback)"""
        return f"runner-{runner_id[:8]}"

    def count_started_runs_until(
        self,
        plan_key: str,
        until_started_at_iso: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """동일 plan_key 그룹의 started_at 누적 실행 횟수를 반환."""
        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
        try:
            if plan_key == "__ALL_PLANS__":
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM workflows
                    WHERE started_at IS NOT NULL
                      AND started_at <= ?
                      AND (
                          plan_file IS NULL
                          OR TRIM(plan_file) = ''
                          OR plan_file = '__ALL_PLANS__'
                          OR plan_file = 'ALL'
                      )
                    """,
                    (until_started_at_iso,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM workflows
                    WHERE started_at IS NOT NULL
                      AND started_at <= ?
                      AND REPLACE(COALESCE(plan_file, ''), '\\', '/') = ?
                    """,
                    (until_started_at_iso, plan_key),
                ).fetchone()
            return int(row["cnt"]) if row and row["cnt"] is not None else 0
        finally:
            if own_conn:
                conn.close()

    def mark_running_with_execution_count(
        self,
        workflow_id: int,
        runner_id: str,
        branch: str,
        worktree_path: str,
        engine: str,
    ) -> tuple[str, int]:
        """running 전이 + started_at + execution_count를 원자적으로 계산/반영."""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, plan_file FROM workflows WHERE id = ?",
                (workflow_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"workflow not found: id={workflow_id}")

            started_at_iso = datetime.now().isoformat()
            plan_key = self._normalize_plan_key(row["plan_file"])

            conn.execute(
                """
                UPDATE workflows
                SET status = 'running',
                    started_at = ?,
                    runner_id = ?,
                    branch = ?,
                    worktree_path = ?,
                    engine = ?
                WHERE id = ?
                """,
                (started_at_iso, runner_id, branch, worktree_path, engine, workflow_id),
            )

            execution_count = self.count_started_runs_until(plan_key, started_at_iso, conn=conn)
            conn.commit()
            logger.info(
                "[WorkflowManager] mark_running_with_execution_count id=%s plan_key=%s count=%s",
                workflow_id,
                plan_key,
                execution_count,
            )
            return started_at_iso, execution_count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ──────────────────────────────────────────────
    # 데이터 마이그레이션 유틸리티
    # ──────────────────────────────────────────────

    def sync_from_worktrees(self, worktree_base_dir) -> int:
        """기존 활성 worktree에서 workflow 레코드 자동 생성
        WorktreeManager.list_worktrees() 결과에서 workflow 없는 항목 생성 → 생성된 수 반환
        """
        try:
            import sys
            scripts_dir = str(Path(__file__).parent)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from worktree_manager import WorktreeManager
        except ImportError:
            logger.warning("[WorkflowManager.sync_from_worktrees] WorktreeManager import 실패")
            return 0

        created = 0
        try:
            worktrees = WorktreeManager.list_worktrees(Path(worktree_base_dir))
        except Exception as e:
            logger.warning(f"[WorkflowManager.sync_from_worktrees] list_worktrees 실패: {e}")
            return 0

        for wt in worktrees:
            runner_id = wt.get("runner_id") or wt.get("name", "")
            plan_file = wt.get("plan_file")
            branch = wt.get("branch", "")
            worktree_path = wt.get("path", "")

            if not runner_id:
                continue

            # 이미 workflow가 있으면 스킵
            existing = self.get_by_runner_id(runner_id)
            if existing:
                continue

            slug = (
                self._slug_from_plan_file(plan_file)
                if plan_file
                else self._slug_from_runner_id(runner_id)
            )
            # slug 중복 방지
            if self.get_by_slug(slug):
                slug = f"{slug}-{runner_id[:4]}"

            try:
                wf_id = self.create(slug, plan_file)
                self.update_status(
                    wf_id, "running",
                    runner_id=runner_id,
                    branch=branch,
                    worktree_path=str(worktree_path),
                )
                created += 1
            except Exception as e:
                logger.warning(f"[WorkflowManager.sync_from_worktrees] 생성 실패 slug={slug}: {e}")

        logger.info(f"[WorkflowManager.sync_from_worktrees] {created}개 생성")
        return created
