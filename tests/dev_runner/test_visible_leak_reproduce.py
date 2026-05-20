"""visible 노출 버그 재현/통합 TC

Phase T3: fakeredis로 실제 get_all_runners() 호출.
근본 원인 재현: test_source 누락 → trigger="api" → 이전 코드면 visible=True (버그), 수정 후 visible=False (정상).
"""

import pytest
import asyncio
import uuid
import fakeredis.aioredis
import redis as sync_redis
import redis.asyncio as aioredis
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from app.modules.dev_runner.services import visibility
from app.modules.dev_runner.services.executor_service import ExecutorService

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"


async def _make_executor_with_fakeredis():
    """fakeredis를 주입한 ExecutorService 인스턴스 생성 (decode_responses=True: str 반환)"""
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = fake_redis
    return svc, fake_redis


async def _seed_runner(fake_redis, runner_id: str, trigger: str | None, status: str = "running", plan_file: str = "docs/plan/test.md"):
    """fakeredis에 runner 키를 직접 세팅"""
    await fake_redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    await fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", status)
    await fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
    if trigger is not None:
        await fake_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)
    # trigger 키를 세팅하지 않으면 Redis에서 None 반환 → TTL 만료/소실 시나리오


# ══════════════════════════════════════════════════════════════════════════════
# 재현 TC: 화이트리스트 전환 후 fail-closed 검증
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reproduce_visible_leak_missing_test_source():
    """재현: test_source 누락 시 trigger="api" → get_all_runners() → visible=False (fail-closed)

    버그 재발 시나리오: test_source 없이 RunRequest 생성 → executor_service가 trigger="api" 설정.
    화이트리스트 전환 전: visible=True (버그)
    화이트리스트 전환 후: visible=False (정상 — 이 TC가 검증)
    """
    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "leak-test-001"
    # test_source 누락 시나리오: trigger="api" (executor_service 기본 폴백)
    await _seed_runner(fake_redis, runner_id, trigger="api")

    # DB 세션 mock (orphan 판별용)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert len(runners) == 1
    runner = runners[0]
    assert runner.runner_id == runner_id
    assert runner.trigger == "api"
    assert runner.visible is False, (
        f"trigger='api' runner가 visible=True! "
        f"화이트리스트 전환이 제대로 적용되지 않았습니다. visible={runner.visible!r}"
    )


@pytest.mark.asyncio
async def test_reproduce_visible_leak_trigger_none():
    """재현: trigger 키 소실 시나리오 → get_all_runners() → visible=False (fail-closed)

    버그 재발 시나리오: RUNNER_KEY_SUFFIXES에서 trigger 누락 → TTL 미설정 → runner cleanup 후 trigger 키 소실.
    화이트리스트 전환 전: visible=True (버그)
    화이트리스트 전환 후: visible=False (정상)
    """
    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "leak-test-002"
    # trigger 키를 아예 세팅하지 않음 (TTL 만료/소실 시나리오)
    await _seed_runner(fake_redis, runner_id, trigger=None)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert len(runners) == 1
    runner = runners[0]
    assert runner.runner_id == runner_id
    assert runner.trigger is None
    assert runner.visible is False, (
        f"trigger=None runner가 visible=True! "
        f"화이트리스트 전환이 제대로 적용되지 않았습니다. visible={runner.visible!r}"
    )


