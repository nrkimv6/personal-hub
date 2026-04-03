"""plans 캐시 무효화 TC — done 트리거 + TTL fallback

Phase T1 (단위 TC):
  - done 트리거: _force_cleanup_state() 호출 시 plan_service.invalidate_plans_cache 호출 확인
  - TTL: 캐시 만료 후 재스캔, TTL 내 캐시 유지, invalidate 후 타임스탬프 리셋

Phase T3 (통합 TC):
  - 파일 삭제 후 TTL 경과 → list_plans에서 사라짐
  - runner cleanup 트리거 후 plan 리스트 갱신
"""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import fakeredis.aioredis as fakeredis_async
import fakeredis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def svc(tmp_path, dev_runner_config_isolation):
    """격리된 PlanService 인스턴스"""
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    return PlanService()


def _make_plan(plan_dir: Path, filename: str, status: str = "구현중") -> Path:
    """테스트용 plan .md 파일 생성"""
    content = (
        f"# Test Plan\n\n"
        f"> 상태: {status}\n"
        f"> 진행률: 0/1 (0%)\n\n"
        f"## TODO\n\n- [ ] 작업1\n"
    )
    p = plan_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


def _register_path(reg_file: Path, path: str, path_type: str = "plan"):
    """registered_paths.json에 경로 추가"""
    paths = json.loads(reg_file.read_text(encoding="utf-8"))
    paths.append({"path": path, "type": path_type})
    reg_file.write_text(json.dumps(paths), encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase T1: done 트리거 TC
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_force_cleanup_single_runner_invalidates_plans_cache(tmp_path):
    """RIGHT: runner_id 지정하여 _force_cleanup_state(runner_id) 호출 → invalidate_plans_cache 1회"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    fake_redis = fakeredis_async.FakeRedis(decode_responses=True)
    runner_id = "abc12345"

    # Redis에 runner status/plan_file 키 세팅
    await fake_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
    await fake_redis.set(f"plan-runner:runners:{runner_id}:plan_file", "/some/plan.md")
    await fake_redis.sadd("plan-runner:active_runners", runner_id)

    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = fake_redis

    with patch("app.modules.dev_runner.services.runner_state.plan_service") as mock_ps:
        await svc._force_cleanup_state(runner_id)
        mock_ps.invalidate_plans_cache.assert_called_once()


@pytest.mark.asyncio
async def test_force_cleanup_all_runners_invalidates_plans_cache(tmp_path):
    """RIGHT: runner_id 없이 _force_cleanup_state() 호출 → invalidate_plans_cache 1회"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    fake_redis = fakeredis_async.FakeRedis(decode_responses=True)
    for rid in ["rid00001", "rid00002"]:
        await fake_redis.set(f"plan-runner:runners:{rid}:status", "running")
        await fake_redis.sadd("plan-runner:active_runners", rid)

    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = fake_redis

    with patch("app.modules.dev_runner.services.runner_state.plan_service") as mock_ps:
        await svc._force_cleanup_state()
        mock_ps.invalidate_plans_cache.assert_called_once()


@pytest.mark.asyncio
async def test_force_cleanup_already_cleaned_skips_cache_invalidation():
    """BOUNDARY: status 키 없는(listener가 이미 정리한) runner → early return, invalidate 호출 안 됨"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    fake_redis = fakeredis_async.FakeRedis(decode_responses=True)
    runner_id = "deadbeef"
    # status 키 없음 (이미 cleanup 완료)
    await fake_redis.sadd("plan-runner:active_runners", runner_id)

    svc = ExecutorService.__new__(ExecutorService)
    svc.async_redis = fake_redis

    with patch("app.modules.dev_runner.services.runner_state.plan_service") as mock_ps:
        await svc._force_cleanup_state(runner_id)
        mock_ps.invalidate_plans_cache.assert_not_called()


# ---------------------------------------------------------------------------
# Phase T1: TTL TC
# ---------------------------------------------------------------------------

def test_plans_cache_ttl_expiry(svc, tmp_path):
    """RIGHT: TTL 경과 후 list_plans 호출 시 _scan_all_plans 재실행"""
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    _make_plan(plan_dir, "test_plan.md")

    cfg = svc._registered_paths
    svc._registered_paths = [{"path": str(plan_dir), "type": "plan"}]

    with patch.object(svc, "_scan_all_plans", wraps=svc._scan_all_plans) as mock_scan:
        # 1차 호출 — 캐시 빌드
        svc.list_plans()
        assert mock_scan.call_count == 1

        # 캐시 타임을 TTL+1초 과거로 조작
        svc._plans_cache_time = time.monotonic() - svc._PLANS_CACHE_TTL - 1

        # 2차 호출 — TTL 만료로 재스캔
        svc.list_plans()
        assert mock_scan.call_count == 2


def test_plans_cache_within_ttl(svc, tmp_path):
    """BOUNDARY: TTL 내 재호출 시 캐시 유지 (재스캔 없음)"""
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    _make_plan(plan_dir, "test_plan.md")

    svc._registered_paths = [{"path": str(plan_dir), "type": "plan"}]

    with patch.object(svc, "_scan_all_plans", wraps=svc._scan_all_plans) as mock_scan:
        svc.list_plans()
        assert mock_scan.call_count == 1

        # 캐시 타임을 TTL-30초 과거로 조작 (아직 유효)
        svc._plans_cache_time = time.monotonic() - svc._PLANS_CACHE_TTL + 30

        svc.list_plans()
        # 재스캔 없음
        assert mock_scan.call_count == 1


def test_invalidate_resets_timestamp(svc, tmp_path):
    """RIGHT: list_plans 후 _plans_cache_time > 0, invalidate 후 == 0"""
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    _make_plan(plan_dir, "test_plan.md")

    svc._registered_paths = [{"path": str(plan_dir), "type": "plan"}]

    svc.list_plans()
    assert svc._plans_cache_time > 0

    svc.invalidate_plans_cache()
    assert svc._plans_cache_time == 0
    assert svc._plans_cache is None
    assert svc._plans_cache_with_ignored is None


# ---------------------------------------------------------------------------
# Phase T3: 통합 TC
# ---------------------------------------------------------------------------

def test_deleted_plan_removed_after_ttl(tmp_path, dev_runner_config_isolation):
    """T3: 파일 삭제 후 TTL 경과 → list_plans에서 사라짐"""
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    plan_file = _make_plan(plan_dir, "vanishing_plan.md")

    svc = PlanService()
    _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir))
    svc._load_registered_paths()

    # 파일 있음 확인
    plans = svc.list_plans()
    filenames = [p.filename for p in plans]
    assert "vanishing_plan.md" in filenames

    # 파일 삭제
    plan_file.unlink()

    # TTL 만료 조작
    svc._plans_cache_time = time.monotonic() - svc._PLANS_CACHE_TTL - 1

    # 재조회 — 파일 없어야 함
    plans = svc.list_plans()
    filenames = [p.filename for p in plans]
    assert "vanishing_plan.md" not in filenames


@pytest.mark.asyncio
async def test_cleanup_triggers_cache_refresh_with_real_plan_service(tmp_path, dev_runner_config_isolation):
    """T3: executor cleanup → invalidate → list_plans 재스캔 — end-to-end 흐름"""
    from app.modules.dev_runner.services.plan_service import PlanService
    from app.modules.dev_runner.services.executor_service import ExecutorService

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    plan_file = _make_plan(plan_dir, "target_plan.md")

    real_svc = PlanService()
    _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir))
    real_svc._load_registered_paths()

    # 파일 있음 확인
    plans = real_svc.list_plans()
    assert any(p.filename == "target_plan.md" for p in plans)

    # 파일 삭제
    plan_file.unlink()

    # RunnerState가 참조하는 plan_service를 real_svc로 교체
    with patch("app.modules.dev_runner.services.runner_state.plan_service", real_svc):
        fake_redis = fakeredis_async.FakeRedis(decode_responses=True)
        runner_id = "cafebabe"
        await fake_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        await fake_redis.sadd("plan-runner:active_runners", runner_id)

        ex = ExecutorService.__new__(ExecutorService)
        ex.async_redis = fake_redis

        # cleanup 호출 → invalidate_plans_cache 실행
        await ex._force_cleanup_state(runner_id)

    # 캐시가 무효화되었으므로 재스캔 → 파일 없어야 함
    plans = real_svc.list_plans()
    assert not any(p.filename == "target_plan.md" for p in plans)
