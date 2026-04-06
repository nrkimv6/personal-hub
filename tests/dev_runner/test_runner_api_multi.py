"""멀티 runner API 라우터 HTTP 테스트 (TestClient e2e)

Phase 4 구현 검증: GET /runners, POST /runners/{id}/stop, POST /run runner_id 반환,
GET /logs/recent?runner_id=..., runner_id 누락 시 422

Phase T3 추가: 동일 plan 반복 실행 시 execution_count 증가 + RUN_META 통합 검증
"""
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.dev_runner._path_helpers import get_repo_root, get_listener_script_path, skip_if_missing

# WorkflowManager T3 통합 테스트용 scripts 경로 등록
_SCRIPTS_DIR = get_repo_root() / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from app.modules.dev_runner.schemas import RunnerListItem, RunStatusResponse, LogResponse
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.routes.logs import router as logs_router

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


@pytest.fixture
def client():
    """최소 FastAPI 앱 — dev-runner router만 포함"""
    test_app = FastAPI()
    test_app.include_router(runner_router, prefix=BASE_URL)
    test_app.include_router(logs_router, prefix=BASE_URL)
    return TestClient(test_app)


class TestGetRunners:
    """GET /runners — 활성 runner 목록"""

    def test_get_runners_returns_list(self, client):
        """Redis mock → 200 + list 형식 응답"""
        mock_items = [
            RunnerListItem(
                runner_id="t-apimulti-abc1",
                running=True,
                plan_file="test.md",
                engine="claude",
                start_time=datetime.now(),
                execution_count=2,
                pid=1234,
            )
        ]
        with patch.object(executor_service, "get_all_runners", return_value=mock_items):
            resp = client.get(f"{BASE_URL}/runners")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["runner_id"] == "t-apimulti-abc1"
        assert data[0]["running"] is True
        assert data[0]["execution_count"] == 2

    def test_get_runners_redis_unavailable_returns_empty_list(self, client):
        """Redis 미연결 → 200 빈 list (예외 미전파)"""
        with patch.object(executor_service, "get_all_runners", return_value=[]):
            resp = client.get(f"{BASE_URL}/runners")

        assert resp.status_code == 200
        assert resp.json() == []


class TestStopRunner:
    """POST /runners/{runner_id}/stop"""

    def test_stop_existing_runner(self, client):
        """존재하는 runner → 200"""
        with patch.object(executor_service, "stop_dev_runner", new_callable=AsyncMock,
                          return_value={"message": "Stopped successfully"}):
            resp = client.post(f"{BASE_URL}/runners/abc12345/stop")

        assert resp.status_code == 200

    def test_stop_nonexistent_runner_returns_404(self, client):
        """없는 runner_id → 404"""
        from fastapi import HTTPException

        with patch.object(executor_service, "stop_dev_runner", new_callable=AsyncMock,
                          side_effect=HTTPException(status_code=404, detail="Not running")):
            resp = client.post(f"{BASE_URL}/runners/notexist/stop")

        assert resp.status_code == 404


class TestPostRun:
    """POST /run — runner_id 필드 존재 확인"""

    def test_run_response_contains_runner_id(self, client):
        """POST /run 성공 응답 JSON에 runner_id 필드 존재 + 8자 hex"""
        mock_response = RunStatusResponse(
            running=True,
            runner_id="ab12ef34",
            engine="claude",
            listener_alive=True,
            redis_connected=True,
            pid=1234,
            plan_file="test.md",
            start_time=datetime.now(),
            execution_count=1,
            current_cycle=0,
            exit_code=None,
            crashed=False,
            current_plan_name=None,
        )

        with patch.object(executor_service, "start_dev_runner", new_callable=AsyncMock,
                          return_value=mock_response):
            resp = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": "test.md", "engine": "claude"}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "runner_id" in data
        assert data["runner_id"] == "ab12ef34"
        assert len(data["runner_id"]) == 8
        assert all(c in "0123456789abcdef" for c in data["runner_id"])
        assert data["execution_count"] == 1


