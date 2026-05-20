"""event_payload 단위 테스트

build_status_payload, build_all_runners_status, build_tracking_payload,
TestBuildAllRunnersStatusRecentInclusion 검증.
fakeredis 주입 단위 테스트 — conftest의 sync_redis, event_service fixture 사용.
"""

import time
import pytest

from app.modules.dev_runner.services import visibility
from app.modules.dev_runner.services.event_payload import (
    build_status_payload,
    build_all_runners_status,
    build_tracking_payload,
)
from app.modules.dev_runner.services.event_routing import (
    RUNNER_KEY_PREFIX,
    REDIS_STATE_KEY,
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    PLAN_FILE_ALL,
)


# ─── TestBuildStatusPayload ──────────────────────────────────────────────────

class TestBuildStatusPayload:
    def test_returns_dict_with_runner_id(self, event_service, sync_redis):
        runner_id = "test01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", "12345")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:current_cycle", "3")

        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["runner_id"] == runner_id
        assert payload["status"] == "running"
        assert payload["pid"] == "12345"
        assert payload["current_cycle"] == "3"

    def test_missing_fields_return_none_values(self, event_service):
        payload = build_status_payload(event_service._sync, "nonexistent")
        assert payload is not None
        assert payload["status"] is None
        assert payload["pid"] is None

    def test_build_status_payload_stopped_runner_plan_file_none_returns_none(self, event_service, sync_redis):
        """R: status=stopped + plan_file 키 없음 → plan_file is None (sentinel 아님)"""
        runner_id = "stopped01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_running_runner_plan_file_none_returns_none(self, event_service, sync_redis):
        """R: status=running + plan_file 키 없음 → None 반환 (sentinel fallback 제거)"""
        runner_id = "running01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_running_with_explicit_sentinel(self, event_service, sync_redis):
        """R: plan_file에 __ALL_PLANS__ 명시 → 그대로 전달"""
        runner_id = "running01b"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", PLAN_FILE_ALL)
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] == PLAN_FILE_ALL

    def test_build_status_payload_plan_file_empty_string_returns_none(self, event_service, sync_redis):
        """B: plan_file="" (falsy) → None 반환"""
        runner_id = "running01c"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "")
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_running_runner_plan_file_set_returns_value(self, event_service, sync_redis):
        """R: status=running + plan_file 정상값 → 그대로 반환"""
        runner_id = "running02"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "feature-x.md")
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] == "feature-x.md"

    def test_build_status_payload_stopped_runner_branch_set_still_none(self, event_service, sync_redis):
        """B: status=stopped + branch 있음 + plan_file 없음 → plan_file is None"""
        runner_id = "stopped02"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "impl/some-feature")
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] is None

    def test_build_status_payload_includes_trigger_field(self, event_service, sync_redis):
        """R: trigger 키 있는 runner → payload에 trigger 필드 포함"""
        runner_id = "triggered01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "manual")
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["trigger"] == "manual"

    def test_build_status_payload_trigger_none_when_key_missing(self, event_service, sync_redis):
        """B: trigger Redis 키 없음 → payload["trigger"] is None"""
        runner_id = "triggered02"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["trigger"] is None

    def test_build_status_payload_includes_stale_metadata_fields(self, event_service, sync_redis):
        """R: plan-runner snapshot stale metadata를 SSE payload에 포함한다."""
        runner_id = "metadata01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_exists", "false")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch_exists", "true")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch_merged_to_main", "true")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:metadata_checked_at", "2026-05-05T21:35:00")

        payload = build_status_payload(event_service._sync, runner_id)

        assert payload is not None
        assert payload["worktree_exists"] is False
        assert payload["branch_exists"] is True
        assert payload["branch_merged_to_main"] is True
        assert payload["metadata_checked_at"] == "2026-05-05T21:35:00"

    def test_build_status_payload_metadata_defaults_unknown(self, event_service, sync_redis):
        """B: snapshot stale metadata가 없는 구버전 runner는 unknown으로 보낸다."""
        runner_id = "metadata02"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")

        payload = build_status_payload(event_service._sync, runner_id)

        assert payload is not None
        assert payload["worktree_exists"] == "unknown"
        assert payload["branch_exists"] == "unknown"
        assert payload["branch_merged_to_main"] == "unknown"
        assert payload["metadata_checked_at"] == "unknown"

    def test_build_status_payload_includes_visible_field(self, event_service, sync_redis, tmp_path, monkeypatch):
        """R: trigger=user + 실제 plan evidence면 visible=True, trigger=api면 visible=False."""
        plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        plans_dir.mkdir(parents=True)
        plan_name = "2026-05-20_real-user-plan.md"
        (plans_dir / plan_name).write_text("# real\n", encoding="utf-8")
        monkeypatch.setattr(visibility, "_project_root", lambda: tmp_path)

        rid_user = "visible-user-01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{rid_user}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{rid_user}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{rid_user}:plan_file", f"docs/plan/{plan_name}")
        payload_user = build_status_payload(event_service._sync, rid_user)
        assert payload_user is not None
        assert payload_user["visible"] is True

        rid_api = "visible-api-01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{rid_api}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{rid_api}:trigger", "api")
        payload_api = build_status_payload(event_service._sync, rid_api)
        assert payload_api is not None
        assert payload_api["visible"] is False

    def test_build_status_payload_includes_exit_reason_and_error(self, event_service, sync_redis):
        """R: exit_reason/error 저장 시 status payload에 그대로 포함."""
        runner_id = "failed01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", "Process exited with code 15")

        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["exit_reason"] == "error"
        assert payload["error"] == "Process exited with code 15"

    def test_build_status_payload_includes_commit_failed_detail(self, event_service, sync_redis):
        """R: commit_failed error/detail pair는 status payload에 그대로 포함."""
        runner_id = "failed02"
        detail = "exit_code=0; exit_reason=commit_failed; detail=commit_scope=docs/plan/test.md"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "commit_failed")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", detail)

        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["exit_reason"] == "commit_failed"
        assert payload["error"] == detail

    def test_build_status_payload_includes_merge_recovery_fields(self, event_service, sync_redis):
        """R: merge 복구용 필드가 status payload에 포함된다."""
        runner_id = "merge01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", "/tmp/wt/merge01")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason", "service_lock")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_message", "MERGE_PRECHECK_FAILED[service_lock]: blocked")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage", "post_review")

        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["worktree_path"] == "/tmp/wt/merge01"
        assert payload["merge_status"] == "merged"
        assert payload["merge_reason"] == "service_lock"
        assert "MERGE_PRECHECK_FAILED" in (payload.get("merge_message") or "")
        assert payload["stop_stage"] == "post_review"
        assert payload["display_state"] == "merged"
        assert payload["display_label"] == "머지됨"

    def test_build_status_payload_includes_display_state_for_approval_required(self, event_service, sync_redis):
        """R: SSE payload도 backend display state와 stale badge policy를 포함한다."""
        runner_id = "approval-display-01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "approval_required")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch_exists", "false")

        payload = build_status_payload(event_service._sync, runner_id)

        assert payload is not None
        assert payload["display_state"] == "approval_required"
        assert payload["display_label"] == "승인 필요"
        assert payload["display_severity"] == "approval"
        assert payload["display_secondary"] is None
        assert payload["hide_stale_branch_badge"] is True

    def test_build_status_payload_plan_file_none_when_key_missing(self, event_service, sync_redis):
        """R: trigger="user" + plan_file 키 미설정 → payload["plan_file"] is None, != PLAN_FILE_ALL"""
        runner_id = "user-pf-none-01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")

        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] is None
        assert payload["plan_file"] != PLAN_FILE_ALL

    def test_build_status_payload_plan_file_sentinel_preserved(self, event_service, sync_redis):
        """R: trigger="user:all" + plan_file=PLAN_FILE_ALL 명시 → 그대로 반환"""
        runner_id = "userall-sentinel-01"
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user:all")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", PLAN_FILE_ALL)

        payload = build_status_payload(event_service._sync, runner_id)
        assert payload is not None
        assert payload["plan_file"] == PLAN_FILE_ALL


