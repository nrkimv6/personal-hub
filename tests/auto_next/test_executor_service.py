"""ExecutorService TC - RIGHT-BICEP 원칙 적용

대상 소스: app/modules/auto_next/services/executor_service.py (340줄)
Mock 대상: redis.Redis → fakeredis.FakeRedis
"""

import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
import fakeredis

from app.modules.auto_next.services.executor_service import ExecutorService
from app.modules.auto_next.schemas import RunRequest
from fastapi import HTTPException


# ========== Fixtures ==========

@pytest.fixture
def fake_redis():
    """fakeredis 인스턴스"""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def executor_service(fake_redis):
    """fakeredis 주입된 ExecutorService 인스턴스"""
    service = ExecutorService()
    service.redis_client = fake_redis
    return service


@pytest.fixture
def run_request_single():
    """단일 plan 실행 요청"""
    return RunRequest(plan_file="common/docs/plan/test.md")


@pytest.fixture
def run_request_parallel():
    """병렬 실행 요청"""
    return RunRequest(parallel=True, plan_file=None)


@pytest.fixture
def mock_listener_success(fake_redis):
    """BRPOP 결과 mock - 성공 케이스"""
    def setup():
        result_data = {
            "success": True,
            "pid": 12345,
            "log_file": "D:/work/project/logs/auto-next-20260216.log"
        }
        fake_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:pid", "12345")
        fake_redis.set("auto-next:state:plan_file", "common/docs/plan/test.md")
        fake_redis.set("auto-next:state:start_time", datetime.now().isoformat())
        fake_redis.rpush("auto-next:command_results", json.dumps(result_data))
    return setup


# ========== RIGHT-BICEP Tests ==========

class TestStartAutoNext:
    """start_auto_next() 메서드 TC"""

    def test_start_single_plan_builds_correct_command(self, executor_service, run_request_single, mock_listener_success, fake_redis):
        """TC#1: Right - plan_file 있을 때 command에 plan_file 키 포함"""
        mock_listener_success()

        with patch.object(executor_service.redis_client, 'lpush', wraps=fake_redis.lpush) as mock_lpush:
            result = executor_service.start_auto_next(run_request_single)

            # lpush 호출 검증
            assert mock_lpush.call_count == 1
            call_args = mock_lpush.call_args[0]
            command_json = call_args[1]
            command = json.loads(command_json)

            # plan_file 키 포함 확인
            assert "plan_file" in command
            assert command["plan_file"] == "common/docs/plan/test.md"
            assert command["action"] == "run"
            assert command["source"] == "monitor-page-api"

    def test_start_parallel_builds_correct_command(self, executor_service, run_request_parallel, mock_listener_success, fake_redis):
        """TC#2: Right - parallel=True일 때 command에 parallel 키 포함, plan_file 미포함"""
        mock_listener_success()

        with patch.object(executor_service.redis_client, 'lpush', wraps=fake_redis.lpush) as mock_lpush:
            result = executor_service.start_auto_next(run_request_parallel)

            call_args = mock_lpush.call_args[0]
            command = json.loads(call_args[1])

            # parallel 키 포함, plan_file 미포함
            assert command.get("parallel") is True
            assert "plan_file" not in command

    def test_start_all_options_included(self, executor_service, fake_redis, mock_listener_success):
        """TC#3: Right - max_cycles, until, dry_run, skip_plan, projects 전부 command에 반영"""
        request = RunRequest(
            plan_file="test.md",
            max_cycles=5,
            max_tokens=100000,
            until="18:00",
            dry_run=True,
            skip_plan=True,
            projects="activity-hub,wtools"
        )
        mock_listener_success()

        with patch.object(executor_service.redis_client, 'lpush', wraps=fake_redis.lpush) as mock_lpush:
            result = executor_service.start_auto_next(request)

            command = json.loads(mock_lpush.call_args[0][1])

            assert command["max_cycles"] == 5
            assert command["max_tokens"] == 100000
            assert command["until"] == "18:00"
            assert command["dry_run"] is True
            assert command["skip_plan"] is True
            assert command["projects"] == "activity-hub,wtools"

    def test_start_already_running_raises_409(self, executor_service, run_request_single, fake_redis):
        """TC#4: Boundary - status=running일 때 409 반환"""
        # Redis 상태를 running으로 설정
        fake_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:pid", "12345")

        with pytest.raises(HTTPException) as exc_info:
            executor_service.start_auto_next(run_request_single)

        assert exc_info.value.status_code == 409
        assert "Already running" in exc_info.value.detail

    def test_start_redis_down_raises_503(self, executor_service, run_request_single):
        """TC#5: Boundary - Redis 연결 실패 시 503"""
        # Redis 연결 끊기
        executor_service.redis_client.connection_pool.disconnect()

        with pytest.raises(HTTPException) as exc_info:
            executor_service.start_auto_next(run_request_single)

        assert exc_info.value.status_code == 503
        assert "Redis connection failed" in exc_info.value.detail

    def test_start_listener_timeout_raises_504(self, executor_service, run_request_single, fake_redis):
        """TC#6: Boundary - BRPOP 타임아웃 시 504"""
        # BRPOP 타임아웃 mock (None 반환)
        with patch.object(fake_redis, 'brpop', return_value=None):
            executor_service.redis_client.brpop = fake_redis.brpop

            with pytest.raises(HTTPException) as exc_info:
                executor_service.start_auto_next(run_request_single)

            assert exc_info.value.status_code == 504
            assert "Command timeout" in exc_info.value.detail

    def test_start_listener_returns_failure(self, executor_service, run_request_single, fake_redis):
        """TC#7: Error - listener가 success=False 반환 시 500"""
        # listener 실패 응답
        result_data = {"success": False, "message": "Failed to spawn process"}
        fake_redis.rpush("auto-next:command_results", json.dumps(result_data))

        with pytest.raises(HTTPException) as exc_info:
            executor_service.start_auto_next(run_request_single)

        assert exc_info.value.status_code == 500
        assert "Failed to start" in exc_info.value.detail


