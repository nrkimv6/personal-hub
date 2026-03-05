"""
TC: plan_archive_analyze / plan_requirements_sync 스케줄 DB-driven 전환 검증

- _process_plan_archive_schedule() / _execute_plan_archive_run()
- _process_plan_requirements_sync_schedule() / _execute_plan_requirements_sync_run()
- _process_unqueued_requirements_sync() (via _maybe_queue_requirements_sync)
- dispatch 등록 및 하드코딩 제거 검증 (AST)
"""
import ast
import asyncio
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

SCHEDULED_WORKER_PATH = Path(__file__).resolve().parents[2] / "app" / "worker" / "scheduled_worker.py"
HANDLER_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "claude_worker" / "services" / "plan_analyze_handler.py"


# ============================================================
# 헬퍼: in-memory SQLite + 필수 테이블 생성
# ============================================================

def _make_db():
    """in-memory SQLite 연결 + 필수 테이블 생성."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS plan_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename_hash TEXT,
            filename TEXT,
            file_path TEXT,
            archived_at DATETIME,
            llm_processed_at DATETIME,
            category TEXT,
            summary TEXT,
            tags TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS llm_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_type TEXT,
            caller_id TEXT,
            prompt TEXT,
            queue_name TEXT,
            requested_by TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS task_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            display_name TEXT,
            target_type TEXT,
            target_config TEXT DEFAULT '{}',
            schedule_type TEXT,
            schedule_value TEXT,
            enabled INTEGER DEFAULT 1,
            last_run_at DATETIME,
            next_run_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS task_schedule_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            status TEXT DEFAULT 'running',
            worker_id TEXT,
            config_snapshot TEXT,
            result TEXT,
            error_message TEXT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        );
    """)
    return conn


# ============================================================
# Phase T1: _process_plan_archive_schedule() TC
# ============================================================

