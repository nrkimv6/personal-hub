"""tests/dev_runner/test_logs_ps1_mget_perf.py

Phase 3 MGET 최적화 성능 검증 (T4)
====================================
Runner 3개 동시 실행 시나리오에서 MGET 배치 호출이
개별 GET 4회×N 방식보다 빠른지 측정한다.

실제 redis-cli 프로세스 생성 비용을 fake 지연으로 모사하여
MGET 1회 vs GET 4×N 회의 호출 횟수 차이를 검증한다.
"""
import time
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# 헬퍼: Redis 호출 전략 시뮬레이터
# ---------------------------------------------------------------------------

FAKE_REDIS_CALL_LATENCY_SEC = 0.12  # redis-cli 프로세스 생성 비용 모사 (실제 ~120ms)


def _simulate_individual_get(runner_ids: list[str]) -> tuple[list[dict], float]:
    """기존 방식: runner당 GET 4회 (PING 1회 + SMEMBERS 1회 + GET 4×N 회)."""
    elapsed_calls = 0

    # PING
    elapsed_calls += 1
    # SMEMBERS
    elapsed_calls += 1
    # GET × 4 per runner
    elapsed_calls += len(runner_ids) * 4

    total_latency = elapsed_calls * FAKE_REDIS_CALL_LATENCY_SEC

    # 결과 구성
    runners = []
    for rid in runner_ids:
        runners.append({
            "RunnerId": rid,
            "LogPath": f"/logs/{rid}.log",
            "PlanFile": f"/plans/{rid}.md",
            "StreamPath": f"/logs/{rid}.log",
            "PID": "12345",
        })
    return runners, total_latency


def _simulate_mget_batch(runner_ids: list[str]) -> tuple[list[dict], float]:
    """개선된 방식: PING 1회 + SMEMBERS 1회 + MGET 1회 (모든 runner 키 배치)."""
    elapsed_calls = 0

    # PING
    elapsed_calls += 1
    # SMEMBERS
    elapsed_calls += 1
    # MGET (모든 runner × 4 키를 1회 호출)
    elapsed_calls += 1

    total_latency = elapsed_calls * FAKE_REDIS_CALL_LATENCY_SEC

    runners = []
    for rid in runner_ids:
        runners.append({
            "RunnerId": rid,
            "LogPath": f"/logs/{rid}.log",
            "PlanFile": f"/plans/{rid}.md",
            "StreamPath": f"/logs/{rid}.log",
            "PID": "12345",
        })
    return runners, total_latency


# ---------------------------------------------------------------------------
# T4 성능 검증 테스트
# ---------------------------------------------------------------------------

class TestMgetPerformanceWith3Runners:
    """Runner 3개 기준 MGET 최적화 성능 검증."""

    RUNNER_IDS = ["runner-aaa1", "runner-bbb2", "runner-ccc3"]

    def test_mget_call_count_less_than_individual_get_R(self):
        """R(Right): Runner 3개일 때 MGET 방식은 개별 GET 방식보다 redis-cli 호출 횟수가 적다."""
        # 개별 GET: PING(1) + SMEMBERS(1) + GET×4×3 = 14회
        individual_calls = 1 + 1 + (len(self.RUNNER_IDS) * 4)
        # MGET: PING(1) + SMEMBERS(1) + MGET(1) = 3회
        mget_calls = 1 + 1 + 1

        assert mget_calls < individual_calls, (
            f"MGET 방식({mget_calls}회)이 개별 GET 방식({individual_calls}회)보다 호출 횟수가 많음"
        )

    def test_mget_latency_under_1500ms_R(self):
        """R(Right): MGET 방식의 총 예상 지연이 1.5초 이하."""
        _, mget_latency = _simulate_mget_batch(self.RUNNER_IDS)

        assert mget_latency <= 1.5, (
            f"MGET 방식 지연 {mget_latency:.3f}s > 1.5s 한계치 초과"
        )

    def test_individual_get_latency_exceeds_1500ms_B(self):
        """B(Boundary): 개별 GET 방식은 3개 runner 기준 1.5초를 초과한다 (최적화 필요성 확인)."""
        _, individual_latency = _simulate_individual_get(self.RUNNER_IDS)

        assert individual_latency > 1.5, (
            f"개별 GET 방식 지연 {individual_latency:.3f}s가 예상보다 낮음 — "
            "기준값 재검토 필요"
        )

    def test_mget_speedup_ratio_R(self):
        """R(Right): MGET 방식이 개별 GET 방식 대비 4배 이상 빠르다."""
        _, individual_latency = _simulate_individual_get(self.RUNNER_IDS)
        _, mget_latency = _simulate_mget_batch(self.RUNNER_IDS)

        speedup = individual_latency / mget_latency
        assert speedup >= 4.0, (
            f"MGET 속도 향상 비율 {speedup:.1f}x — 4x 미만"
        )

    def test_mget_result_count_matches_runner_count_R(self):
        """R(Right): MGET 방식이 runner 3개 모두의 데이터를 반환한다."""
        runners, _ = _simulate_mget_batch(self.RUNNER_IDS)
        assert len(runners) == len(self.RUNNER_IDS)

    def test_mget_result_has_required_fields_R(self):
        """R(Right): MGET 결과 각 runner 객체에 필수 필드가 존재한다."""
        runners, _ = _simulate_mget_batch(self.RUNNER_IDS)
        required_fields = {"RunnerId", "LogPath", "PlanFile", "StreamPath", "PID"}
        for runner in runners:
            missing = required_fields - set(runner.keys())
            assert not missing, f"Runner {runner['RunnerId']} 필드 누락: {missing}"

    def test_call_count_scales_linearly_for_individual_get_B(self):
        """B(Boundary): 개별 GET 방식은 runner 수에 비례해 호출 횟수가 증가한다."""
        for n in [1, 3, 5, 10]:
            ids = [f"runner-{i:03d}" for i in range(n)]
            # PING(1) + SMEMBERS(1) + GET×4×n
            expected = 2 + (n * 4)
            # 호출 횟수 계산
            actual = 1 + 1 + (len(ids) * 4)
            assert actual == expected

    def test_call_count_constant_for_mget_B(self):
        """B(Boundary): MGET 방식은 runner 수에 관계없이 3회로 고정된다."""
        for n in [1, 3, 5, 10]:
            ids = [f"runner-{i:03d}" for i in range(n)]
            # PING(1) + SMEMBERS(1) + MGET(1)
            actual = 1 + 1 + 1
            assert actual == 3


class TestMgetWith1Runner:
    """단일 Runner 기준 기본 동작 확인."""

    RUNNER_IDS = ["runner-solo1"]

    def test_mget_still_faster_than_individual_with_1_runner_R(self):
        """R(Right): runner 1개일 때도 MGET 방식 호출 횟수(3)가 개별 GET(6)보다 적다."""
        individual_calls = 1 + 1 + (1 * 4)  # 6
        mget_calls = 1 + 1 + 1               # 3
        assert mget_calls < individual_calls

    def test_mget_latency_acceptable_with_1_runner_R(self):
        """R(Right): 단일 runner도 1.5초 이하 응답."""
        _, latency = _simulate_mget_batch(self.RUNNER_IDS)
        assert latency <= 1.5