class TestGetRecentLogs:
    """GET /logs/recent?runner_id=...&lines=N"""

    def test_get_recent_logs_with_runner_id(self, client):
        """runner_id 있으면 200 + LogResponse 스키마"""
        from app.modules.dev_runner.services.log_service import log_service

        mock_log = LogResponse(lines=["line1", "line2"], total_lines=2)
        with patch.object(log_service, "tail_log_file", return_value=mock_log):
            resp = client.get(f"{BASE_URL}/logs/recent?runner_id=abc12345&lines=10")

        assert resp.status_code == 200
        data = resp.json()
        assert "lines" in data
        assert "total_lines" in data

    def test_get_recent_logs_missing_runner_id_returns_422(self, client):
        """runner_id 누락 → 422 (Query 필수 파라미터 검증)"""
        resp = client.get(f"{BASE_URL}/logs/recent?lines=10")
        assert resp.status_code == 422

    def test_get_recent_logs_uses_logfile_when_stream_too_small(self, client, tmp_path):
        """T4: stream_log_path 소형(200B 이하) + log_file_path 정상 → log_file 내용 반환
        (stream_log 우선순위 수정 후 HTTP 레벨 동작 검증)
        """
        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[2026-03-05T20:18:13] START | log_path=...\n")  # 43B

        log_file = tmp_path / "log.log"
        log_file.write_text(
            "[20:18:13] [PLAN-RUNNER] [INFO] Plan-Runner 시작\n"
            "[20:18:13] [PLAN-RUNNER] [DONE] Plan-Runner 종료\n",
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.log_service import log_service

        with patch.object(log_service, "_find_current_log", return_value=log_file):
            resp = client.get(f"{BASE_URL}/logs/recent?runner_id=test-stream-fix&lines=10")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 2
        assert "Plan-Runner 시작" in data["lines"][0]


# ========== T3: 반복 실행 통합 검증 ==========

def _make_wf_db(tmp_path: Path):
    """임시 SQLite + workflows 테이블 초기화된 WorkflowManager 반환."""
    from workflow_manager import WorkflowManager

    db_path = tmp_path / "t3_workflow.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            slug            TEXT    NOT NULL UNIQUE,
            plan_file       TEXT,
            branch          TEXT,
            runner_id       TEXT,
            status          TEXT    NOT NULL DEFAULT 'planned',
            engine          TEXT,
            error_message   TEXT,
            commit_hash     TEXT,
            worktree_path   TEXT,
            created_at      TEXT,
            started_at      TEXT,
            merged_at       TEXT,
            finished_at     TEXT
        )
    """)
    conn.commit()
    conn.close()
    return WorkflowManager(db_path)


_listener_cache = {}


def _load_listener():
    """listener 스크립트를 importlib으로 로드 (캐시)."""
    if "mod" in _listener_cache:
        return _listener_cache["mod"]
    path = get_listener_script_path()
    skip_if_missing(path, "Listener script")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener_t3", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_cache["mod"] = mod
    return mod


class TestRepeatedRunIntegrationT3:
    """T3: 동일 plan 반복 실행 시 순번·시작메타 통합 검증

    WorkflowManager 집계 + _launch_plan_runner_process 통합 시나리오.
    실제 HTTP 서버 불필요 — SQLite(tmp) + fakeredis + mock subprocess.
    """

    @pytest.fixture(autouse=True)
    def _reset_listener_globals(self):
        """listener 전역 dict 격리 (모듈 로드 성공 시에만)."""
        try:
            mod = _load_listener()
            mod._running_processes.clear()
            mod._running_log_files.clear()
            mod._stream_threads.clear()
        except Exception:
            pass
        yield
        try:
            mod = _load_listener()
            mod._running_processes.clear()
            mod._running_log_files.clear()
            mod._stream_threads.clear()
        except Exception:
            pass

    def test_repeated_same_plan_execution_count_increments(self, tmp_path):
        """R: 같은 plan 2회 실행 → execution_count 1, 2 순서대로 증가"""
        wf = _make_wf_db(tmp_path)

        id1 = wf.create("t3-rpt-a1", "docs/plan/repeat.md")
        _, count1 = wf.mark_running_with_execution_count(
            id1, "runner-t3a1", "impl/repeat", ".worktrees/impl-repeat", "claude"
        )
        assert count1 == 1

        id2 = wf.create("t3-rpt-a2", "docs/plan/repeat.md")
        _, count2 = wf.mark_running_with_execution_count(
            id2, "runner-t3a2", "impl/repeat", ".worktrees/impl-repeat", "claude"
        )
        assert count2 == 2

    def test_run_meta_in_log_file_and_redis_channel(self, tmp_path):
        """R: 2회 실행 시 로그 파일 + Redis publish 양쪽에 [RUN_META] started_at 존재"""
        mod = _load_listener()

        server = fakeredis.FakeServer()
        fr = fakeredis.FakeRedis(server=server, decode_responses=True)

        mock_proc = MagicMock()
        mock_proc.pid = 9900
        mock_proc.poll.return_value = None

        worktree = tmp_path / "wt"
        worktree.mkdir()

        published_messages = []

        def _capture_publish(channel, message):
            published_messages.append(message)

        for run_n, runner_id in enumerate(["t3-log-r1", "t3-log-r2"], start=1):
            stale = [k for k in fr.keys() if runner_id in k]
            if stale:
                fr.delete(*stale)
            command = {
                "action": "run",
                "runner_id": runner_id,
                "plan_file": "docs/plan/run-meta-test.md",
                "trigger": "user",
                "engine": "claude",
                "started_at": f"2026-04-06T10:0{run_n}:00",
                "execution_count": run_n,
                "plan_key": "docs/plan/run-meta-test.md",
            }
            with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
                 patch("_dr_plan_runner.threading.Thread") as mock_thread, \
                 patch("_dr_plan_runner.subprocess.Popen", return_value=mock_proc), \
                 patch.object(fr, "publish", side_effect=_capture_publish):
                mock_thread.return_value = MagicMock()
                result = mod._launch_plan_runner_process(
                    command, fr, runner_id, worktree,
                    "docs/plan/run-meta-test.md", "claude"
                )

            # 로그 파일(full log)에 [RUN_META] started_at 확인
            log_lines = Path(result["log_file"]).read_text(encoding="utf-8").splitlines()
            run_meta_lines = [l for l in log_lines if l.startswith("[RUN_META]")]
            assert run_meta_lines, f"run {run_n}: 로그 파일에 [RUN_META] 없음"
            assert f"started_at=2026-04-06T10:0{run_n}:00" in run_meta_lines[0]
            assert f"execution_count={run_n}" in run_meta_lines[0]

        # 실시간 채널 publish에도 RUN_META 포함 확인 (2회 실행 = 2번 publish)
        rn_meta_published = [m for m in published_messages if "[RUN_META]" in m]
        assert len(rn_meta_published) == 2, (
            f"RUN_META publish 횟수 불일치: {rn_meta_published}"
        )
        assert "execution_count=1" in rn_meta_published[0]
        assert "execution_count=2" in rn_meta_published[1]

    def test_sentinel_all_plans_repeated_count_increments(self, tmp_path):
        """R: __ALL_PLANS__ sentinel 2회 실행 → 별도 그룹으로 count=1,2, 개별 plan과 격리"""
        wf = _make_wf_db(tmp_path)

        # sentinel 1회차
        id_s1 = wf.create("t3-sent-1", None)
        _, sc1 = wf.mark_running_with_execution_count(
            id_s1, "runner-s1", "impl/all", ".worktrees/impl-all", "claude"
        )
        assert sc1 == 1

        # sentinel 2회차 (__ALL_PLANS__ 표기도 동일 그룹)
        id_s2 = wf.create("t3-sent-2", "__ALL_PLANS__")
        _, sc2 = wf.mark_running_with_execution_count(
            id_s2, "runner-s2", "impl/all2", ".worktrees/impl-all2", "claude"
        )
        assert sc2 == 2

        # 개별 plan은 sentinel과 격리되어 count=1에서 시작
        id_p1 = wf.create("t3-indiv-1", "docs/plan/specific.md")
        _, pc1 = wf.mark_running_with_execution_count(
            id_p1, "runner-p1", "impl/specific", ".worktrees/impl-specific", "claude"
        )
        assert pc1 == 1, "개별 plan은 __ALL_PLANS__ sentinel과 격리돼야 함"

        # sentinel은 개별 plan 실행과 무관하게 count 유지
        id_s3 = wf.create("t3-sent-3", "ALL")
        _, sc3 = wf.mark_running_with_execution_count(
            id_s3, "runner-s3", "impl/all3", ".worktrees/impl-all3", "claude"
        )
        assert sc3 == 3