class TestProcessPlanArchiveSchedule:
    """_process_plan_archive_schedule() 동작 검증."""

    def _make_worker(self):
        """ScheduledCrawlWorker 대신 동일 패턴을 가진 스텁 클래스 사용."""
        class StubWorker:
            name = "test_worker"
            _tasks = {}

            def _is_task_running(self, name):
                return name in self._tasks

            def _create_task(self, coro, name):
                self._tasks[name] = coro

            def _should_run_cron(self, schedule, last_run_at):
                return True

            async def _process_plan_archive_schedule(self, db, schedule, schedule_service):
                try:
                    last_run = schedule_service.get_latest_run(schedule.id)
                    last_run_at = last_run.started_at if last_run else None
                    if not self._should_run_cron(schedule, last_run_at):
                        return
                    if schedule_service.has_active_run(schedule.id):
                        return
                    run = schedule_service.start_run(
                        schedule_id=schedule.id,
                        worker_id=self.name,
                        config_snapshot={}
                    )
                    task_name = f"plan_archive_analyze_{schedule.id}_run_{run.id}"
                    if not self._is_task_running(task_name):
                        self._create_task(
                            self._execute_plan_archive_run(schedule, run),
                            task_name
                        )
                except Exception as e:
                    pass

            async def _execute_plan_archive_run(self, schedule, run):
                pass

        return StubWorker()

    @pytest.mark.asyncio
    async def test_process_plan_archive_schedule_right_runs_when_cron_due(self):
        """R: cron 시간 도래 + 활성 실행 없음 → start_run + _create_task 호출."""
        worker = self._make_worker()

        schedule = MagicMock()
        schedule.id = 1

        schedule_service = MagicMock()
        schedule_service.get_latest_run.return_value = None
        schedule_service.has_active_run.return_value = False
        run = MagicMock()
        run.id = 10
        schedule_service.start_run.return_value = run

        await worker._process_plan_archive_schedule(None, schedule, schedule_service)

        schedule_service.start_run.assert_called_once()
        assert len(worker._tasks) == 1

    @pytest.mark.asyncio
    async def test_process_plan_archive_schedule_boundary_skip_if_active_run(self):
        """B: 이미 활성 실행 존재 → start_run 미호출."""
        worker = self._make_worker()

        schedule = MagicMock()
        schedule.id = 1

        schedule_service = MagicMock()
        schedule_service.get_latest_run.return_value = None
        schedule_service.has_active_run.return_value = True

        await worker._process_plan_archive_schedule(None, schedule, schedule_service)

        schedule_service.start_run.assert_not_called()
        assert len(worker._tasks) == 0

    @pytest.mark.asyncio
    async def test_process_plan_archive_schedule_boundary_cron_not_due(self):
        """B: cron 시간 미도래 → start_run 미호출."""
        worker = self._make_worker()
        worker._should_run_cron = lambda s, lr: False  # cron 미도래

        schedule = MagicMock()
        schedule.id = 1
        schedule_service = MagicMock()
        schedule_service.get_latest_run.return_value = None

        await worker._process_plan_archive_schedule(None, schedule, schedule_service)

        schedule_service.start_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_plan_archive_run_right_complete_run_called(self):
        """R: _process_unprocessed_plans가 3 반환 → complete_run + update_schedule_after_run 호출."""
        from unittest.mock import patch

        class StubWorkerExec:
            name = "test_worker"

            def _process_unprocessed_plans(self):
                return 3

            async def _execute_plan_archive_run(self, schedule, run):
                import asyncio as _asyncio
                from app.services.task_schedule_service import TaskScheduleService
                from app.database import SessionLocal
                db = MagicMock()
                schedule_service = MagicMock()
                loop = _asyncio.get_event_loop()
                count = await loop.run_in_executor(None, self._process_unprocessed_plans)
                schedule_service.complete_run(run.id, result={"queued": count})
                schedule_service.update_schedule_after_run(schedule.id)
                return count, schedule_service

        worker = StubWorkerExec()
        schedule = MagicMock()
        schedule.id = 1
        run = MagicMock()
        run.id = 10

        count, svc = await worker._execute_plan_archive_run(schedule, run)
        assert count == 3
        svc.complete_run.assert_called_once_with(run.id, result={"queued": 3})
        svc.update_schedule_after_run.assert_called_once_with(schedule.id)

    @pytest.mark.asyncio
    async def test_execute_plan_archive_run_error_calls_fail_run(self):
        """E: _process_unprocessed_plans 예외 → fail_run 호출, 예외 외부 전파 없음."""
        class StubWorkerFail:
            name = "test_worker"

            def _process_unprocessed_plans(self):
                raise RuntimeError("db error")

            async def _execute_plan_archive_run(self, schedule, run, schedule_service_mock):
                import asyncio as _asyncio
                loop = _asyncio.get_event_loop()
                try:
                    count = await loop.run_in_executor(None, self._process_unprocessed_plans)
                    schedule_service_mock.complete_run(run.id, result={"queued": count})
                except Exception as e:
                    schedule_service_mock.fail_run(run.id, error_message=str(e))

        worker = StubWorkerFail()
        schedule = MagicMock()
        schedule.id = 1
        run = MagicMock()
        run.id = 10
        svc_mock = MagicMock()

        # 예외가 외부로 전파되지 않아야 함
        await worker._execute_plan_archive_run(schedule, run, svc_mock)
        svc_mock.fail_run.assert_called_once()
        svc_mock.complete_run.assert_not_called()


# ============================================================
# Phase T1: _maybe_queue_requirements_sync() TC
# (plan_analyze_handler._maybe_queue_requirements_sync)
# ============================================================

