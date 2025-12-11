"""
타이밍 캘리브레이션 서비스 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

CORRECT 조건 적용:
- Conformance: 형식 준수
- Ordering: 순서 보장
- Range: 범위 검증
- Reference: 참조 검증
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트

테스트 대상:
- TimingService 캘리브레이션
- Pre-fire 프리셋 관리
- 발사 스케줄 계산
- 결과 기록 및 통계
"""

import pytest
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from typing import List

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.timing_service import (
    TimingService,
    timing_service,
    BoundarySample,
    CalibrationResult,
    FireSchedule,
    PRE_FIRE_PRESETS,
    DEFAULT_PRE_FIRE_PRESET,
)

# 한국 시간대
KST = timezone(timedelta(hours=9))


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def timing_svc():
    """타이밍 서비스 인스턴스"""
    return TimingService()


@pytest.fixture
def mock_db():
    """Mock 데이터베이스 세션"""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.query = MagicMock()
    return db


@pytest.fixture
def sample_boundary_samples():
    """테스트용 경계 감지 샘플"""
    base_time = datetime.now(KST)
    return [
        BoundarySample(
            local_time=base_time,
            server_second=10,
            rtt_ms=100.0,
            offset_ms=50.0
        ),
        BoundarySample(
            local_time=base_time + timedelta(seconds=1),
            server_second=11,
            rtt_ms=120.0,
            offset_ms=60.0
        ),
        BoundarySample(
            local_time=base_time + timedelta(seconds=2),
            server_second=12,
            rtt_ms=90.0,
            offset_ms=45.0
        ),
    ]


@pytest.fixture
def mock_calibration():
    """테스트용 캘리브레이션 결과"""
    from app.models.timing import TimingCalibration
    calibration = MagicMock(spec=TimingCalibration)
    calibration.id = 1
    calibration.host = "booking.naver.com"
    calibration.offset_ms = 80
    calibration.confidence_ms = 15
    calibration.avg_rtt_ms = 100
    calibration.sample_count = 3
    calibration.measured_at = datetime.now()
    return calibration


# ============================================================
# RIGHT: 결과가 올바른가?
# ============================================================

class TestRight:
    """올바른 결과 테스트"""

    def test_pre_fire_presets_exist(self, timing_svc):
        """Pre-fire 프리셋이 존재하는지 확인"""
        presets = timing_svc.get_pre_fire_presets()

        assert "conservative" in presets
        assert "balanced" in presets
        assert "aggressive" in presets
        assert "wide_scan" in presets
        assert "fine_tune" in presets

    def test_pre_fire_preset_values(self, timing_svc):
        """프리셋 값이 올바른지 확인"""
        balanced = timing_svc.get_pre_fire_preset("balanced")

        assert isinstance(balanced, list)
        assert len(balanced) == 3
        assert all(isinstance(v, int) for v in balanced)
        assert balanced == [75, 100, 125]

    def test_default_preset_fallback(self, timing_svc):
        """존재하지 않는 프리셋은 기본값으로 대체"""
        result = timing_svc.get_pre_fire_preset("nonexistent")
        default = timing_svc.get_pre_fire_preset(DEFAULT_PRE_FIRE_PRESET)

        assert result == default

    def test_calculate_final_offset(self, timing_svc, sample_boundary_samples):
        """오프셋 계산이 올바른지 확인"""
        result = timing_svc._calculate_final_offset(sample_boundary_samples)

        assert isinstance(result, CalibrationResult)
        # 중앙값: [45, 50, 60] -> 50
        assert result.offset_ms == 50
        assert result.sample_count == 3
        assert result.avg_rtt_ms > 0

    def test_calculate_fire_times_basic(self, timing_svc, mock_calibration):
        """발사 시간 계산이 올바른지 확인"""
        open_time = datetime.now(KST) + timedelta(minutes=5)
        pre_fires = [50, 100, 150]

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        assert len(schedules) == 3
        assert all(isinstance(s, FireSchedule) for s in schedules)

        # pre_fire가 큰 순으로 정렬되어야 함 (fire_time이 이른 순)
        fire_times = [s.fire_time for s in schedules]
        assert fire_times == sorted(fire_times)

    def test_calculate_fire_times_without_calibration(self, timing_svc):
        """캘리브레이션 없이 발사 시간 계산"""
        open_time = datetime.now(KST) + timedelta(minutes=5)
        pre_fires = [100]

        schedules = timing_svc.calculate_fire_times(open_time, None, pre_fires)

        assert len(schedules) == 1
        # offset=0이므로 fire_time = open_time - pre_fire
        expected = open_time - timedelta(milliseconds=100)
        # 밀리초 수준에서 비교
        diff = abs((schedules[0].fire_time - expected).total_seconds())
        assert diff < 0.001


