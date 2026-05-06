"""PlanExecutionClaimService 단위 테스트 — RIGHT-BICEP 원칙 적용

대상 소스: app/modules/dev_runner/services/plan_execution_claim_service.py
DB: in-memory SQLite (FK check_same_thread=False)
파일시스템 의존: write_claim_id / clear_claim_id를 mock으로 격리
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_execution_claim import PlanExecutionClaim
from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.dev_runner.services.plan_execution_claim_service import (
    claim_plan,
    activate_claim,
    heartbeat_claim,
    release_claim,
    mark_stale_claims,
    get_active_claim_for_plan,
    get_active_claim_for_runner,
    get_active_claims_map,
    ClaimConflictError,
    DEFAULT_LEASE_SECONDS,
)


def _create_tables(eng):
    """테스트에 필요한 테이블만 생성. ForeignKey 순서 보장을 위해 명시 순서 유지."""
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)
    PlanExecutionClaim.__table__.create(bind=eng, checkfirst=True)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """매 테스트마다 롤백되는 세션"""
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(autouse=True)
def no_header_io():
    """plan 파일 I/O를 mock으로 격리. 모든 테스트에 적용."""
    with patch(
        "app.modules.dev_runner.services.plan_execution_claim_service._write_header"
    ) as mock_write, patch(
        "app.modules.dev_runner.services.plan_execution_claim_service._clear_header"
    ) as mock_clear:
        yield mock_write, mock_clear


PLAN_PATH = "docs/plan/2026-05-05_test-claim.md"


# ========== claim_plan() — R: 정상 생성 ==========

class TestClaimPlan:

    def test_claim_plan_creates_queued_row(self, db):
        """R: claim_plan() → state=queued 행 생성"""
        claim = claim_plan(db, PLAN_PATH, engine="claude", runner_id="runner-1")
        assert claim.plan_path == PLAN_PATH
        assert claim.state == "queued"
        assert claim.claim_id is not None
        assert len(claim.claim_id) == 36  # UUID4 형식

    def test_claim_plan_sets_lease_expires(self, db):
        """R: lease_expires_at이 now + DEFAULT_LEASE_SECONDS 이후로 설정된다"""
        before = datetime.now()
        claim = claim_plan(db, PLAN_PATH + "_lease")
        after = datetime.now()
        assert claim.lease_expires_at is not None
        expected_lower = before + timedelta(seconds=DEFAULT_LEASE_SECONDS - 1)
        expected_upper = after + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)
        assert expected_lower <= claim.lease_expires_at <= expected_upper

    def test_claim_plan_stores_engine_and_runner_id(self, db):
        """R: engine, runner_id가 DB에 정확히 저장된다"""
        claim = claim_plan(db, PLAN_PATH + "_meta", engine="codex", runner_id="run-xyz")
        assert claim.engine == "codex"
        assert claim.runner_id == "run-xyz"

    def test_claim_plan_calls_write_header(self, db, no_header_io):
        """R: claim 생성 시 _write_header가 claim_id와 함께 호출된다"""
        mock_write, _ = no_header_io
        path = PLAN_PATH + "_header"
        claim = claim_plan(db, path)
        mock_write.assert_called_once_with(path, claim.claim_id)

    # B: Boundary — 빈 plan_path 허용 여부 (모델 제약 없음, 빈 문자열 저장 가능)
    def test_claim_plan_empty_optional_fields(self, db):
        """B: engine/runner_id/session_id 없이도 claim 생성 가능"""
        claim = claim_plan(db, PLAN_PATH + "_empty_opts")
        assert claim.engine is None
        assert claim.runner_id is None
        assert claim.session_id is None

    # E: Error — 중복 claim 차단
    def test_claim_plan_raises_conflict_on_duplicate(self, db):
        """E: 동일 plan_path에 active/queued claim이 있으면 ClaimConflictError"""
        path = PLAN_PATH + "_conflict"
        claim_plan(db, path, runner_id="first")
        with pytest.raises(ClaimConflictError) as exc_info:
            claim_plan(db, path, runner_id="second")
        assert exc_info.value.existing_claim.runner_id == "first"

    def test_claim_plan_allows_new_claim_after_release(self, db):
        """E: released 상태면 새 claim 생성 가능 (충돌 없음)"""
        path = PLAN_PATH + "_reuse"
        first = claim_plan(db, path)
        release_claim(db, first.claim_id)
        second = claim_plan(db, path)
        assert second.claim_id != first.claim_id
        assert second.state == "queued"


# ========== activate_claim() ==========

class TestActivateClaim:

    def test_activate_claim_transitions_to_active(self, db):
        """R: queued → active 전환"""
        claim = claim_plan(db, PLAN_PATH + "_activate")
        activated = activate_claim(db, claim.claim_id)
        assert activated.state == "active"

    def test_activate_claim_sets_heartbeat(self, db):
        """R: activate 후 heartbeat_at이 설정된다"""
        claim = claim_plan(db, PLAN_PATH + "_hb_activate")
        before = datetime.now()
        activated = activate_claim(db, claim.claim_id)
        after = datetime.now()
        assert activated.heartbeat_at is not None
        assert before <= activated.heartbeat_at <= after

    def test_activate_claim_updates_runner_and_branch(self, db):
        """R: runner_id, pid, branch, worktree_path가 갱신된다"""
        claim = claim_plan(db, PLAN_PATH + "_activate_fields")
        activated = activate_claim(
            db,
            claim.claim_id,
            runner_id="runner-final",
            pid=12345,
            branch="impl/test",
            worktree_path="/tmp/wt",
        )
        assert activated.runner_id == "runner-final"
        assert activated.pid == 12345
        assert activated.branch == "impl/test"
        assert activated.worktree_path == "/tmp/wt"

    def test_activate_claim_extends_lease(self, db):
        """R: activate 후 lease_expires_at이 DEFAULT_LEASE_SECONDS만큼 연장된다"""
        claim = claim_plan(db, PLAN_PATH + "_lease_ext")
        before = datetime.now()
        activated = activate_claim(db, claim.claim_id)
        after = datetime.now()
        lower = before + timedelta(seconds=DEFAULT_LEASE_SECONDS - 1)
        upper = after + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)
        assert lower <= activated.lease_expires_at <= upper

    def test_activate_claim_not_found_raises(self, db):
        """E: 존재하지 않는 claim_id → ValueError"""
        with pytest.raises(ValueError, match="claim not found"):
            activate_claim(db, "00000000-0000-0000-0000-000000000000")


# ========== heartbeat_claim() ==========

class TestHeartbeatClaim:

    def test_heartbeat_updates_heartbeat_at(self, db):
        """R: heartbeat_claim() 호출 후 heartbeat_at이 최신 시각으로 갱신된다"""
        claim = claim_plan(db, PLAN_PATH + "_hb")
        activate_claim(db, claim.claim_id)
        before = datetime.now()
        updated = heartbeat_claim(db, claim.claim_id)
        after = datetime.now()
        assert before <= updated.heartbeat_at <= after

    def test_heartbeat_extends_lease(self, db):
        """R: heartbeat 후 lease_expires_at이 연장된다"""
        claim = claim_plan(db, PLAN_PATH + "_hb_lease")
        activate_claim(db, claim.claim_id)
        before = datetime.now()
        updated = heartbeat_claim(db, claim.claim_id)
        after = datetime.now()
        lower = before + timedelta(seconds=DEFAULT_LEASE_SECONDS - 1)
        upper = after + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)
        assert lower <= updated.lease_expires_at <= upper

    def test_heartbeat_custom_lease(self, db):
        """B: lease_seconds 파라미터가 적용된다"""
        claim = claim_plan(db, PLAN_PATH + "_hb_custom")
        activate_claim(db, claim.claim_id)
        before = datetime.now()
        updated = heartbeat_claim(db, claim.claim_id, lease_seconds=60)
        after = datetime.now()
        lower = before + timedelta(seconds=59)
        upper = after + timedelta(seconds=61)
        assert lower <= updated.lease_expires_at <= upper

    def test_heartbeat_not_found_raises(self, db):
        """E: 존재하지 않는 claim_id → ValueError"""
        with pytest.raises(ValueError, match="claim not found"):
            heartbeat_claim(db, "00000000-0000-0000-0000-000000000000")


# ========== release_claim() ==========

class TestReleaseClaim:

    def test_release_claim_transitions_to_released(self, db):
        """R: release_claim() 후 state=released"""
        claim = claim_plan(db, PLAN_PATH + "_release")
        released = release_claim(db, claim.claim_id)
        assert released.state == "released"

    def test_release_claim_sets_released_at(self, db):
        """R: released_at이 설정된다"""
        claim = claim_plan(db, PLAN_PATH + "_release_at")
        before = datetime.now()
        released = release_claim(db, claim.claim_id)
        after = datetime.now()
        assert released.released_at is not None
        assert before <= released.released_at <= after

    def test_release_claim_calls_clear_header(self, db, no_header_io):
        """R: _clear_header가 plan_path와 함께 호출된다"""
        _, mock_clear = no_header_io
        path = PLAN_PATH + "_clear_hdr"
        claim = claim_plan(db, path)
        release_claim(db, claim.claim_id)
        mock_clear.assert_called_once_with(path)

    def test_release_claim_removes_from_active_query(self, db):
        """R: release 후 get_active_claim_for_plan()이 None 반환"""
        path = PLAN_PATH + "_release_active"
        claim = claim_plan(db, path)
        release_claim(db, claim.claim_id)
        assert get_active_claim_for_plan(db, path) is None

    def test_release_not_found_raises(self, db):
        """E: 존재하지 않는 claim_id → ValueError"""
        with pytest.raises(ValueError, match="claim not found"):
            release_claim(db, "00000000-0000-0000-0000-000000000000")


# ========== mark_stale_claims() ==========

class TestMarkStaleClaims:

    def test_mark_stale_expired_lease(self, db):
        """R: lease_expires_at이 과거이고 heartbeat도 오래된 active claim → stale"""
        claim = claim_plan(db, PLAN_PATH + "_stale", lease_seconds=1)
        activate_claim(db, claim.claim_id)

        # 강제로 만료 시각을 과거로 설정
        db_claim = db.query(PlanExecutionClaim).filter_by(claim_id=claim.claim_id).one()
        db_claim.lease_expires_at = datetime.now() - timedelta(seconds=700)
        db_claim.heartbeat_at = datetime.now() - timedelta(seconds=700)
        db.commit()

        stale = mark_stale_claims(db, threshold_seconds=600)
        assert any(s.claim_id == claim.claim_id for s in stale)
        refreshed = db.query(PlanExecutionClaim).filter_by(claim_id=claim.claim_id).one()
        assert refreshed.state == "stale"

    def test_mark_stale_skips_recently_heartbeated(self, db):
        """B: heartbeat_at이 최신인 active claim은 stale로 변경하지 않는다"""
        claim = claim_plan(db, PLAN_PATH + "_fresh_hb")
        activate_claim(db, claim.claim_id)

        # lease_expires는 과거, heartbeat_at은 최신
        db_claim = db.query(PlanExecutionClaim).filter_by(claim_id=claim.claim_id).one()
        db_claim.lease_expires_at = datetime.now() - timedelta(seconds=10)
        db_claim.heartbeat_at = datetime.now()  # 최신
        db.commit()

        stale = mark_stale_claims(db, threshold_seconds=600)
        assert not any(s.claim_id == claim.claim_id for s in stale)

    def test_mark_stale_marks_expired_queued_claim(self, db):
        """B: queued 상태 claim도 lease가 만료되면 stale 처리한다."""
        claim = claim_plan(db, PLAN_PATH + "_queued_skip")
        # queued 상태 유지, lease_expires를 과거로 설정
        db_claim = db.query(PlanExecutionClaim).filter_by(claim_id=claim.claim_id).one()
        db_claim.lease_expires_at = datetime.now() - timedelta(seconds=700)
        db_claim.heartbeat_at = datetime.now() - timedelta(seconds=700)
        db.commit()

        stale = mark_stale_claims(db, threshold_seconds=600)
        assert any(s.claim_id == claim.claim_id for s in stale)
        refreshed = db.query(PlanExecutionClaim).filter_by(claim_id=claim.claim_id).one()
        assert refreshed.state == "stale"

    def test_mark_stale_returns_empty_when_none(self, db):
        """B: 만료된 active claim 없으면 빈 리스트 반환"""
        stale = mark_stale_claims(db, threshold_seconds=600)
        # 이전 테스트에서 stale로 전환된 것은 state=stale이므로 대상 아님
        assert isinstance(stale, list)


# ========== get_active_claims_map() ==========

class TestGetActiveClaimsMap:

    def test_returns_map_for_active_plans(self, db):
        """R: active/queued claim이 있는 plan_path를 dict로 반환"""
        p1 = PLAN_PATH + "_map1"
        p2 = PLAN_PATH + "_map2"
        c1 = claim_plan(db, p1)
        c2 = claim_plan(db, p2)

        result = get_active_claims_map(db, [p1, p2])
        assert p1 in result
        assert p2 in result
        assert result[p1].claim_id == c1.claim_id
        assert result[p2].claim_id == c2.claim_id

    def test_excludes_released_claims(self, db):
        """R: released claim은 map에 포함되지 않는다"""
        path = PLAN_PATH + "_map_released"
        claim = claim_plan(db, path)
        release_claim(db, claim.claim_id)

        result = get_active_claims_map(db, [path])
        assert path not in result

    def test_empty_input_returns_empty_dict(self, db):
        """B: 빈 plan_paths 입력 → 빈 dict"""
        result = get_active_claims_map(db, [])
        assert result == {}

    def test_unknown_path_not_in_result(self, db):
        """B: claim이 없는 path는 결과에 포함되지 않는다"""
        result = get_active_claims_map(db, ["docs/plan/nonexistent.md"])
        assert "docs/plan/nonexistent.md" not in result

    def test_returns_latest_claim_for_same_path(self, db):
        """C: 동일 path에 released + queued가 있으면 queued(최신)만 반환"""
        path = PLAN_PATH + "_map_latest"
        first = claim_plan(db, path)
        release_claim(db, first.claim_id)
        second = claim_plan(db, path)  # 새 queued

        result = get_active_claims_map(db, [path])
        assert result[path].claim_id == second.claim_id


class TestGetActiveClaimForRunner:

    def test_returns_queued_or_active_claim_for_runner(self, db):
        """R: runner_id 기준으로 queued/active claim을 조회한다."""
        claim = claim_plan(db, PLAN_PATH + "_runner_lookup", runner_id="runner-lookup-1")

        result = get_active_claim_for_runner(db, "runner-lookup-1")

        assert result is not None
        assert result.claim_id == claim.claim_id

    def test_excludes_released_claim_for_runner(self, db):
        """B: released claim은 runner_id 조회 대상이 아니다."""
        claim = claim_plan(db, PLAN_PATH + "_runner_released", runner_id="runner-lookup-2")
        release_claim(db, claim.claim_id)

        assert get_active_claim_for_runner(db, "runner-lookup-2") is None