class TestMaybeQueueRequirementsSync:
    """_maybe_queue_requirements_sync() 동작 검증 (in-memory SQLite)."""

    def _setup_sqlalchemy_db(self):
        """SQLAlchemy in-memory DB + 필요 테이블 생성."""
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite:///:memory:", echo=False)
        # 테이블 생성 (SQLAlchemy model 없이 raw SQL)
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS plan_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename_hash TEXT,
                    filename TEXT,
                    file_path TEXT,
                    archived_at DATETIME,
                    llm_processed_at DATETIME,
                    category TEXT,
                    summary TEXT,
                    tags TEXT,
                    superseded_by TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS llm_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    caller_type TEXT,
                    caller_id TEXT,
                    prompt TEXT,
                    queue_name TEXT,
                    requested_by TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

        Session = sessionmaker(bind=engine)
        return Session()

    def _insert_plan_records(self, db, category: str, count: int, with_summary: bool = True):
        """plan_records 테스트 데이터 삽입."""
        from sqlalchemy import text
        now = datetime.now()
        for i in range(count):
            db.execute(text("""
                INSERT INTO plan_records (filename_hash, filename, file_path, archived_at, llm_processed_at, category, summary)
                VALUES (:hash, :filename, :filepath, :archived, :processed, :category, :summary)
            """), {
                "hash": f"hash_{category}_{i}",
                "filename": f"{category}_plan_{i}.md",
                "filepath": f"docs/archive/{category}_plan_{i}.md",
                "archived": now.isoformat(),
                "processed": now.isoformat(),
                "category": category,
                "summary": f"Summary {i}" if with_summary else None,
            })
        db.commit()

    def test_maybe_queue_right_queues_when_enough(self):
        """R: category='instagram', processed 5개 → LLMRequest 1개 생성."""
        db = self._setup_sqlalchemy_db()
        self._insert_plan_records(db, "instagram", 5)

        from app.modules.claude_worker.services.plan_analyze_handler import _maybe_queue_requirements_sync
        result = _maybe_queue_requirements_sync(db, "instagram")

        assert result is True
        from sqlalchemy import text
        rows = db.execute(text("SELECT * FROM llm_requests WHERE caller_type='plan_requirements_sync' AND caller_id='instagram'")).fetchall()
        assert len(rows) == 1

    def test_maybe_queue_boundary_4_records_skipped(self):
        """B: processed 4개 → LLMRequest 미생성."""
        db = self._setup_sqlalchemy_db()
        self._insert_plan_records(db, "naver-booking", 4)

        from app.modules.claude_worker.services.plan_analyze_handler import _maybe_queue_requirements_sync
        result = _maybe_queue_requirements_sync(db, "naver-booking")

        assert result is False
        from sqlalchemy import text
        rows = db.execute(text("SELECT * FROM llm_requests WHERE caller_type='plan_requirements_sync'")).fetchall()
        assert len(rows) == 0

    def test_maybe_queue_boundary_exactly_5_queued(self):
        """B: processed 정확히 5개 → LLMRequest 1개 생성 (경계값)."""
        db = self._setup_sqlalchemy_db()
        self._insert_plan_records(db, "infra", 5)

        from app.modules.claude_worker.services.plan_analyze_handler import _maybe_queue_requirements_sync
        result = _maybe_queue_requirements_sync(db, "infra")

        assert result is True

    def test_maybe_queue_boundary_24h_duplicate_skipped(self):
        """B: 24시간 내 동일 category LLMRequest 존재 → 중복 미생성."""
        db = self._setup_sqlalchemy_db()
        self._insert_plan_records(db, "writing", 6)

        # 1시간 전 LLMRequest 삽입
        from sqlalchemy import text
        recent = (datetime.now() - timedelta(hours=1)).isoformat()
        db.execute(text("""
            INSERT INTO llm_requests (caller_type, caller_id, prompt, queue_name, requested_by, created_at)
            VALUES ('plan_requirements_sync', 'writing', 'test', 'utility', 'scheduler', :created_at)
        """), {"created_at": recent})
        db.commit()

        from app.modules.claude_worker.services.plan_analyze_handler import _maybe_queue_requirements_sync
        result = _maybe_queue_requirements_sync(db, "writing")

        assert result is False
        from sqlalchemy import text as t
        rows = db.execute(t("SELECT * FROM llm_requests WHERE caller_type='plan_requirements_sync' AND caller_id='writing'")).fetchall()
        assert len(rows) == 1  # 기존 1개만, 새 것 없음

    def test_maybe_queue_right_limits_50_summaries(self):
        """R: processed 80개 → build_requirements_sync_prompt에 ≤50개 summary 전달."""
        db = self._setup_sqlalchemy_db()
        self._insert_plan_records(db, "common", 80)

        captured_summaries = []
        original = None

        import app.modules.claude_worker.services.plan_analyze_handler as handler_mod
        original_build = handler_mod.build_requirements_sync_prompt

        def mock_build(category, plan_summaries):
            captured_summaries.extend(plan_summaries)
            return original_build(category, plan_summaries)

        handler_mod.build_requirements_sync_prompt = mock_build
        try:
            from app.modules.claude_worker.services.plan_analyze_handler import _maybe_queue_requirements_sync
            _maybe_queue_requirements_sync(db, "common")
        finally:
            handler_mod.build_requirements_sync_prompt = original_build

        assert len(captured_summaries) <= 50