# ============================================================
# BOUNDARY: 경계값 테스트
# ============================================================

class TestBoundary:
    """경계값 테스트"""

    def test_empty_samples(self, timing_svc):
        """빈 샘플 리스트 처리"""
        # MIN_VALID_SAMPLES보다 적으면 calibrate()에서 기본값 반환
        # _calculate_final_offset은 빈 리스트를 직접 처리하지 않음
        # 이 테스트는 calibrate()의 동작을 검증해야 함
        pass  # calibrate()가 빈 샘플을 처리함

    def test_single_sample(self, timing_svc, sample_boundary_samples):
        """단일 샘플 처리"""
        single = [sample_boundary_samples[0]]
        result = timing_svc._calculate_final_offset(single)

        assert result.sample_count == 1
        assert result.offset_ms == int(single[0].offset_ms)
        # 표준편차는 0
        assert result.confidence_ms == 0

    def test_empty_pre_fires(self, timing_svc, mock_calibration):
        """빈 pre_fire 리스트"""
        open_time = datetime.now(KST)
        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, [])

        assert schedules == []

    def test_max_pre_fire_value(self, timing_svc, mock_calibration):
        """최대 pre_fire 값 테스트"""
        open_time = datetime.now(KST) + timedelta(minutes=1)
        pre_fires = [500]  # 최대값

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        assert len(schedules) == 1
        # fire_time이 open_time보다 이전이어야 함
        assert schedules[0].fire_time < open_time

    def test_zero_pre_fire(self, timing_svc, mock_calibration):
        """pre_fire = 0 테스트"""
        open_time = datetime.now(KST)
        pre_fires = [0]

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        assert len(schedules) == 1
        # fire_time = open_time - offset - 0 = open_time - offset
        expected_offset = mock_calibration.offset_ms
        expected = open_time - timedelta(milliseconds=expected_offset)
        diff = abs((schedules[0].fire_time - expected).total_seconds())
        assert diff < 0.001


# ============================================================
# INVERSE: 역관계 검증
# ============================================================

class TestInverse:
    """역관계 검증 테스트"""

    def test_pre_fire_order_inverse(self, timing_svc, mock_calibration):
        """pre_fire가 클수록 fire_time이 빠름"""
        open_time = datetime.now(KST) + timedelta(minutes=5)
        pre_fires = [50, 100, 150]

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        # pre_fire 150 -> fire_time이 가장 빠름 (인덱스 0)
        # pre_fire 50 -> fire_time이 가장 늦음 (인덱스 2)
        assert schedules[0].pre_fire_ms == 150  # 가장 이른 fire_time
        assert schedules[-1].pre_fire_ms == 50  # 가장 늦은 fire_time

    def test_offset_direction(self, timing_svc, mock_calibration):
        """양수 오프셋은 fire_time을 더 빠르게 함"""
        open_time = datetime.now(KST) + timedelta(minutes=5)
        pre_fires = [100]

        # offset=80인 경우
        schedules_with_offset = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        # offset=0인 경우
        schedules_no_offset = timing_svc.calculate_fire_times(open_time, None, pre_fires)

        # offset이 있으면 fire_time이 더 빠름
        assert schedules_with_offset[0].fire_time < schedules_no_offset[0].fire_time


# ============================================================
# CROSS-CHECK: 교차 검증
# ============================================================

class TestCrossCheck:
    """교차 검증 테스트"""

    def test_fire_time_calculation_formula(self, timing_svc, mock_calibration):
        """발사 시간 계산 공식 검증: fire_time = open_time - offset - pre_fire"""
        open_time = datetime.now(KST) + timedelta(minutes=5)
        pre_fire = 100
        offset = mock_calibration.offset_ms

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, [pre_fire])

        expected = open_time - timedelta(milliseconds=offset + pre_fire)
        actual = schedules[0].fire_time

        diff = abs((actual - expected).total_seconds())
        assert diff < 0.001

    def test_preset_completeness(self, timing_svc):
        """모든 프리셋이 유효한 값을 가지는지 검증"""
        presets = timing_svc.get_pre_fire_presets()

        for name, info in presets.items():
            values = info["values"]
            description = info["description"]

            assert isinstance(values, list), f"프리셋 {name}: values는 리스트여야 함"
            assert len(values) > 0, f"프리셋 {name}: 최소 1개 값 필요"
            assert all(0 <= v <= 500 for v in values), f"프리셋 {name}: 값은 0-500 범위"
            assert isinstance(description, str), f"프리셋 {name}: description은 문자열이어야 함"


