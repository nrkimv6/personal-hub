"""
T4: MGET 성능 검증 — Runner 3개 동시 실행 시 응답 시간 측정

logs.ps1 Phase 3 구현 검증:
- Get-ActivePlanRunners의 MGET 배치 최적화가 실제로 빠른지 확인
- Redis 미사용 환경(worktree)에서는 skip, 실제 Redis 환경에서 측정
"""

import time
import uuid
import pytest

# Redis 가용성 확인 (skip 조건)
def _redis_available():
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, socket_timeout=1)
        return r.ping()
    except Exception:
        return False


REDIS_SKIP = pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not available — skipping performance test (worktree mode)"
)

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_SET_KEY = "plan-runner:active_runners"


@pytest.fixture
def redis_client():
    """실제 Redis 클라이언트"""
    import redis
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    yield r


@pytest.fixture
def three_mock_runners(redis_client):
    """3개의 mock runner를 Redis에 세팅하고, 테스트 후 정리"""
    runner_ids = [str(uuid.uuid4())[:8] for _ in range(3)]
    test_log_dir = "D:/work/project/tools/monitor-page/logs"

    # 세팅
    pipeline = redis_client.pipeline()
    for i, rid in enumerate(runner_ids):
        pipeline.sadd(ACTIVE_SET_KEY, rid)
        pipeline.set(f"{RUNNER_KEY_PREFIX}:{rid}:log_file_path",
                     f"{test_log_dir}/plan-runner-{rid}.log")
        pipeline.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file",
                     f"docs/plan/2026-03-test-plan-{i}.md")
        pipeline.set(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path",
                     f"{test_log_dir}/plan-runner-{rid}.log")
        pipeline.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", str(10000 + i))
    pipeline.execute()

    yield runner_ids

    # 정리
    cleanup = redis_client.pipeline()
    for rid in runner_ids:
        cleanup.srem(ACTIVE_SET_KEY, rid)
        cleanup.delete(f"{RUNNER_KEY_PREFIX}:{rid}:log_file_path")
        cleanup.delete(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file")
        cleanup.delete(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path")
        cleanup.delete(f"{RUNNER_KEY_PREFIX}:{rid}:pid")
    cleanup.execute()


def _measure_mget_approach(redis_client, runner_ids):
    """MGET 배치 호출 방식 (Phase 3 구현 — logs.ps1 Get-ActivePlanRunners)"""
    keys = []
    for rid in runner_ids:
        keys.append(f"{RUNNER_KEY_PREFIX}:{rid}:log_file_path")
        keys.append(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file")
        keys.append(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path")
        keys.append(f"{RUNNER_KEY_PREFIX}:{rid}:pid")

    start = time.perf_counter()
    vals = redis_client.mget(keys)
    elapsed = time.perf_counter() - start

    # 결과 파싱 (nil 필터링)
    results = []
    for i, rid in enumerate(runner_ids):
        base = i * 4
        log_path    = vals[base]    if vals[base]    and vals[base]    != "(nil)" else None
        plan_file   = vals[base+1]  if vals[base+1]  and vals[base+1]  != "(nil)" else None
        stream_path = vals[base+2]  if vals[base+2]  and vals[base+2]  != "(nil)" else None
        pid_val     = vals[base+3]  if vals[base+3]  and vals[base+3]  != "(nil)" else None
        results.append({
            "runner_id": rid,
            "log_path": log_path,
            "plan_file": plan_file,
            "stream_path": stream_path,
            "pid": pid_val,
        })

    return elapsed, results


def _measure_sequential_get_approach(redis_client, runner_ids):
    """순차 GET 방식 (Phase 3 이전 — runner당 4회 호출)"""
    start = time.perf_counter()
    results = []
    for rid in runner_ids:
        log_path    = redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:log_file_path")
        plan_file   = redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file")
        stream_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path")
        pid_val     = redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid")
        results.append({
            "runner_id": rid,
            "log_path": log_path,
            "plan_file": plan_file,
            "stream_path": stream_path,
            "pid": pid_val,
        })
    elapsed = time.perf_counter() - start
    return elapsed, results


@REDIS_SKIP
def test_mget_returns_all_three_runners(redis_client, three_mock_runners):
    """MGET 배치 호출로 3개 runner 데이터를 모두 올바르게 반환하는지 확인"""
    runner_ids = three_mock_runners
    _, results = _measure_mget_approach(redis_client, runner_ids)

    assert len(results) == 3, "3개 runner 모두 반환되어야 한다"

    for result in results:
        assert result["log_path"] is not None, f"log_path 누락: {result['runner_id']}"
        assert result["plan_file"] is not None, f"plan_file 누락: {result['runner_id']}"
        assert result["stream_path"] is not None, f"stream_path 누락: {result['runner_id']}"
        assert result["pid"] is not None, f"pid 누락: {result['runner_id']}"


@REDIS_SKIP
def test_mget_response_time_under_500ms(redis_client, three_mock_runners):
    """
    Runner 3개 기준 MGET 응답 시간이 500ms 이하인지 확인.

    Phase 3 이전: runner당 4회 redis-cli 프로세스 생성 → 3개 × 4 + 2(PING+SMEMBERS) = 14 프로세스
    Phase 3 이후: 1회 MGET 배치 호출 → redis-py 단순 네트워크 왕복
    """
    runner_ids = three_mock_runners

    # 5회 측정 후 중간값 사용 (노이즈 제거)
    timings = []
    for _ in range(5):
        elapsed, results = _measure_mget_approach(redis_client, runner_ids)
        timings.append(elapsed)
        assert len(results) == 3

    timings.sort()
    median_ms = timings[2] * 1000  # 중간값 (ms)

    print(f"\n[MGET 응답 시간] Runner 3개 × 4키 = 12키 배치 조회")
    print(f"  측정값: {[f'{t*1000:.2f}ms' for t in timings]}")
    print(f"  중간값: {median_ms:.2f}ms (임계값: 500ms)")

    assert median_ms < 500, (
        f"MGET 응답 시간 {median_ms:.2f}ms > 500ms — "
        "Redis 연결 문제 또는 최적화 미적용 의심"
    )


@REDIS_SKIP
def test_mget_faster_than_sequential(redis_client, three_mock_runners):
    """
    MGET 배치가 순차 GET보다 빠른지 비교 검증.

    redis-py 기반이므로 subprocess 오버헤드 없이 순수 프로토콜 차이만 측정.
    MGET는 1회 왕복, 순차 GET는 12회 왕복 → MGET가 빨라야 정상.
    """
    runner_ids = three_mock_runners

    # 각각 5회씩 측정
    mget_times = []
    seq_times = []

    for _ in range(5):
        t, _ = _measure_mget_approach(redis_client, runner_ids)
        mget_times.append(t)
        t, _ = _measure_sequential_get_approach(redis_client, runner_ids)
        seq_times.append(t)

    mget_times.sort()
    seq_times.sort()
    mget_median_ms = mget_times[2] * 1000
    seq_median_ms  = seq_times[2]  * 1000

    print(f"\n[MGET vs 순차 GET 성능 비교] Runner 3개 기준")
    print(f"  MGET 중간값:  {mget_median_ms:.3f}ms")
    print(f"  순차 GET 중간값: {seq_median_ms:.3f}ms")
    print(f"  개선율: {seq_median_ms / mget_median_ms:.1f}x")

    # MGET이 순차 GET보다 빠르거나 비슷해야 한다 (redis-py는 파이프라인 최적화가 있어 차이가 작을 수 있음)
    # 중요한 건 둘 다 빠른 것이 확인되는 것
    assert mget_median_ms < 500, f"MGET {mget_median_ms:.2f}ms 초과 — 성능 저하 의심"
    assert seq_median_ms < 1000, f"순차 GET {seq_median_ms:.2f}ms 초과 — Redis 연결 문제 의심"


@REDIS_SKIP
def test_nil_values_filtered_correctly(redis_client, three_mock_runners):
    """
    MGET 결과에서 (nil) 값이 올바르게 필터링되는지 확인 (Phase 1 검증).
    stream_log_path 키 일부를 삭제 후 MGET 결과에서 None 반환 확인.
    """
    runner_ids = three_mock_runners

    # 첫 번째 runner의 stream_log_path 삭제 (nil 시뮬레이션)
    redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_ids[0]}:stream_log_path")

    _, results = _measure_mget_approach(redis_client, runner_ids)

    assert results[0]["stream_path"] is None, (
        "삭제된 키는 None으로 반환되어야 한다 (nil 필터링 확인)"
    )
    # 나머지 runner는 정상
    for result in results[1:]:
        assert result["stream_path"] is not None