# ─── TestBuildAllRunnersStatus ────────────────────────────────────────────────

class TestBuildAllRunnersStatus:
    def _real_plan_file(self, tmp_path, monkeypatch, name: str = "2026-05-20_real-user-plan.md") -> str:
        plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / name).write_text("# real\n", encoding="utf-8")
        monkeypatch.setattr(visibility, "_project_root", lambda: tmp_path)
        return f"docs/plan/{name}"

    def _register_runner(
        self,
        redis,
        runner_id: str,
        trigger: str | None = None,
        status: str = "running",
        plan_file: str | None = None,
    ):
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", status)
        if trigger is not None:
            redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)
        if plan_file is not None:
            redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
        redis.sadd("plan-runner:active_runners", runner_id)

    def test_build_all_runners_excludes_tc_trigger(self, event_service, sync_redis):
        """R: trigger="tc:test" runner 등록 → build_all_runners_status() 결과에 미포함"""
        self._register_runner(sync_redis, "tc_runner01", trigger="tc:test")
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "tc_runner01" not in ids

    def test_build_all_runners_includes_normal_trigger(self, event_service, sync_redis):
        """R: trigger="manual" runner → 화이트리스트에 없으므로 결과에 미포함"""
        self._register_runner(sync_redis, "manual_runner01", trigger="manual")
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "manual_runner01" not in ids

    def test_build_all_runners_includes_trigger_none(self, event_service, sync_redis):
        """B: trigger 키 없음(None) → 화이트리스트에 없으므로 미포함"""
        self._register_runner(sync_redis, "notrigger_runner01", trigger=None)
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "notrigger_runner01" not in ids

    def test_build_all_runners_includes_trigger_empty(self, event_service, sync_redis):
        """B: trigger="" → 화이트리스트에 없으므로 미포함"""
        self._register_runner(sync_redis, "emptytrigger_runner01", trigger="")
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "emptytrigger_runner01" not in ids

    def test_build_all_runners_includes_user_trigger(self, event_service, sync_redis, tmp_path, monkeypatch):
        """R: trigger="user" + 실제 plan evidence runner → 결과에 포함"""
        self._register_runner(
            sync_redis,
            "user_runner01",
            trigger="user",
            plan_file=self._real_plan_file(tmp_path, monkeypatch),
        )
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "user_runner01" in ids

    def test_build_all_runners_includes_user_all_trigger(self, event_service, sync_redis, tmp_path, monkeypatch):
        """R: trigger="user:all" + 실제 plan evidence runner → 결과에 포함"""
        self._register_runner(
            sync_redis,
            "userall_runner01",
            trigger="user:all",
            plan_file=self._real_plan_file(tmp_path, monkeypatch),
        )
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "userall_runner01" in ids

    def test_build_all_runners_excludes_api_trigger(self, event_service, sync_redis):
        """R: trigger="api" runner → 화이트리스트에 없으므로 미포함"""
        self._register_runner(sync_redis, "api_runner01", trigger="api")
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "api_runner01" not in ids

    def test_build_all_runners_excludes_trigger_tc_prefix_only(self, event_service, sync_redis):
        """B: trigger="tc:" (접두사만, 값 없음) → 필터링됨"""
        self._register_runner(sync_redis, "tconly_runner01", trigger="tc:")
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "tconly_runner01" not in ids

    def test_build_all_runners_mixed(self, event_service, sync_redis, tmp_path, monkeypatch):
        """R: tc: runner + 일반 runner 혼재 → 일반 runner만 반환"""
        self._register_runner(
            sync_redis,
            "vis_runner01",
            trigger="user",
            plan_file=self._real_plan_file(tmp_path, monkeypatch),
        )
        self._register_runner(sync_redis, "invis_runner01", trigger="tc:pytest")
        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        assert "vis_runner01" in ids
        assert "invis_runner01" not in ids

    def test_build_all_runners_includes_stopped_user_trigger(self, event_service, sync_redis, tmp_path, monkeypatch):
        """R: trigger="user" + status="stopped" + 실제 plan evidence runner → 결과에 포함"""
        self._register_runner(
            sync_redis,
            "stopped_user01",
            trigger="user",
            status="stopped",
            plan_file=self._real_plan_file(tmp_path, monkeypatch),
        )
        result = build_all_runners_status(event_service._sync)
        assert "stopped_user01" in [r["runner_id"] for r in result]

    def test_build_all_runners_plan_file_null_is_not_visible(self, event_service, sync_redis):
        """R: trigger="user"라도 plan_file evidence가 없으면 결과에서 제외"""
        self._register_runner(sync_redis, "nopf_user01", trigger="user")
        result = build_all_runners_status(event_service._sync)
        matching = [r for r in result if r["runner_id"] == "nopf_user01"]
        assert matching == []