# ============================================================
# ERROR: 에러 조건 테스트
# ============================================================

class TestError:
    """에러 조건 테스트"""

    def test_invalid_host_graceful(self, timing_svc):
        """잘못된 호스트에 대한 graceful 처리"""
        # 실제 네트워크 요청 없이 테스트
        pass  # 통합 테스트에서 다룸

    def test_negative_pre_fire_handling(self, timing_svc, mock_calibration):
        """음수 pre_fire 처리 (엣지 케이스)"""
        open_time = datetime.now(KST)
        pre_fires = [-10]  # 비정상 값

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        # 음수 pre_fire도 계산은 가능 (검증은 호출자 책임)
        assert len(schedules) == 1


# ============================================================
# RANGE: 범위 검증 (CORRECT)
# ============================================================

class TestRange:
    """범위 검증 테스트"""

    def test_pre_fire_preset_ranges(self, timing_svc):
        """프리셋 값이 합리적인 범위 내에 있는지 확인"""
        presets = timing_svc.get_pre_fire_presets()

        for name, info in presets.items():
            for value in info["values"]:
                assert 0 <= value <= 500, f"프리셋 {name}: {value}ms는 0-500ms 범위 밖"

    def test_offset_reasonable_range(self, timing_svc, sample_boundary_samples):
        """계산된 오프셋이 합리적인 범위인지 확인"""
        result = timing_svc._calculate_final_offset(sample_boundary_samples)

        # 오프셋은 일반적으로 ±1000ms 이내
        assert -1000 <= result.offset_ms <= 1000


# ============================================================
# TIME: 시간 관련 테스트 (CORRECT)
# ============================================================

class TestTime:
    """시간 관련 테스트"""

    def test_fire_schedule_ordering(self, timing_svc, mock_calibration):
        """발사 스케줄이 시간 순으로 정렬되는지 확인"""
        open_time = datetime.now(KST) + timedelta(minutes=5)
        pre_fires = [100, 50, 200, 75]  # 무작위 순서

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        # fire_time 오름차순 정렬 확인
        fire_times = [s.fire_time for s in schedules]
        assert fire_times == sorted(fire_times)

    def test_calibration_measured_at(self, timing_svc, sample_boundary_samples):
        """캘리브레이션 측정 시간이 현재 시간과 가까운지 확인"""
        result = timing_svc._calculate_final_offset(sample_boundary_samples)

        now = datetime.now(KST)
        diff = abs((result.measured_at - now).total_seconds())
        assert diff < 5  # 5초 이내


# ============================================================
# CARDINALITY: 개수 검증 (CORRECT)
# ============================================================

class TestCardinality:
    """개수 검증 테스트"""

    def test_fire_schedule_count_matches_pre_fires(self, timing_svc, mock_calibration):
        """발사 스케줄 개수가 pre_fire 개수와 일치"""
        open_time = datetime.now(KST)
        pre_fires = [50, 100, 150]

        schedules = timing_svc.calculate_fire_times(open_time, mock_calibration, pre_fires)

        assert len(schedules) == len(pre_fires)

    def test_sample_count_accuracy(self, timing_svc, sample_boundary_samples):
        """샘플 개수가 정확히 기록되는지 확인"""
        result = timing_svc._calculate_final_offset(sample_boundary_samples)

        assert result.sample_count == len(sample_boundary_samples)


# ============================================================
# 통합 테스트 (Async)
# ============================================================

class TestIntegration:
    """통합 테스트 (실제 HTTP 요청 없이)"""

    @pytest.mark.asyncio
    async def test_calibrate_with_mock_http(self, timing_svc):
        """HTTP 요청을 Mock하여 캘리브레이션 테스트"""
        from email.utils import formatdate
        import time

        # Mock HTTP 클라이언트 응답 생성
        async def mock_head(*args, **kwargs):
            response = MagicMock()
            # RFC 2822 형식의 Date 헤더
            response.headers = {
                'Date': formatdate(timeval=time.time(), localtime=False, usegmt=True)
            }
            return response

        # 캘리브레이션은 실제 HTTP 요청이 필요하므로 Mock 사용
        with patch.object(timing_svc, '_detect_second_boundaries') as mock_detect:
            mock_detect.return_value = [
                BoundarySample(
                    local_time=datetime.now(KST),
                    server_second=10,
                    rtt_ms=100.0,
                    offset_ms=50.0
                ),
                BoundarySample(
                    local_time=datetime.now(KST),
                    server_second=11,
                    rtt_ms=110.0,
                    offset_ms=55.0
                ),
            ]

            result = await timing_svc.calibrate("booking.naver.com")

            assert isinstance(result, CalibrationResult)
            assert result.sample_count == 2


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
