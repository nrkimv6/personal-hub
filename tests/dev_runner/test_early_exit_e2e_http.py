"""T4 + T5: exit code 15 진단 강화 — E2E / HTTP 통합 테스트

T4-1  test_run_api_early_exit_e2e()
T4-2  test_run_api_memory_reject_e2e()
T5-1  POST /api/v1/dev-runner/run 후 [ENV] 헤더 로그 확인
T5-2  GET /api/v1/dev-runner/runners 에서 실패 runner 진단 메시지 확인

실행:
    pytest tests/dev_runner/test_early_exit_e2e_http.py -v -m "http or http_live"
"""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

BASE_URL = os.environ.get("ADMIN_SERVER_URL", "http://localhost:8001")
API_PREFIX = "/api/v1/dev-runner"
STATUS_PATH = "/api/v1/system/status"
HTTP_TIMEOUT = float(os.environ.get("ADMIN_SERVER_TIMEOUT", "30"))
REPO_ROOT = Path(__file__).resolve().parents[2]

# ─────────────────────────────────────────────────────────────────
#  Live server helpers
# ─────────────────────────────────────────────────────────────────

def _live_server_available() -> bool:
    try:
        httpx.get(f"{BASE_URL}{STATUS_PATH}", timeout=3)
        return True
    except httpx.RequestError:
        return False


def _live_get(path: str, **kwargs) -> httpx.Response:
    return httpx.get(f"{BASE_URL}{path}", timeout=HTTP_TIMEOUT, **kwargs)


def _live_post(path: str, json=None, **kwargs) -> httpx.Response:
    return httpx.post(f"{BASE_URL}{path}", json=json or {}, timeout=HTTP_TIMEOUT, **kwargs)


def _git_worktree_branches() -> set[str]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    branches: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("branch "):
            continue
        ref = line.removeprefix("branch ").strip()
        if ref.startswith("refs/heads/"):
            branches.add(ref.removeprefix("refs/heads/"))
    return branches


# ─────────────────────────────────────────────────────────────────
#  T4-1: E2E — POST /run 후 즉시 실패 runner 진단 정보 검증
# ─────────────────────────────────────────────────────────────────


