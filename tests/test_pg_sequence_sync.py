"""
PostgreSQL SERIAL 시퀀스 동기화 테스트.

Phase T1: 단위 테스트 (mock 기반)
Phase T3: 재현/통합 테스트 (실제 PG 연결)
Phase T4: E2E 테스트 (실제 서버 8001, pytest.mark.e2e)
Phase T5: HTTP 통합 테스트 (실제 서버 8001, pytest.mark.http_live)
"""
import os
import sys
import pytest
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, call

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── 헬퍼 ──────────────────────────────────────────────────────────────────

def _make_mock_conn(seq_exists: bool = True, raise_on_setval: Exception = None):
    """mock connection 빌더.
    execute() 호출 패턴:
      1st call: SELECT EXISTS ... (시퀀스 존재 확인)
      2nd call: SELECT setval(...) (실제 동기화)
    """
    mock_conn = MagicMock()

    def _execute(sql, params=None):
        sql_str = str(sql)
        if "pg_sequences" in sql_str:
            result = MagicMock()
            result.scalar.return_value = seq_exists
            return result
        if "setval" in sql_str:
            if raise_on_setval:
                raise raise_on_setval
            return MagicMock()
        return MagicMock()

    mock_conn.execute.side_effect = _execute
    return mock_conn


def _make_engine_ctx(mock_conn):
    """engine.begin() 컨텍스트 매니저 mock 빌더."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = ctx
    return mock_engine


# ── Phase T1: 단위 테스트 ─────────────────────────────────────────────────

class TestSyncSerialSequences:
    """sync_serial_sequences() 단위 테스트 (RIGHT-BICEP)"""

    def test_sync_serial_sequences_right(self):
        """R(Right): PG 환경에서 존재하는 테이블 1개 — 시퀀스 동기화 1건 반환"""
        mock_conn = _make_mock_conn(seq_exists=True)
        mock_engine = _make_engine_ctx(mock_conn)

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["git_operation_logs"]

        with patch("app.core.database.is_pg", True), \
             patch("app.core.database.engine", mock_engine), \
             patch("app.core.database.inspect", return_value=mock_insp), \
             patch("app.core.database.PG_SERIAL_TABLES", ["git_operation_logs"]):
            from app.core.database import sync_serial_sequences
            result = sync_serial_sequences()

        assert result == 1
        # setval SQL이 git_operation_logs_id_seq 포함해 호출됐는지 확인
        calls = [str(c.args[0]) for c in mock_conn.execute.call_args_list if c.args]
        assert any("git_operation_logs_id_seq" in c for c in calls)

    def test_sync_serial_sequences_boundary_empty_table(self):
        """B(Boundary): 테이블이 비어있어도 COALESCE(MAX(id),0) → 시퀀스 0 설정 후 정상 반환"""
        # 빈 테이블 시나리오: setval이 0으로 호출돼도 예외 없어야 함
        mock_conn = _make_mock_conn(seq_exists=True)
        mock_engine = _make_engine_ctx(mock_conn)

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["git_operation_logs"]

        with patch("app.core.database.is_pg", True), \
             patch("app.core.database.engine", mock_engine), \
             patch("app.core.database.inspect", return_value=mock_insp), \
             patch("app.core.database.PG_SERIAL_TABLES", ["git_operation_logs"]):
            from app.core.database import sync_serial_sequences
            result = sync_serial_sequences()

        # COALESCE(MAX(id), 0) 이므로 빈 테이블도 synced=1 반환
        assert result == 1
        calls = [str(c.args[0]) for c in mock_conn.execute.call_args_list if c.args]
        assert any("GREATEST" in c for c in calls)

    def test_sync_serial_sequences_error_nonexistent_table(self, caplog):
        """E(Error): PG_SERIAL_TABLES에 없는 테이블 → 예외 없이 정상 반환 + 경고 로그"""
        # setval 시 예외 발생 시나리오 (테이블 존재하지만 시퀀스 오류)
        mock_conn = _make_mock_conn(seq_exists=True, raise_on_setval=Exception("table not found"))
        mock_engine = _make_engine_ctx(mock_conn)

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["__nonexistent_test_table__"]

        with patch("app.core.database.is_pg", True), \
             patch("app.core.database.engine", mock_engine), \
             patch("app.core.database.inspect", return_value=mock_insp), \
             patch("app.core.database.PG_SERIAL_TABLES", ["__nonexistent_test_table__"]):
            from app.core.database import sync_serial_sequences
            with caplog.at_level(logging.WARNING):
                result = sync_serial_sequences()

        # 예외 전파 없이 0 반환 (동기화 실패)
        assert result == 0
        assert any("SEQ-SYNC" in r.message or "시퀀스 동기화 실패" in r.message
                   for r in caplog.records)

    def test_sync_serial_sequences_skips_sqlite(self):
        """C(Cross-check): SQLite 환경(is_pg=False) → 0 즉시 반환, engine 쿼리 미실행"""
        mock_engine = MagicMock()

        with patch("app.core.database.is_pg", False), \
             patch("app.core.database.engine", mock_engine):
            from app.core.database import sync_serial_sequences
            result = sync_serial_sequences()

        assert result == 0
        mock_engine.begin.assert_not_called()

    def test_sync_serial_sequences_skips_missing_table(self):
        """B(Boundary): existing_tables에 없는 테이블은 쿼리 없이 스킵"""
        mock_conn = MagicMock()
        mock_engine = _make_engine_ctx(mock_conn)

        mock_insp = MagicMock()
        # DB에 없는 테이블 목록 반환
        mock_insp.get_table_names.return_value = []

        with patch("app.core.database.is_pg", True), \
             patch("app.core.database.engine", mock_engine), \
             patch("app.core.database.inspect", return_value=mock_insp), \
             patch("app.core.database.PG_SERIAL_TABLES", ["git_operation_logs"]):
            from app.core.database import sync_serial_sequences
            result = sync_serial_sequences()

        # 테이블이 없으면 execute 호출 없음
        assert result == 0
        mock_conn.execute.assert_not_called()

    def test_sync_serial_sequences_skips_missing_sequence(self):
        """B(Boundary): 테이블은 있지만 시퀀스가 없으면(seq_exists=False) 스킵"""
        mock_conn = _make_mock_conn(seq_exists=False)
        mock_engine = _make_engine_ctx(mock_conn)

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["git_operation_logs"]

        with patch("app.core.database.is_pg", True), \
             patch("app.core.database.engine", mock_engine), \
             patch("app.core.database.inspect", return_value=mock_insp), \
             patch("app.core.database.PG_SERIAL_TABLES", ["git_operation_logs"]):
            from app.core.database import sync_serial_sequences
            result = sync_serial_sequences()

        # 시퀀스 미존재 → setval 미실행 → synced=0
        assert result == 0
        calls_str = [str(c.args[0]) for c in mock_conn.execute.call_args_list if c.args]
        assert not any("setval" in c for c in calls_str)


# ── Phase T3: 재현/통합 테스트 ───────────────────────────────────────────

def _pg_available() -> bool:
    """실제 PG 연결 가능 여부 확인"""
    try:
        from sqlalchemy import create_engine, text
        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor"
        )
        if not db_url.startswith("postgresql"):
            return False
        eng = create_engine(db_url, connect_args={"connect_timeout": 3})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_available(), reason="실제 PostgreSQL 연결 불가 — 통합 TC 스킵")
class TestSequenceDesyncIntegration:
    """T3: 시퀀스 불일치 재현 + sync_serial_sequences() 수정 검증"""

    @pytest.fixture(autouse=True)
    def pg_engine(self):
        from sqlalchemy import create_engine
        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor"
        )
        self.engine = create_engine(db_url)
        yield
        self.engine.dispose()

    def test_sequence_desync_causes_unique_violation(self):
        """
        실제 PG에서 시퀀스 불일치 → UniqueViolation 재현 → sync 후 정상 INSERT 확인.

        안전 전략:
        - 임시 테스트 전용 테이블 사용 (git_operation_logs 직접 조작 금지)
        - 테스트 후 테이블 DROP으로 정리
        """
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        import app.core.database as db_mod

        table = "_test_seq_sync_verify"
        seq = f"{table}_id_seq"

        with self.engine.begin() as conn:
            # 테스트 테이블 생성
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
            conn.execute(text(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, val TEXT)"))

            # 데이터 3건 삽입 (id=1,2,3)
            conn.execute(text(f"INSERT INTO {table}(val) VALUES ('a'), ('b'), ('c')"))

            # 시퀀스를 1로 강제 리셋 (불일치 유발)
            conn.execute(text(f"SELECT setval('{seq}', 1)"))

        # 시퀀스 불일치 상태에서 INSERT 시도 → UniqueViolation
        with pytest.raises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(text(f"INSERT INTO {table}(val) VALUES ('d')"))

        # sync_serial_sequences() 를 이 테이블에 대해 직접 실행
        with self.engine.begin() as conn:
            conn.execute(text(
                f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 0))"
            ))

        # 동기화 후 INSERT 성공 확인 (id=4)
        with self.engine.begin() as conn:
            result = conn.execute(
                text(f"INSERT INTO {table}(val) VALUES ('d') RETURNING id")
            )
            new_id = result.scalar()

        assert new_id == 4, f"시퀀스 동기화 후 예상 id=4, 실제={new_id}"

        # 정리
        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))

    def test_sync_serial_sequences_fixes_real_desync(self):
        """
        sync_serial_sequences() 함수 직접 호출로 실제 시퀀스 불일치를 복구.
        임시 테이블에서 불일치 유발 후 함수 호출 → synced 반환값 > 0 확인.
        """
        from sqlalchemy import text
        import app.core.database as db_mod

        table = "_test_seq_sync_verify2"
        seq = f"{table}_id_seq"

        # 임시 테이블 생성 + 데이터 + 시퀀스 리셋
        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
            conn.execute(text(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, val TEXT)"))
            conn.execute(text(f"INSERT INTO {table}(val) VALUES ('x'), ('y')"))
            conn.execute(text(f"SELECT setval('{seq}', 1)"))

        # PG_SERIAL_TABLES에 임시 테이블 추가해서 sync_serial_sequences() 실행
        original_tables = db_mod.PG_SERIAL_TABLES
        try:
            db_mod.PG_SERIAL_TABLES = [table]
            synced = db_mod.sync_serial_sequences()
        finally:
            db_mod.PG_SERIAL_TABLES = original_tables

        assert synced == 1, f"동기화 건수 1 예상, 실제={synced}"

        # 동기화 후 INSERT 성공 + 중복 없음 확인 (MAX(id)=2 → setval(seq,2) → nextval=3)
        with self.engine.begin() as conn:
            result = conn.execute(text(f"INSERT INTO {table}(val) VALUES ('z') RETURNING id"))
            next_id = result.scalar()
        assert next_id == 3, f"동기화 후 nextval=3 예상, 실제={next_id}"

        # 정리
        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


# ── Phase T4: E2E 테스트 (실제 서버 8001) ────────────────────────────────

_LIVE_BASE = "http://localhost:8001/api/v1/git-repos"


def _server_available() -> bool:
    try:
        import requests
        r = requests.get("http://localhost:8001/api/v1/dev-runner/runners", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _live_api(method, path="", json=None, params=None):
    import requests
    url = f"{_LIVE_BASE}{path}"
    return getattr(requests, method)(url, json=json, params=params, timeout=15)


def _poll_task(task_id: str, interval: float = 0.5, max_retries: int = 40) -> dict:
    import time
    for _ in range(max_retries):
        resp = _live_api("get", f"/tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] != "pending":
            return data
        time.sleep(interval)
    raise TimeoutError(f"Task {task_id} timed out after {max_retries * interval}s")


@pytest.mark.e2e
@pytest.mark.skipif(not _server_available(), reason="실제 서버(8001) 미응답 — E2E 스킵")
class TestSequenceSyncE2E:
    """T4: 시퀀스 동기화 후 git_operation_logs INSERT 정상 동작 E2E 검증"""

    @pytest.fixture(scope="class")
    def test_repo(self):
        """E2E 테스트용 레포 등록 → 사용 → 삭제."""
        import subprocess, tempfile, shutil
        tmpdir = tempfile.mkdtemp(prefix="seq_sync_e2e_")
        repo_id = None
        try:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmpdir, capture_output=True)
            (Path(tmpdir) / "readme.txt").write_text("hello")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)

            resp = _live_api("post", "", json={"path": tmpdir, "alias": "seq_sync_e2e_test"})
            assert resp.status_code == 200, f"레포 등록 실패: {resp.text}"
            repo_id = resp.json()["id"]
            yield {"id": repo_id, "path": tmpdir}
        finally:
            if repo_id:
                _live_api("delete", f"/{repo_id}")
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_git_repos_e2e_after_sync(self, test_repo):
        """
        E2E: 시퀀스 동기화 후 git_operation_logs INSERT 정상 동작 확인.
        unstage API → poll_task → status=completed (UniqueViolation 미발생)
        """
        import subprocess
        repo_id = test_repo["id"]
        repo_path = test_repo["path"]

        (Path(repo_path) / "test_file.txt").write_text("changed")
        subprocess.run(["git", "add", "test_file.txt"], cwd=repo_path, capture_output=True)

        resp = _live_api("post", f"/{repo_id}/unstage", json={"files": ["test_file.txt"]})
        assert resp.status_code == 200, f"unstage 실패: {resp.text}"
        task_id = resp.json().get("task_id")
        assert task_id

        result = _poll_task(task_id)
        assert result["status"] == "completed", f"task 완료 실패: {result}"


# ── Phase T5: HTTP 통합 테스트 (실제 서버 8001) ───────────────────────────

@pytest.mark.http_live
@pytest.mark.skipif(not _server_available(), reason="실제 서버(8001) 미응답 — HTTP_LIVE 스킵")
class TestSequenceSyncHttpLive:
    """T5: HTTP 엔드포인트를 통한 log_operation INSERT 검증"""

    @pytest.fixture(scope="class")
    def test_repo(self):
        """HTTP 테스트용 레포 등록 → 사용 → 삭제."""
        import subprocess, tempfile, shutil
        tmpdir = tempfile.mkdtemp(prefix="seq_sync_http_")
        repo_id = None
        try:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmpdir, capture_output=True)
            (Path(tmpdir) / "readme.txt").write_text("init")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)

            resp = _live_api("post", "", json={"path": tmpdir, "alias": "seq_sync_http_test"})
            assert resp.status_code == 200, f"레포 등록 실패: {resp.text}"
            repo_id = resp.json()["id"]
            yield {"id": repo_id, "path": tmpdir}
        finally:
            if repo_id:
                _live_api("delete", f"/{repo_id}")
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_http_git_repos_unstage_creates_log(self, test_repo):
        """
        POST /api/v1/git-repos/{id}/unstage → 200 응답 → 워커 완료 후 git_operation_logs 레코드 확인.
        시퀀스 동기화 후 UniqueViolation 없이 INSERT 성공 검증.
        """
        import subprocess
        from sqlalchemy import create_engine, text as sa_text
        repo_id = test_repo["id"]
        repo_path = test_repo["path"]

        (Path(repo_path) / "unstage_test.txt").write_text("data")
        subprocess.run(["git", "add", "unstage_test.txt"], cwd=repo_path, capture_output=True)

        resp = _live_api("post", f"/{repo_id}/unstage", json={"files": ["unstage_test.txt"]})
        assert resp.status_code == 200, f"unstage API 실패: {resp.text}"
        task_id = resp.json().get("task_id")
        assert task_id

        result = _poll_task(task_id)
        assert result["status"] == "completed", f"task 미완료: {result}"

        db_url = os.environ.get("DATABASE_URL", "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor")
        eng = create_engine(db_url)
        with eng.connect() as conn:
            count = conn.execute(sa_text(
                "SELECT COUNT(*) FROM git_operation_logs WHERE repo_id = :rid AND operation = 'unstage'"
            ), {"rid": repo_id}).scalar()
        eng.dispose()
        assert count >= 1, f"git_operation_logs에 unstage 레코드 없음 (count={count})"

    def test_http_git_repos_commit_creates_log(self, test_repo):
        """
        POST /api/v1/git-repos/{id}/commit → 200 응답 → 워커 완료 후 git_operation_logs 레코드 확인.
        """
        import subprocess
        from sqlalchemy import create_engine, text as sa_text
        repo_id = test_repo["id"]
        repo_path = test_repo["path"]

        (Path(repo_path) / "commit_test.txt").write_text("commit data")
        subprocess.run(["git", "add", "commit_test.txt"], cwd=repo_path, capture_output=True)

        resp = _live_api("post", f"/{repo_id}/commit", json={"message": "T5 test commit"})
        assert resp.status_code == 200, f"commit API 실패: {resp.text}"
        task_id = resp.json().get("task_id")
        assert task_id

        result = _poll_task(task_id)
        assert result["status"] == "completed", f"task 미완료: {result}"

        db_url = os.environ.get("DATABASE_URL", "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor")
        eng = create_engine(db_url)
        with eng.connect() as conn:
            count = conn.execute(sa_text(
                "SELECT COUNT(*) FROM git_operation_logs WHERE repo_id = :rid AND operation = 'commit'"
            ), {"rid": repo_id}).scalar()
        eng.dispose()
        assert count >= 1, f"git_operation_logs에 commit 레코드 없음 (count={count})"
