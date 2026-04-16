"""
WorkflowManager - dev-runner workflow persistence.

The listener runs as an independent process, so this module uses SQLAlchemy Core
directly instead of the app's ORM session helpers.
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject

_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
_repo_root = _Path_inject(__file__).resolve().parents[2]
if str(_repo_root) not in _sys_inject.path:
    _sys_inject.path.insert(0, str(_repo_root))
del _sys_inject, _Path_inject

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.models.workflow import Workflow as WorkflowModel

logger = logging.getLogger(__name__)

_WORKFLOW_TABLE = WorkflowModel.__table__
_TERMINAL_STATUSES = {"merged", "failed", "cancelled", "completed"}


class WorkflowManager:
    def __init__(self, db_source=None):
        source = settings.DATABASE_URL if db_source is None else db_source
        self.db_source = str(source)
        self.db_url = self._normalize_db_url(self.db_source)
        engine_kwargs = self._engine_kwargs(self.db_url)
        self._engine = create_engine(self.db_url, **engine_kwargs)

    @staticmethod
    def _normalize_db_url(db_source: str) -> str:
        raw = str(db_source).strip()
        if "://" in raw:
            return raw
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        return f"sqlite:///{path.resolve().as_posix()}"

    @staticmethod
    def _engine_kwargs(db_url: str) -> dict:
        if db_url.startswith("sqlite"):
            kwargs = {
                "pool_pre_ping": True,
                "connect_args": {"check_same_thread": False},
            }
            if db_url.endswith(":memory:"):
                kwargs["poolclass"] = StaticPool
            return kwargs
        return {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_timeout": 10,
            "pool_size": 5,
            "max_overflow": 10,
            "connect_args": {"connect_timeout": 5},
        }

    def _get_conn(self) -> Connection:
        return self._engine.connect()

    @staticmethod
    def _row_to_dict(row) -> Optional[dict]:
        if row is None:
            return None
        return dict(row._mapping)

    # ──────────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────────

    def create(self, slug: str, plan_file: str = None) -> int:
        """새 workflow 레코드 생성 (status=planned) → workflow_id 반환."""
        created_at = datetime.now()
        stmt = text(
            """
            INSERT INTO workflows (slug, plan_file, status, created_at)
            VALUES (:slug, :plan_file, 'planned', :created_at)
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            wf_id = conn.execute(
                stmt,
                {"slug": slug, "plan_file": plan_file, "created_at": created_at},
            ).scalar_one()
        logger.info("[WorkflowManager] created workflow id=%s slug=%s", wf_id, slug)
        return int(wf_id)

    def get_by_slug(self, slug: str) -> Optional[dict]:
        """slug로 workflow 조회 → dict 또는 None."""
        stmt = text("SELECT * FROM workflows WHERE slug = :slug")
        with self._get_conn() as conn:
            row = conn.execute(stmt, {"slug": slug}).mappings().first()
            return dict(row) if row else None

    def get_by_runner_id(self, runner_id: str) -> Optional[dict]:
        """runner_id로 workflow 조회 (최신순) → dict 또는 None."""
        stmt = text(
            """
            SELECT * FROM workflows
            WHERE runner_id = :runner_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        with self._get_conn() as conn:
            row = conn.execute(stmt, {"runner_id": runner_id}).mappings().first()
            return dict(row) if row else None

    def update_status(self, workflow_id: int, status: str, **kwargs) -> None:
        """상태 전이 + 타임스탬프 자동 업데이트.

        kwargs 지원: runner_id, branch, worktree_path, engine,
                     commit_hash, error_message
        """
        now = datetime.now()
        fields = {"status": status}

        if status == "running":
            fields["started_at"] = now
        elif status in _TERMINAL_STATUSES:
            fields["finished_at"] = now
            if status == "merged":
                fields["merged_at"] = now

        allowed = {
            "runner_id",
            "branch",
            "worktree_path",
            "engine",
            "commit_hash",
            "error_message",
        }
        for key, val in kwargs.items():
            if key in allowed:
                fields[key] = val

        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        params = dict(fields)
        params["workflow_id"] = workflow_id

        stmt = text(f"UPDATE workflows SET {set_clause} WHERE id = :workflow_id")
        with self._engine.begin() as conn:
            conn.execute(stmt, params)
        logger.info("[WorkflowManager] updated workflow id=%s status=%s", workflow_id, status)

    def list_workflows(self, status: str = None, limit: int = 50, offset: int = 0) -> list:
        """workflow 목록 조회 (status 필터 옵션)."""
        if status:
            stmt = text(
                """
                SELECT * FROM workflows
                WHERE status = :status
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            )
            params = {"status": status, "limit": limit, "offset": offset}
        else:
            stmt = text(
                """
                SELECT * FROM workflows
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            )
            params = {"limit": limit, "offset": offset}

        with self._get_conn() as conn:
            rows = conn.execute(stmt, params).mappings().all()
            return [dict(row) for row in rows]

    # ──────────────────────────────────────────────
    # slug utilities
    # ──────────────────────────────────────────────

    @staticmethod
    def _normalize_plan_key(plan_file: Optional[str]) -> str:
        """실행 순번 집계를 위한 plan key 정규화."""
        if plan_file is None:
            return "__ALL_PLANS__"
        raw = str(plan_file).strip()
        if not raw or raw in {"ALL", "__ALL_PLANS__"}:
            return "__ALL_PLANS__"
        return raw.replace("\\", "/")

    @staticmethod
    def _slug_from_plan_file(plan_file: str) -> str:
        """plan 파일명에서 slug 추출."""
        basename = Path(plan_file).stem
        if basename.endswith("_todo"):
            basename = basename[:-5]
        return basename

    @staticmethod
    def _slug_from_runner_id(runner_id: str) -> str:
        """runner_id에서 slug 생성 (plan_file 없을 때 fallback)."""
        return f"runner-{runner_id[:8]}"

    def count_started_runs_until(
        self,
        plan_key: str,
        until_started_at_iso: str,
        conn: Optional[Connection] = None,
    ) -> int:
        """동일 plan_key 그룹의 started_at 누적 실행 횟수를 반환."""
        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
        try:
            if plan_key == "__ALL_PLANS__":
                stmt = text(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM workflows
                    WHERE started_at IS NOT NULL
                      AND started_at <= :until_started_at
                      AND (
                          plan_file IS NULL
                          OR TRIM(plan_file) = ''
                          OR plan_file = '__ALL_PLANS__'
                          OR plan_file = 'ALL'
                      )
                    """
                )
                params = {"until_started_at": until_started_at_iso}
            else:
                stmt = text(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM workflows
                    WHERE started_at IS NOT NULL
                      AND started_at <= :until_started_at
                      AND REPLACE(COALESCE(plan_file, ''), '\\', '/') = :plan_key
                    """
                )
                params = {
                    "until_started_at": until_started_at_iso,
                    "plan_key": plan_key,
                }
            row = conn.execute(stmt, params).mappings().first()
            return int(row["cnt"]) if row and row["cnt"] is not None else 0
        finally:
            if own_conn and conn is not None:
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
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT id, plan_file FROM workflows WHERE id = :workflow_id"),
                {"workflow_id": workflow_id},
            ).mappings().first()
            if row is None:
                raise ValueError(f"workflow not found: id={workflow_id}")

            started_at_iso = datetime.now().isoformat()
            plan_key = self._normalize_plan_key(row["plan_file"])

            conn.execute(
                text(
                    """
                    UPDATE workflows
                    SET status = 'running',
                        started_at = :started_at,
                        runner_id = :runner_id,
                        branch = :branch,
                        worktree_path = :worktree_path,
                        engine = :engine
                    WHERE id = :workflow_id
                    """
                ),
                {
                    "started_at": started_at_iso,
                    "runner_id": runner_id,
                    "branch": branch,
                    "worktree_path": worktree_path,
                    "engine": engine,
                    "workflow_id": workflow_id,
                },
            )
            execution_count = self.count_started_runs_until(plan_key, started_at_iso, conn=conn)

        logger.info(
            "[WorkflowManager] mark_running_with_execution_count id=%s plan_key=%s count=%s",
            workflow_id,
            plan_key,
            execution_count,
        )
        return started_at_iso, execution_count

    # ──────────────────────────────────────────────
    # data migration helpers
    # ──────────────────────────────────────────────

    def sync_from_worktrees(self, worktree_base_dir) -> int:
        """기존 활성 worktree에서 workflow 레코드 자동 생성."""
        try:
            import sys

            scripts_dir = str(Path(__file__).parent)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from worktree_manager import WorktreeManager
        except ImportError:
            logger.warning("[WorkflowManager.sync_from_worktrees] WorktreeManager import 실패")
            return 0

        try:
            worktrees = WorktreeManager.list_worktrees()
        except Exception as e:
            logger.warning("[WorkflowManager.sync_from_worktrees] list_worktrees 실패: %s", e)
            return 0

        created = 0
        for wt in worktrees:
            runner_id = wt.get("runner_id") or wt.get("name", "")
            plan_file = wt.get("plan_file")
            branch = wt.get("branch", "")
            worktree_path = wt.get("path", "")

            if not runner_id:
                continue

            existing = self.get_by_runner_id(runner_id)
            if existing:
                continue

            slug = self._slug_from_plan_file(plan_file) if plan_file else self._slug_from_runner_id(runner_id)
            if self.get_by_slug(slug):
                slug = f"{slug}-{runner_id[:4]}"

            try:
                wf_id = self.create(slug, plan_file)
                self.update_status(
                    wf_id,
                    "running",
                    runner_id=runner_id,
                    branch=branch,
                    worktree_path=str(worktree_path),
                )
                created += 1
            except Exception as e:
                logger.warning("[WorkflowManager.sync_from_worktrees] 생성 실패 slug=%s: %s", slug, e)

        logger.info("[WorkflowManager.sync_from_worktrees] %s개 생성", created)
        return created