@pytest.mark.asyncio
@pytest.mark.allow_prod_redis
async def test_reproduce_5th_visible_leak():
    """T3 재현: 실제 Redis에 tc-pytest- prefix + trigger="user" 직접 기록 → visible=False 확인

    5차 재발 시나리오 재현:
      pytest가 운영 Redis(localhost:6379 db=0)에 trigger="user" 키를 직접 기록.
      화이트리스트 단독 방어면 visible=True가 반환되는 것이 버그.

    이중 방어 검증:
      1) 화이트리스트: trigger="user" → is_user=True (화이트리스트는 통과)
      2) tc-pytest- prefix 이중 방어: is_user=False 강제 → visible=False

    실제 Redis 사용 (mock 없음). cleanup은 redis_runner_cleanup autouse fixture가 보장.
    """
    # 실제 Redis 연결 확인
    try:
        r = sync_redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception:
        pytest.fail("Redis 연결 불가 — 실제 Redis 필요 (로컬 개발 환경에서 실행)")

    runner_id = f"tc-pytest-5th-leak-{uuid.uuid4().hex[:8]}"

    # 실제 Redis에 trigger="user" 직접 기록 (5차 재발 시나리오)
    r.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")

    # ExecutorService 인스턴스에 실제 Redis 클라이언트 주입
    # (__new__를 사용해 force_test_source fixture의 __init__ patch 우회)
    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = aioredis.Redis(
        host="localhost", port=6379, db=0, decode_responses=True
    )

    # DB 세션 mock (orphan 판별용 — 테스트 DB 불필요)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    # tc-pytest- runner가 목록에 존재해야 함
    tc_runners = [item for item in runners if item.runner_id == runner_id]
    assert len(tc_runners) == 1, (
        f"tc-pytest- runner가 get_all_runners() 결과에 없음: "
        f"{[item.runner_id for item in runners]}"
    )

    tc_runner = tc_runners[0]
    assert tc_runner.trigger == "user", (
        f"trigger 값이 예상과 다름: {tc_runner.trigger!r} (expected 'user')"
    )
    assert tc_runner.visible is False, (
        f"5차 재발 재현! tc-pytest- prefix runner가 trigger='user'임에도 visible=True!\n"
        f"  runner_id={runner_id}\n"
        f"  tc-pytest- prefix 이중 방어(executor_service.py L764)가 작동하지 않습니다.\n"
        f"  visible={tc_runner.visible!r}"
    )


@pytest.mark.asyncio
async def test_user_trigger_with_real_plan_evidence_visible_true_integration(tmp_path, monkeypatch):
    """통합: trigger="user" + 실제 plan evidence → get_all_runners() → visible=True."""
    plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
    plans_dir.mkdir(parents=True)
    plan_name = "2026-05-20_real-user-plan.md"
    (plans_dir / plan_name).write_text("# real\n", encoding="utf-8")
    monkeypatch.setattr(visibility, "_project_root", lambda: tmp_path)

    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "user-runner-001"
    await _seed_runner(fake_redis, runner_id, trigger="user", plan_file=f"docs/plan/{plan_name}")

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert len(runners) == 1
    runner = runners[0]
    assert runner.visible is True, (
        f"trigger='user' runner가 visible=False! "
        f"프론트엔드에서 사용자 실행 runner가 표시되지 않습니다. visible={runner.visible!r}"
    )


@pytest.mark.asyncio
async def test_user_trigger_synthetic_plan_hidden_integration():
    """통합: trigger=user여도 synthetic plan이면 get_all_runners()에서 visible=False."""
    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "synthetic-user-runner-001"
    await _seed_runner(fake_redis, runner_id, trigger="user", plan_file="docs/plan/approval-t5.md")

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert len(runners) == 1
    assert runners[0].visible is False


@pytest.mark.asyncio
async def test_user_trigger_synthetic_plan_skips_db_backfill(monkeypatch):
    """통합: Redis synthetic user row는 Postgres mirror backfill 대상이 아니다."""
    svc, fake_redis = await _make_executor_with_fakeredis()
    runner_id = "synthetic-backfill-user-001"
    await _seed_runner(fake_redis, runner_id, trigger="user", plan_file="docs/plan/blocked-plan.md")
    upsert = MagicMock()
    monkeypatch.setattr(svc, "_best_effort_upsert_runner_state", upsert)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    assert [item.runner_id for item in runners] == [runner_id]
    assert runners[0].visible is False
    upsert.assert_not_called()


@pytest.mark.asyncio
async def test_db_only_user_trigger_synthetic_plan_hidden_integration(monkeypatch):
    """통합: Postgres mirror row만 남아도 synthetic plan은 visible=False."""
    svc, _fake_redis = await _make_executor_with_fakeredis()
    runner_id = "db-only-synthetic-user-001"
    row = SimpleNamespace(
        runner_id=runner_id,
        status="stopped",
        plan_file="docs/plan/test.md",
        started_at=None,
        branch=None,
        worktree_path=None,
        exit_reason=None,
        merge_requested=False,
        metadata_json={"trigger": "user"},
    )
    monkeypatch.setattr(svc, "_load_db_runner_states", lambda limit=200: {runner_id: row})

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.database.SessionLocal", return_value=mock_db):
        runners = await svc.get_all_runners()

    matching = [item for item in runners if item.runner_id == runner_id]
    assert len(matching) == 1
    assert matching[0].visible is False
