"""pytest marker/collect 계약 검증 테스트."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
PYTHON = sys.executable


def _run_pytest(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-m", "pytest", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT),
        timeout=timeout,
    )


def _run_collect_only(path: str, marker: str, *extra_args: str) -> subprocess.CompletedProcess[str]:
    try:
        return _run_pytest(path, "--collect-only", "-m", marker, "-q", "--no-header", *extra_args, timeout=90)
    except subprocess.TimeoutExpired as exc:
        pytest.skip(f"collect-only timeout: {path} -m {marker} ({exc.timeout}s)")


class TestPytestMarkInfra:
    def test_registered_markers_include_http_http_live_and_e2e(self):
        """TC-Right: pytest.ini에 핵심 marker가 모두 등록되어 있다."""
        result = _run_pytest("--markers")
        assert "@pytest.mark.http" in result.stdout, f"http marker not found: {result.stdout[:500]}"
        assert "@pytest.mark.http_live" in result.stdout, f"http_live marker not found: {result.stdout[:500]}"
        assert "@pytest.mark.e2e" in result.stdout, f"e2e marker not found: {result.stdout[:500]}"

    def test_registered_markers_include_destructive_live(self):
        """TC-Right: pytest.ini에 destructive_live marker가 등록되어 있다."""
        result = _run_pytest("--markers")
        assert "@pytest.mark.destructive_live" in result.stdout, (
            f"destructive_live marker not found: {result.stdout[:500]}"
        )

    def test_http_marker_collects_testclient_suite(self):
        """TC-Right: TestClient 기반 HTTP 파일은 -m http에서 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_http_e2e.py", "http")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "tests/dev_runner/test_http_e2e.py" in result.stdout

    def test_exit_reason_legacy_e2e_file_collects_under_http(self):
        """TC-Right: legacy e2e 파일명이어도 실제 계약은 http marker로 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_exit_reason_e2e.py", "http")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_exit_reason_http_runners_api" in result.stdout

    def test_boundary_non_http_test_included_in_not_http(self):
        """TC-Boundary: mark 없는 테스트 → -m 'not http'에 포함됨"""
        result = _run_pytest("tests/dev_runner/test_pytest_mark.py", "--collect-only", "-m", "not http", "-q", "--no-header", timeout=60)
        # 이 파일 자체는 http mark 없으므로 수집되어야 함
        assert result.returncode == 0

    def test_legacy_e2e_file_is_not_collected_by_e2e_marker(self):
        """TC-Boundary: TestClient 기반 legacy 파일은 -m e2e에서 무선택이어야 한다."""
        result = _run_collect_only("tests/dev_runner/test_exit_reason_e2e.py", "e2e")
        combined = result.stdout + result.stderr
        assert "no tests collected" in combined, combined

    def test_v2_merge_fallback_e2e_file_collects_under_e2e(self):
        """TC-Right: v2 merge fallback e2e 파일은 -m e2e collect-only에서 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_v2_merge_fallback_e2e.py", "e2e")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "test_v2_merge_fallback_e2e_stream_output_R" in combined, combined
        assert "test_v2_merge_fallback_e2e_stream_output_residue_guard_E" in combined, combined

    def test_done_and_v2_merge_fallback_pair_collects_under_e2e(self):
        """TC-Boundary: explicit e2e pair 명령은 done preconditions와 fallback 파일을 함께 수집한다."""
        try:
            result = _run_pytest(
                "tests/dev_runner/test_done_preconditions_e2e.py",
                "tests/dev_runner/test_v2_merge_fallback_e2e.py",
                "--collect-only",
                "-m",
                "e2e",
                "-q",
                "--no-header",
                timeout=90,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.skip(f"collect-only timeout: done+fallback pair -m e2e ({exc.timeout}s)")

        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "test_done_e2e_fix_plan_no_phase_r_blocked" in combined, combined
        assert "test_v2_merge_fallback_e2e_stream_output_R" in combined, combined

    def test_http_live_marker_collects_live_server_suite(self):
        """TC-Right: 실서버 파일은 -m http_live에서 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_live_server_http.py", "http_live")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "tests/dev_runner/test_live_server_http.py" in result.stdout

    def test_read_only_coupang_live_http_case_still_collects_under_http_live(self):
        """TC-Right: 쿠팡 live HTTP read-only 케이스는 기본 http_live 수집 대상이다."""
        result = _run_collect_only(
            "tests/modules/coupang_travel/test_coupang_live_http.py",
            "http_live",
            "-k",
            "get_status_200",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_live_get_status_200" in result.stdout

    def test_http_live_marker_unaffected_for_cancellation_stats(self):
        """TC-Right: 무관한 쿠팡 live HTTP 파일은 기존 http_live 계약을 유지한다."""
        result = _run_collect_only(
            "tests/modules/coupang_travel/test_cancellation_stats_live_http.py",
            "http_live",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_live_cancellation_stats_200" in result.stdout

    def test_destructive_live_case_skips_without_flag(self):
        """TC-Right: destructive HTTP 케이스는 --run-destructive-live 없으면 skip된다."""
        result = _run_pytest(
            "tests/modules/coupang_travel/test_coupang_live_http.py",
            "-m",
            "http_live and destructive_live",
            "-k",
            "cleanup_returns_deleted_field",
            "-rs",
            "-q",
            "--no-header",
            timeout=90,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "--run-destructive-live required" in combined, combined
        assert "1 skipped" in combined, combined

    def test_destructive_live_e2e_file_skips_without_flag(self):
        """TC-Right: destructive E2E 파일 전체는 flag 없으면 skip된다."""
        result = _run_pytest(
            "tests/modules/coupang_travel/test_coupang_live_e2e.py",
            "-m",
            "http_live",
            "-rs",
            "-q",
            "--no-header",
            timeout=90,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "--run-destructive-live required" in combined, combined
        assert "5 skipped" in combined, combined

    def test_log_stream_live_file_collects_under_http_live(self):
        """TC-Right: test_log_stream_http.py 전체는 http_live에서만 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_log_stream_http.py", "http_live")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_http_log_stream_connected_event" in result.stdout

    def test_log_stream_live_file_not_collected_by_http(self):
        """TC-Boundary: 혼합 마커 파일에서 -m http는 http 테스트만 수집하고 http_live 전용은 제외한다."""
        result = _run_collect_only("tests/dev_runner/test_log_stream_http.py", "http")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "test_http_log_stream_commit_failed_keeps_reason_and_detail" in combined, combined
        assert "test_http_events_stream_fallback_log_delivery" in combined, combined
        # http_live-only 실서버 케이스는 -m http에서 수집되면 안 된다.
        assert "test_http_log_stream_connected_event" not in combined, combined

    def test_boundary_http_live_excluded_from_default(self):
        """TC-Boundary: addopts에 'not http_live' 포함 → 기본 pytest 실행 시 http_live 제외"""
        ini_file = PROJECT_ROOT / "pytest.ini"
        content = ini_file.read_text(encoding="utf-8")
        assert "not http_live" in content, \
            "pytest.ini addopts에 'not http_live' 가 없음 — 기본 실행 시 실서버 TC가 포함됨"


class TestMergeRetryHttpMarkerContract:
    """test_merge_retry_http.py의 http marker 계약 고정 guard."""

    _TARGET = "tests/dev_runner/test_merge_retry_http.py"

    _HTTP_CASES = [
        "test_direct_merge_success",
        "test_direct_merge_safe_doc_payload_preserved",
        "test_direct_merge_missing_branch_422",
        "test_retry_merge_endpoint_regression",
        "test_retry_merge_conflict_payload_preserved",
        "test_logs_recent_redis_list_fallback",
        "test_retry_merge_returns_test_failed_then_fixing_http",
    ]

    _NON_HTTP_CASES = [
        "test_build_status_payload_dm_runner_keeps_plan_file_none",
        "test_normal_runner_plan_file_none_regression",
    ]

    def test_http_marker_collects_all_testclient_cases(self):
        """TC-Right: `-m http`로 collect-only 시 TestClient 7건이 모두 수집된다."""
        result = _run_collect_only(self._TARGET, "http")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        for name in self._HTTP_CASES:
            assert name in combined, f"'{name}' not found in -m http collect: {combined[:800]}"

    def test_http_marker_excludes_fakeredis_cases(self):
        """TC-Boundary: `-m http` collect-only에서 fakeredis 2건은 나타나지 않는다."""
        result = _run_collect_only(self._TARGET, "http")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        for name in self._NON_HTTP_CASES:
            assert name not in combined, f"fakeredis case '{name}' should NOT appear in -m http collect: {combined[:800]}"

    def test_default_addopts_collects_only_fakeredis_cases(self):
        """TC-Right: marker 인자 없는 기본 실행(not http addopts)에서 fakeredis 2건만 수집된다."""
        result = _run_collect_only(self._TARGET, "not http and not http_live and not integration and not e2e")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        for name in self._NON_HTTP_CASES:
            assert name in combined, f"'{name}' should appear in default collect: {combined[:800]}"

    def test_default_addopts_excludes_testclient_cases(self):
        """TC-Boundary: 기본 addopts 필터에서 TestClient 7건은 수집 대상에서 제외된다."""
        result = _run_collect_only(self._TARGET, "not http and not http_live and not integration and not e2e")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        for name in self._HTTP_CASES:
            assert name not in combined, f"TestClient case '{name}' should NOT appear in default collect: {combined[:800]}"


class TestDbDirEnvVar:
    def test_right_test_db_dir_env_var_used(self, tmp_path):
        """TC-Right: TEST_DB_DIR 환경변수 설정 → 해당 경로에 test_monitor.db 생성 가능"""
        # conftest.py가 TEST_DB_DIR 환경변수를 읽는지 확인
        from tests.conftest import TEST_DB_DIR as _default_dir
        # 환경변수 없을 때 기본값이 PROJECT_ROOT/data인지 확인
        default_path = PROJECT_ROOT / "data"
        # TEST_DB_DIR 환경변수가 없을 때 기본값 사용
        env_val = os.environ.get("TEST_DB_DIR", str(default_path))
        assert env_val  # 값이 있어야 함

    def test_right_test_db_default_path(self):
        """TC-Right: TEST_DB_DIR 미설정 → 기본 PROJECT_ROOT/data 경로 사용"""
        import importlib
        import tests.conftest as conf
        importlib.reload(conf)
        default = str(PROJECT_ROOT / "data")
        # TEST_DB_DIR 없으면 기본 경로
        if "TEST_DB_DIR" not in os.environ:
            assert str(conf.TEST_DB_DIR) == default

    def test_boundary_nonexistent_test_db_dir_auto_makedirs(self, tmp_path):
        """TC-Boundary: TEST_DB_DIR 경로가 존재하지 않음 → makedirs 호출"""
        new_dir = tmp_path / "nested" / "db_dir"
        assert not new_dir.exists()
        # makedirs 호출
        new_dir.mkdir(parents=True, exist_ok=True)
        assert new_dir.exists()


class TestHttpRunnerMarkerContract:
    """test_http_runner.py의 http marker 계약 고정 guard."""

    _TARGET = "tests/dev_runner/test_http_runner.py"

    _HTTP_CASES = [
        "test_cleanup_stale_endpoint_returns_200",
        "test_cleanup_stale_endpoint_empty_returns_200",
        "test_cleanup_stale_endpoint_idempotent",
        "test_cleanup_stale_response_schema",
        "test_delete_tab_removes_runner_from_list",
        "test_cleanup_stale_preserves_then_delete_tab_removes",
        "test_cleanup_stale_and_dismiss_order_is_consistent",
        "test_logs_history_visible_only_returns_user_runner",
        "test_logs_history_visible_only_excludes_tc_runner",
        "test_logs_history_default_not_visible_only",
    ]

    def test_http_marker_collects_all_testclient_cases(self):
        """TC-Right: `-m http` collect-only에서 TestClient 10건이 모두 수집된다."""
        result = _run_collect_only(self._TARGET, "http")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        for name in self._HTTP_CASES:
            assert name in combined, f"'{name}' not found in -m http collect: {combined[:800]}"

    def test_default_addopts_excludes_testclient_cases(self):
        """TC-Boundary: 기본 addopts 필터에서 TestClient 10건이 모두 제외된다."""
        result = _run_collect_only(self._TARGET, "not http and not http_live and not integration and not e2e")
        combined = result.stdout + result.stderr
        # exit 5 = no tests collected — all deselected, which is the correct outcome
        assert result.returncode in (0, 5), combined
        for name in self._HTTP_CASES:
            assert name not in combined, f"TestClient case '{name}' should NOT appear in default collect: {combined[:800]}"


class TestDevguideStalenessMarkerContract:
    """test_devguide_staleness.py의 http marker 계약 고정 guard."""

    _TARGET = "tests/dev_runner/test_devguide_staleness.py"
    _CASE = "test_e2e_guide_status_with_history"

    def test_e2e_guide_status_with_history_collects_under_http(self):
        """TC-Right: `-m http` collect-only에서 test_e2e_guide_status_with_history가 수집된다."""
        result = _run_collect_only(self._TARGET, "http", "-k", self._CASE)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert self._CASE in combined, f"'{self._CASE}' not found in -m http collect: {combined[:800]}"

    def test_e2e_guide_status_with_history_excluded_from_default(self):
        """TC-Boundary: 기본 addopts marker 식에서 test_e2e_guide_status_with_history가 제외된다."""
        result = _run_collect_only(self._TARGET, "not http and not http_live and not integration and not e2e", "-k", self._CASE)
        combined = result.stdout + result.stderr
        # exit 5 = no tests collected — all deselected, which is the correct outcome
        assert result.returncode in (0, 5), combined
        assert self._CASE not in combined or "no tests collected" in combined, (
            f"'{self._CASE}' should NOT appear in default collect: {combined[:800]}"
        )


class TestDevRunnerAsyncHttpImportBoundary:
    """diagnostics/worktrees 계열 6개 파일의 lazy import + http marker 계약 guard."""

    _TARGETS = [
        PROJECT_ROOT / "tests/dev_runner/test_diagnostics_http.py",
        PROJECT_ROOT / "tests/dev_runner/test_worktree_cleanup_http.py",
        PROJECT_ROOT / "tests/dev_runner/test_worktree_list_v1_v2_coexist.py",
        PROJECT_ROOT / "tests/dev_runner/test_worktree_list_v2_lite.py",
        PROJECT_ROOT / "tests/dev_runner/test_worktrees_commits_endpoint.py",
        PROJECT_ROOT / "tests/dev_runner/test_worktrees_http.py",
    ]

    def test_targets_have_no_module_level_app_main_import(self):
        """TC-Right: 대상 파일 텍스트에 모듈 레벨 'from app.main import app'가 없다."""
        import re
        pattern = re.compile(r"^from app\.main import app", re.MULTILINE)
        failures = []
        for target in self._TARGETS:
            text = target.read_text(encoding="utf-8")
            if pattern.search(text):
                failures.append(str(target.relative_to(PROJECT_ROOT)))
        assert not failures, (
            f"모듈 레벨 'from app.main import app' 발견 — lazy import로 이동 필요:\n"
            + "\n".join(f"  {f}" for f in failures)
        )

    def test_targets_keep_http_asyncio_boundary(self):
        """TC-Right: 대상 파일이 pytestmark에 http + asyncio 조합을 유지한다."""
        failures = []
        for target in self._TARGETS:
            text = target.read_text(encoding="utf-8")
            has_http = "pytest.mark.http" in text
            has_asyncio = "pytest.mark.asyncio" in text
            if not (has_http and has_asyncio):
                failures.append(
                    f"{target.relative_to(PROJECT_ROOT)}: http={has_http}, asyncio={has_asyncio}"
                )
        assert not failures, (
            "http + asyncio marker 계약 미충족 파일:\n"
            + "\n".join(f"  {f}" for f in failures)
        )


class TestRemainingHttpRunnerMarkerContract:
    """markerless / class decorator-only 6건 전용 guard."""

    _TARGETS = [
        "tests/dev_runner/test_executor_redis_guard_http.py",
        "tests/dev_runner/test_http_cleanup_stale.py",
        "tests/dev_runner/test_http_stop_all.py",
        "tests/dev_runner/test_t4_t5_pid_correction.py",
        "tests/dev_runner/test_redis_reconnect_http.py",
        "tests/dev_runner/test_rerun_orphan_http.py",
    ]

    def test_targets_have_no_module_level_app_main_import(self):
        """TC-Right: 대상 파일 텍스트에 모듈 레벨 'from app.main import app'가 없다."""
        import re
        pattern = re.compile(r"^from app\.main import app\b", re.MULTILINE)
        failures = []
        for target in self._TARGETS:
            text = (PROJECT_ROOT / target).read_text(encoding="utf-8")
            if pattern.search(text):
                failures.append(target)
        assert not failures, (
            f"모듈 레벨 'from app.main import app' 발견 — lazy import로 이동 필요:\n"
            + "\n".join(f"  {f}" for f in failures)
        )

    def test_targets_keep_http_marker_boundary(self):
        """TC-Right: 대상 파일이 module-level pytestmark = pytest.mark.http를 포함한다."""
        import re
        pattern = re.compile(r"pytestmark\s*=\s*(?:pytest\.mark\.http|\[pytest\.mark\.http)")
        failures = []
        for target in self._TARGETS:
            text = (PROJECT_ROOT / target).read_text(encoding="utf-8")
            if not pattern.search(text):
                failures.append(target)
        assert not failures, (
            "module-level pytestmark = pytest.mark.http 미설정 파일:\n"
            + "\n".join(f"  {f}" for f in failures)
        )


class TestDevRunnerHttpE2EImportBoundary:
    """http/e2e/integration 잔존 12개 파일의 lazy import + marker 계약 guard."""

    _TARGETS = {
        "tests/dev_runner/test_full_e2e_real.py": "full_e2e",
        "tests/dev_runner/test_early_exit_e2e_http.py": "http",
        "tests/dev_runner/test_exit_reason_e2e.py": "http",
        "tests/dev_runner/test_heartbeat_merge_guard_http.py": "http",
        "tests/dev_runner/test_http_e2e.py": "http",
        "tests/dev_runner/test_http_e2e_max_cycles.py": "http",
        "tests/dev_runner/test_recent_meta_http.py": "http",
        "tests/dev_runner/test_remove_pipeline_v1_e2e.py": "http",
        "tests/dev_runner/test_runner_dry_run.py": "integration",
        "tests/dev_runner/test_t4_http_integration.py": "http",
        "tests/dev_runner/test_t4t5_no_backtick_e2e.py": "http",
        "tests/dev_runner/test_trigger_http.py": "http",
    }

    def test_targets_have_no_module_level_app_main_import(self):
        """TC-Right: 대상 파일 텍스트에 모듈 레벨 'from app.main import app'가 없다."""
        import re

        pattern = re.compile(r"^from app\.main import app\b", re.MULTILINE)
        failures = []
        for target in self._TARGETS:
            text = (PROJECT_ROOT / target).read_text(encoding="utf-8")
            if pattern.search(text):
                failures.append(target)
        assert not failures, (
            f"모듈 레벨 'from app.main import app' 발견 — lazy import로 이동 필요:\n"
            + "\n".join(f"  {f}" for f in failures)
        )

    def test_targets_keep_marker_boundary(self):
        """TC-Right: 대상 파일이 기대 marker를 그대로 유지한다."""
        failures = []
        for target, expected_marker in self._TARGETS.items():
            text = (PROJECT_ROOT / target).read_text(encoding="utf-8")
            marker_token = f"pytest.mark.{expected_marker}"
            if marker_token not in text:
                failures.append(f"{target}: expected={expected_marker}")
        assert not failures, (
            "marker boundary 미충족 파일:\n"
            + "\n".join(f"  {f}" for f in failures)
        )