# ─── TestBuildTrackingPayload ────────────────────────────────────────────────

class TestBuildTrackingPayload:
    def test_returns_none_when_no_text(self, event_service):
        assert build_tracking_payload(event_service._sync) is None

    def test_returns_dict_with_text(self, event_service, sync_redis):
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_text", "[ ] 테스트 태스크")
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_confidence", "HIGH")
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_line_num", "42")
        sync_redis.set(f"{REDIS_STATE_KEY}:current_task_plan_file", "/path/to/plan.md")

        payload = build_tracking_payload(event_service._sync)
        assert payload is not None
        assert payload["text"] == "[ ] 테스트 태스크"
        assert payload["confidence"] == "HIGH"
        assert payload["line_num"] == 42
        assert payload["plan_file"] == "/path/to/plan.md"


# ─── TestBuildAllRunnersStatusRecentInclusion ─────────────────────────────────

class TestBuildAllRunnersStatusRecentInclusion:
    """SSE build_all_runners_status()의 RECENT visible 러너 포함 검증"""

    def _real_plan_file(self, tmp_path, monkeypatch) -> str:
        plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_name = "2026-05-20_real-user-plan.md"
        (plans_dir / plan_name).write_text("# real\n", encoding="utf-8")
        monkeypatch.setattr(visibility, "_project_root", lambda: tmp_path)
        return f"docs/plan/{plan_name}"

    def _register_recent(self, r, runner_id: str, trigger: str | None = None, plan_file: str = "docs/plan/test.md"):
        """RECENT_RUNNERS_KEY에 등록 (ACTIVE에는 미등록)"""
        r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
        if trigger is not None:
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)

    def test_build_all_runners_status_includes_recent_visible(self, event_service, sync_redis, tmp_path, monkeypatch):
        """R: ACTIVE 빈 + RECENT에 trigger='user' runner → 결과에 포함"""
        runner_id = "recent-vis-001"
        self._register_recent(sync_redis, runner_id, trigger="user", plan_file=self._real_plan_file(tmp_path, monkeypatch))

        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]

        assert runner_id in ids, (
            f"RECENT의 visible runner {runner_id!r}이 SSE 결과에 포함되지 않음. "
            f"결과: {ids}"
        )

    def test_build_all_runners_status_excludes_recent_invisible(self, event_service, sync_redis):
        """I: RECENT에 trigger=None runner → 결과에 미포함 (화이트리스트 필터링)"""
        runner_id = "recent-invis-001"
        self._register_recent(sync_redis, runner_id, trigger=None)

        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]

        assert runner_id not in ids, (
            f"RECENT의 invisible runner {runner_id!r}이 SSE 결과에 포함됨 — 필터링 실패. "
            f"결과: {ids}"
        )

    def test_build_all_runners_status_deduplicates_active_recent(self, event_service, sync_redis, tmp_path, monkeypatch):
        """B: 동일 runner_id가 ACTIVE+RECENT 모두에 존재 → 결과에 1개만 포함"""
        runner_id = "dedup-001"
        plan_file = self._real_plan_file(tmp_path, monkeypatch)
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        sync_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
        sync_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        sync_redis.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})

        result = build_all_runners_status(event_service._sync)
        ids = [r["runner_id"] for r in result]
        count = ids.count(runner_id)

        assert count == 1, (
            f"ACTIVE+RECENT 중복 runner {runner_id!r}이 {count}회 포함됨 (기대: 1회). "
            f"결과: {ids}"
        )