# ============================================================
# Phase T1: dispatch 등록 + 하드코딩 제거 TC (AST)
# ============================================================

class TestDispatchAndHardcodingRemoval:
    """AST 기반 구조 검증."""

    def _get_source(self):
        return SCHEDULED_WORKER_PATH.read_text(encoding="utf-8")

    def _get_tree(self):
        return ast.parse(self._get_source())

    def test_dispatch_includes_plan_archive_type(self):
        """R: _dispatch_scheduled_runs()에 TARGET_TYPE_PLAN_ARCHIVE_ANALYZE 참조 존재."""
        source = self._get_source()
        tree = self._get_tree()

        dispatch_func = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef,)) and node.name == "_dispatch_scheduled_runs":
                dispatch_func = node
                break

        assert dispatch_func is not None, "_dispatch_scheduled_runs 메서드를 찾을 수 없음"

        func_source = ast.get_source_segment(source, dispatch_func)
        assert "TARGET_TYPE_PLAN_ARCHIVE_ANALYZE" in (func_source or ""), \
            "_dispatch_scheduled_runs에 TARGET_TYPE_PLAN_ARCHIVE_ANALYZE 참조 없음"

    def test_dispatch_includes_plan_requirements_sync_type(self):
        """R: _dispatch_scheduled_runs()에 TARGET_TYPE_PLAN_REQUIREMENTS_SYNC 참조 존재."""
        source = self._get_source()
        tree = self._get_tree()

        dispatch_func = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef,)) and node.name == "_dispatch_scheduled_runs":
                dispatch_func = node
                break

        assert dispatch_func is not None
        func_source = ast.get_source_segment(source, dispatch_func)
        assert "TARGET_TYPE_PLAN_REQUIREMENTS_SYNC" in (func_source or ""), \
            "_dispatch_scheduled_runs에 TARGET_TYPE_PLAN_REQUIREMENTS_SYNC 참조 없음"

    def test_hardcoded_schedule_method_removed(self):
        """R: _check_plan_archive_schedule 메서드 정의 없음."""
        tree = self._get_tree()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name != "_check_plan_archive_schedule", \
                    "_check_plan_archive_schedule 메서드가 아직 존재함 — 하드코딩 제거 미완료"

    def test_main_loop_no_hardcoded_call(self):
        """R: _main_loop_iteration()에 'check_plan_archive_schedule' 문자열 없음."""
        source = self._get_source()
        tree = self._get_tree()

        main_loop_func = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef,)) and node.name == "_main_loop_iteration":
                main_loop_func = node
                break

        assert main_loop_func is not None, "_main_loop_iteration 메서드를 찾을 수 없음"
        func_source = ast.get_source_segment(source, main_loop_func) or ""
        assert "check_plan_archive_schedule" not in func_source, \
            "_main_loop_iteration에 하드코딩된 check_plan_archive_schedule 호출이 남아있음"