class TestStopAutoNext:
    """stop_auto_next() 메서드 TC"""

    def test_stop_not_running_raises_404(self, executor_service, fake_redis):
        """TC#8: Boundary - 미실행 상태에서 stop 시 404"""
        # Redis 상태를 stopped 또는 None으로 설정
        fake_redis.set("auto-next:state:status", "stopped")

        with pytest.raises(HTTPException) as exc_info:
            executor_service.stop_auto_next()

        assert exc_info.value.status_code == 404
        assert "Not running" in exc_info.value.detail

    def test_stop_listener_timeout_force_cleanup(self, executor_service, fake_redis):
        """TC#9: Error - listener 무응답 시 Redis 상태 강제 정리"""
        # running 상태 설정
        fake_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:pid", "12345")
        fake_redis.set("auto-next:state:plan_file", "test.md")

        # BRPOP 타임아웃 mock
        with patch.object(fake_redis, 'brpop', return_value=None):
            executor_service.redis_client.brpop = fake_redis.brpop

            result = executor_service.stop_auto_next()

            # 상태 정리 확인
            assert fake_redis.get("auto-next:state:status") is None
            assert fake_redis.get("auto-next:state:pid") is None
            assert "Force cleaned" in result["message"]


class TestGetProcessStatus:
    """get_process_status() 메서드 TC"""

    def test_status_running_with_dead_pid_auto_cleanup(self, executor_service, fake_redis):
        """TC#10: Cross-check - PID 죽으면 자동으로 stopped 전환"""
        # running 상태 설정
        fake_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:pid", "99999")  # 존재하지 않는 PID

        # _is_pid_alive mock - False 반환
        with patch.object(executor_service, '_is_pid_alive', return_value=False):
            result = executor_service.get_process_status()

            # 자동 정리 확인
            assert result.running is False
            assert result.pid is None
            assert fake_redis.get("auto-next:state:status") is None

    def test_status_redis_down_returns_not_running(self, executor_service):
        """TC#11: Error - Redis 다운 시 running=False 반환"""
        # Redis 연결 끊기
        executor_service.redis_client.connection_pool.disconnect()

        result = executor_service.get_process_status()

        # 에러 발생 안 하고 False 반환
        assert result.running is False
        assert result.pid is None