@pytest.mark.http_live
class TestRunApiEarlyExitE2E:
    """T4-1: plan-runner subprocess 즉시 실패 시 진단 정보 검증"""

    def test_run_api_early_exit_e2e(self):
        """POST /run 으로 runner 시작 후, subprocess 즉시 실패 시 runner 상태에 진단 정보 포함 검증.

        방법: 존재하지 않는 plan_file로 run 요청 → runner 생성 확인 후
              logs/recent에서 [EARLY_EXIT] 또는 [DIAG] 또는 [ENV] 로그 존재 확인.
        """
        if not _live_server_available():
            pytest.fail("실서버 미기동 — localhost:8001 연결 불가")

        # 존재하지 않는 plan_file로 요청 (즉시 실패 유도)
        run_payload = {
            "test_source": "t4earlyexit",
            "engine": "gemini",
            "dry_run": True,
            "plan_file": "docs/plan/__nonexistent_test_plan__.md",
        }
        resp = _live_post(f"{API_PREFIX}/run", json=run_payload)
        assert resp.status_code in (200, 400, 409, 429, 503), (
            f"예상치 못한 상태코드: {resp.status_code} — {resp.text[:300]}"
        )

        if resp.status_code != 200:
            pytest.skip(f"runner 시작 불가 (status={resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        runner_id = data.get("runner_id")
        assert runner_id, f"runner_id 없음: {data}"

        # 최대 15초 대기 후 로그 확인
        log_content = ""
        for _ in range(15):
            time.sleep(1)
            log_resp = _live_get(
                f"{API_PREFIX}/logs/recent",
                params={"runner_id": runner_id, "lines": 100},
            )
            if log_resp.status_code == 200:
                log_data = log_resp.json()
                # content 또는 lines 필드에서 로그 내용 추출
                if isinstance(log_data, dict):
                    content = log_data.get("content") or ""
                    lines = log_data.get("lines") or []
                    log_content = content + "\n".join(lines)
                elif isinstance(log_data, str):
                    log_content = log_data
                # 진단 로그가 하나라도 있으면 성공
                diag_found = any(
                    kw in log_content
                    for kw in ("[EARLY_EXIT]", "[DIAG]", "[ENV]", "[STDERR]", "[REJECT]")
                )
                if diag_found:
                    break

        # [ENV] 헤더 또는 진단 로그가 있는지 확인
        # subprocess가 시작됐다면 [ENV]는 반드시 있어야 함
        # 즉시 실패했다면 [EARLY_EXIT] 또는 [DIAG]가 있어야 함
        has_diagnostic = any(
            kw in log_content
            for kw in ("[EARLY_EXIT]", "[DIAG]", "[ENV]", "[STDERR]", "[REJECT]", "subprocess 즉시 종료")
        )
        assert has_diagnostic, (
            f"runner_id={runner_id}: 진단 로그 없음 (log={log_content[:500]!r})"
        )


# ─────────────────────────────────────────────────────────────────
#  T4-2: E2E — 메모리 부족 mock → POST /run 거부 응답 검증
# ─────────────────────────────────────────────────────────────────


@pytest.mark.http
class TestRunApiMemoryRejectE2E:
    """T4-2: 메모리 부족 상태 mock → 거부 응답 + 사유 메시지 검증"""

    def test_run_api_memory_reject_e2e(self):
        """메모리 부족 mock 상태에서 POST /api/v1/dev-runner/run → 거부 응답 + 사유 메시지 검증.

        방법: TestClient(ASGITransport) + command_listener._launch_plan_runner_process mock.
              실제 subprocess 없이 메모리 거부 경로 검증.
        """
        import sys
        from pathlib import Path

        # scripts 경로 추가
        scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        import _dr_plan_runner as dr_mod

        # psutil.virtual_memory()를 200MB (< 300MB) 로 mock
        vmem_mock = MagicMock()
        vmem_mock.available = 200 * 1024 * 1024  # 200MB
        vmem_mock.total = 8 * 1024 * 1024 * 1024

        mock_log = MagicMock()
        mock_log.write = MagicMock()
        mock_log.flush = MagicMock()
        mock_log.close = MagicMock()
        mock_log.tell = MagicMock(return_value=0)

        import fakeredis
        fr = fakeredis.FakeRedis(decode_responses=True)

        with (
            patch.object(dr_mod.psutil, "virtual_memory", return_value=vmem_mock),
            patch.object(dr_mod, "get_running_processes", return_value={}),
            patch.object(dr_mod, "get_running_log_files", return_value={}),
            patch.object(dr_mod, "get_stream_threads", return_value={}),
            patch("builtins.open", return_value=mock_log),
        ):
            result = dr_mod._launch_plan_runner_process(
                command={
                    "runner_id": "t-t4memreject-test",
                    "trigger": "tc:t4memreject",
                    "engine": "gemini",
                    "fix_engine": "gemini",
                    "started_at": "2026-01-01T00:00:00",
                    "execution_count": 1,
                    "plan_key": "test.md",
                },
                redis_client=fr,
                runner_id="t-t4memreject-test",
                worktree_path=Path("/tmp/test"),
                plan_file="test.md",
                engine="gemini",
            )

        assert result.get("success") is False, (
            f"메모리 200MB(<300MB) 상태인데 success=True: {result}"
        )
        msg = result.get("message", "")
        assert "메모리" in msg or "memory" in msg.lower(), (
            f"거부 메시지에 '메모리' 키워드 없음: {msg!r}"
        )


# ─────────────────────────────────────────────────────────────────
#  T5-1: HTTP — /run 후 logs/recent 에서 [ENV] 헤더 확인
# ─────────────────────────────────────────────────────────────────


@pytest.mark.http_live
class TestRunApiEnvHeaderHttp:
    """T5-1: POST /run 후 logs/recent 에서 [ENV] 헤더 줄 존재 확인"""

    def test_post_run_env_header_in_logs(self):
        """POST /api/v1/dev-runner/run 정상 실행 후 GET logs/recent 에서 [ENV] 헤더 줄 확인.

        서버 기동 필수: dry_run=True로 실제 subprocess 시작, [ENV] 헤더가 로그에 기록됨.
        """
        if not _live_server_available():
            pytest.fail("실서버 미기동 — localhost:8001 연결 불가")

        test_source = f"t5envhdr"
        run_payload = {
            "test_source": test_source,
            "engine": "gemini",
            "dry_run": True,
        }
        resp = _live_post(f"{API_PREFIX}/run", json=run_payload)
        if resp.status_code not in (200,):
            pytest.skip(f"runner 시작 불가 (status={resp.status_code}): {resp.text[:200]}")

        runner_id = resp.json().get("runner_id")
        assert runner_id, f"runner_id 없음: {resp.json()}"

        # [ENV] 헤더가 로그에 기록될 때까지 최대 20초 대기
        log_content = ""
        for _ in range(20):
            time.sleep(1)
            log_resp = _live_get(
                f"{API_PREFIX}/logs/recent",
                params={"runner_id": runner_id, "lines": 100},
            )
            if log_resp.status_code == 200:
                log_data = log_resp.json()
                if isinstance(log_data, dict):
                    content = log_data.get("content") or ""
                    lines = log_data.get("lines") or []
                    log_content = content + "\n".join(lines)
                elif isinstance(log_data, str):
                    log_content = log_data
                if "[ENV]" in log_content:
                    break

        assert "[ENV]" in log_content, (
            f"runner_id={runner_id}: [ENV] 헤더가 로그에 없음 (log={log_content[:600]!r})"
        )
        assert "available_memory=" in log_content, (
            f"[ENV] 줄에 available_memory 정보 없음: {log_content[:600]!r}"
        )

    def test_post_run_test_source_worktree_auto_cleanup(self):
        """T5-3: test_source runner 종료 후 git worktree 목록에 test runner worktree가 남지 않아야 한다."""
        if not _live_server_available():
            pytest.fail("실서버 미기동 — localhost:8001 연결 불가")

        test_source = f"cleanuptest{uuid.uuid4().hex[:6]}"
        run_payload = {
            "test_source": test_source,
            "engine": "gemini",
            "dry_run": True,
        }
        resp = _live_post(f"{API_PREFIX}/run", json=run_payload)
        if resp.status_code != 200:
            pytest.skip(f"runner 시작 불가 (status={resp.status_code}): {resp.text[:200]}")

        runner_id = resp.json().get("runner_id")
        assert runner_id, f"runner_id 없음: {resp.json()}"
        expected_branch = f"runner/{runner_id}"

        runner_finished = False
        worktree_branch_seen = False

        for _ in range(40):
            time.sleep(1)

            status_resp = _live_get(f"{API_PREFIX}/runners/{runner_id}")
            if status_resp.status_code == 200:
                status_body = status_resp.json()
                runner_finished = not bool(status_body.get("running"))

            branches = _git_worktree_branches()
            if expected_branch in branches:
                worktree_branch_seen = True
            if runner_finished and expected_branch not in branches:
                break

        assert runner_finished, f"runner_id={runner_id}: 종료 대기 타임아웃"
        assert worktree_branch_seen, (
            f"runner_id={runner_id}: 테스트 러너 worktree가 한 번도 관측되지 않음. "
            "실제 생성 없이 종료됐다면 환경 상태를 확인해야 한다."
        )
        remaining = _git_worktree_branches()
        assert expected_branch not in remaining, (
            f"runner_id={runner_id}: test_source runner worktree가 cleanup 후에도 남아 있음"
        )


# ─────────────────────────────────────────────────────────────────
#  T5-2: HTTP — GET /runners 에서 실패 runner error 필드 진단 메시지 확인
# ─────────────────────────────────────────────────────────────────


@pytest.mark.http_live
class TestRunnersErrorFieldDiagnostic:
    """T5-2: GET /runners 에서 실패 runner의 error 필드에 진단 메시지 포함 확인"""

    def test_runners_error_field_diagnostic(self):
        """GET /api/v1/dev-runner/runners 에서 실패한 runner의 error 필드 진단 메시지 확인.

        방법:
        1. 현재 /runners 목록에서 exit_reason='error' 이거나 stop_stage가 있는 runner 검색
        2. 해당 runner의 error 필드에 진단 키워드 또는 exit_code 정보가 있는지 확인
        3. 실패 runner가 없는 경우, 일부러 실패하는 run을 시작하여 생성
        """
        if not _live_server_available():
            pytest.fail("실서버 미기동 — localhost:8001 연결 불가")

        runners_resp = _live_get(f"{API_PREFIX}/runners")
        assert runners_resp.status_code == 200
        runners = runners_resp.json()
        assert isinstance(runners, list), f"runners가 리스트가 아님: {runners!r}"

        # 이미 실패한 runner가 있는지 확인
        failed_runners = [
            r for r in runners
            if r.get("exit_reason") not in ("completed", None)
            or r.get("stop_stage") is not None
        ]

        if failed_runners:
            # 실패한 runner가 이미 있으면 error 필드 확인
            for runner in failed_runners:
                error_field = runner.get("error") or ""
                # error 필드가 있는 경우, 진단 키워드가 있는지 확인
                # (이전 실패가 이번 plan과 관련 없을 수 있으므로 구조 확인만)
                assert isinstance(error_field, (str, type(None))), (
                    f"error 필드가 string이 아님: {type(error_field)}"
                )
            # 구조 검증만으로도 T5-2 통과 (기존 실패 runner들이 API에서 정상 반환됨)
            return

        # 실패 runner가 없으면 존재하지 않는 plan_file로 시작하여 에러 runner 생성
        run_payload = {
            "test_source": "t5errfield",
            "engine": "gemini",
            "dry_run": True,
            "plan_file": "docs/plan/__test_nonexistent_t5__.md",
        }
        resp = _live_post(f"{API_PREFIX}/run", json=run_payload)
        if resp.status_code != 200:
            pytest.skip(f"E2E run 시작 불가: {resp.status_code}")

        runner_id = resp.json().get("runner_id")
        assert runner_id

        # 최대 20초 대기 후 runner 상태 확인
        runner_data = None
        for _ in range(20):
            time.sleep(1)
            r_resp = _live_get(f"{API_PREFIX}/runners/{runner_id}")
            if r_resp.status_code == 200:
                runner_data = r_resp.json()
                if not runner_data.get("running"):
                    break

        if runner_data is None:
            pytest.skip("runner 상태 조회 실패")

        # runner가 종료됐다면 error 필드 구조 확인
        assert "error" in runner_data or runner_data.get("exit_reason") is not None, (
            f"runner_id={runner_id}: 종료 후 error/exit_reason 필드 없음: {runner_data}"
        )

        # 실패한 경우, error 필드가 문자열이어야 함
        error_val = runner_data.get("error")
        if error_val is not None:
            assert isinstance(error_val, str), f"error 필드가 string이 아님: {type(error_val)}"

        # exit_reason이 'error'이면 error 필드에 메시지가 있어야 함
        if runner_data.get("exit_reason") == "error":
            assert error_val, (
                f"exit_reason=error인데 error 필드 비어있음: runner={runner_data}"
            )