class TestResetRunningState:
    """reset_running_state() 메서드 TC"""

    def test_reset_state_running_to_pending(self, executor_service, fake_redis, tmp_path):
        """TC#12: Right - RUNNING task → PENDING 복구"""
        # SQLite DB mock
        import sqlite3
        db_path = tmp_path / "auto_next.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                status TEXT,
                started_at TEXT
            )
        """)
        cursor.execute("INSERT INTO tasks VALUES ('task1', 'running', '2026-02-16 10:00:00')")
        cursor.execute("INSERT INTO tasks VALUES ('task2', 'pending', NULL)")
        conn.commit()
        conn.close()

        # config mock
        with patch('app.modules.auto_next.services.executor_service.config') as mock_config:
            mock_config.AUTO_NEXT_DB_PATH = str(db_path)

            result = executor_service.reset_running_state(full_reset=False)

            # 결과 검증
            assert result["success"] is True
            assert result["reset_count"] == 1

            # DB 상태 검증
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM tasks WHERE id='task1'")
            status = cursor.fetchone()[0]
            assert status == "pending"
            conn.close()

    def test_reset_state_full_deletes_all(self, executor_service, fake_redis, tmp_path):
        """TC#13: Right - full_reset=True → 전체 삭제"""
        # SQLite DB mock
        import sqlite3
        db_path = tmp_path / "auto_next.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                status TEXT
            )
        """)
        cursor.execute("INSERT INTO tasks VALUES ('task1', 'running')")
        cursor.execute("INSERT INTO tasks VALUES ('task2', 'success')")
        conn.commit()
        conn.close()

        with patch('app.modules.auto_next.services.executor_service.config') as mock_config:
            mock_config.AUTO_NEXT_DB_PATH = str(db_path)

            result = executor_service.reset_running_state(full_reset=True)

            assert result["success"] is True
            assert result["reset_count"] == 2
            assert result["full_reset"] is True

            # DB 전체 삭제 확인
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tasks")
            count = cursor.fetchone()[0]
            assert count == 0
            conn.close()

    def test_reset_state_no_running_tasks(self, executor_service, fake_redis, tmp_path):
        """TC#14: Boundary - RUNNING 0건일 때 정상 반환"""
        # SQLite DB mock - RUNNING 없음
        import sqlite3
        db_path = tmp_path / "auto_next.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                status TEXT
            )
        """)
        cursor.execute("INSERT INTO tasks VALUES ('task1', 'success')")
        conn.commit()
        conn.close()

        with patch('app.modules.auto_next.services.executor_service.config') as mock_config:
            mock_config.AUTO_NEXT_DB_PATH = str(db_path)

            result = executor_service.reset_running_state(full_reset=False)

            assert result["success"] is True
            assert result["reset_count"] == 0


# ========== CORRECT 원칙 추가 TC ==========

class TestCORRECTConformance:
    """Conformance - 스키마 준수"""

    def test_run_request_invalid_schema_raises_error(self):
        """RunRequest 필드 타입 오류 시 Pydantic 에러"""
        with pytest.raises(Exception):  # Pydantic ValidationError
            RunRequest(max_cycles="invalid")  # 문자열 → int 필드


class TestCORRECTExistence:
    """Existence - None vs 빈 문자열"""

    def test_plan_file_none_vs_empty(self, executor_service, fake_redis, mock_listener_success):
        """plan_file=None vs plan_file='' 차이"""
        mock_listener_success()

        # None - 키 미포함
        request1 = RunRequest(plan_file=None)
        with patch.object(executor_service.redis_client, 'lpush', wraps=fake_redis.lpush) as mock_lpush:
            executor_service.start_auto_next(request1)
            command1 = json.loads(mock_lpush.call_args[0][1])
            assert "plan_file" not in command1

        # 빈 문자열 - 키 미포함 (조건: if request.plan_file)
        fake_redis.delete("auto-next:command_results")
        mock_listener_success()
        request2 = RunRequest(plan_file="")
        with patch.object(executor_service.redis_client, 'lpush', wraps=fake_redis.lpush) as mock_lpush:
            executor_service.start_auto_next(request2)
            command2 = json.loads(mock_lpush.call_args[0][1])
            assert "plan_file" not in command2
