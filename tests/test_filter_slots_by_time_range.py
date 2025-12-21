"""
filter_slots_by_time_range 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트

테스트 대상:
- filter_slots_by_time_range: 슬롯 필터링 통합 함수

리팩토링: 3곳에 중복되어 있던 함수를 booking_utils.py로 통합
"""

import pytest
import sys
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.naver_booking.services.booking_utils import filter_slots_by_time_range


# ============================================================
# 1. Right: 기본 기능 테스트
# ============================================================

class TestFilterSlotsBasic:
    """기본 필터링 기능 테스트"""

    def test_filter_slots_24h_format(self):
        """24시간 형식 슬롯 필터링"""
        slots = [
            "2025-11-30 09:00:00 (2매)",
            "2025-11-30 11:00:00 (1매)",
            "2025-11-30 14:00:00 (3매)",
            "2025-11-30 18:00:00 (1매)",
        ]
        result = filter_slots_by_time_range(slots, "10:00-15:00")

        assert len(result) == 2
        assert "2025-11-30 11:00:00 (1매)" in result
        assert "2025-11-30 14:00:00 (3매)" in result
        assert "2025-11-30 09:00:00 (2매)" not in result
        assert "2025-11-30 18:00:00 (1매)" not in result

    def test_filter_slots_ampm_korean(self):
        """오전/오후 한글 형식 슬롯 필터링"""
        slots = [
            "오전 9:00 (2매)",
            "오전 11:00 (1매)",
            "오후 2:00 (3매)",
            "오후 6:00 (1매)",
        ]
        result = filter_slots_by_time_range(slots, "10:00-15:00")

        assert len(result) == 2
        assert "오전 11:00 (1매)" in result
        assert "오후 2:00 (3매)" in result

    def test_filter_slots_ampm_english(self):
        """AM/PM 영어 형식 슬롯 필터링"""
        slots = [
            "AM 9:00 (2매)",
            "AM 11:00 (1매)",
            "PM 2:00 (3매)",
            "PM 6:00 (1매)",
        ]
        result = filter_slots_by_time_range(slots, "10:00-15:00")

        assert len(result) == 2
        assert "AM 11:00 (1매)" in result
        assert "PM 2:00 (3매)" in result

    def test_no_filter_when_no_time_range(self):
        """time_range가 None이면 전체 반환"""
        slots = ["09:00", "12:00", "18:00"]
        result = filter_slots_by_time_range(slots, None)

        assert result == slots

    def test_no_filter_when_empty_time_range(self):
        """time_range가 빈 문자열이면 전체 반환"""
        slots = ["09:00", "12:00", "18:00"]
        result = filter_slots_by_time_range(slots, "")

        assert result == slots

    def test_empty_slots_returns_empty(self):
        """빈 슬롯 리스트면 빈 리스트 반환"""
        result = filter_slots_by_time_range([], "10:00-15:00")

        assert result == []


# ============================================================
# 2. Boundary: 경계값 테스트
# ============================================================

class TestFilterSlotsBoundary:
    """경계값 테스트"""

    def test_exact_start_time_included(self):
        """시작 시간과 정확히 일치하는 슬롯 포함"""
        slots = ["10:00", "11:00", "12:00"]
        result = filter_slots_by_time_range(slots, "10:00-12:00")

        assert "10:00" in result

    def test_exact_end_time_included(self):
        """종료 시간과 정확히 일치하는 슬롯 포함"""
        slots = ["10:00", "11:00", "12:00"]
        result = filter_slots_by_time_range(slots, "10:00-12:00")

        assert "12:00" in result

    def test_exact_time_match_single_time(self):
        """정확히 일치하는 시간만 (예: 12:00-12:00)"""
        slots = ["11:00", "12:00", "13:00"]
        result = filter_slots_by_time_range(slots, "12:00-12:00")

        assert len(result) == 1
        assert "12:00" in result

    def test_24_00_treated_as_23_59(self):
        """24:00은 23:59로 처리"""
        slots = ["22:00", "23:00", "23:30", "23:59"]
        result = filter_slots_by_time_range(slots, "22:00-24:00")

        assert len(result) == 4

    def test_midnight_time_range(self):
        """야간 시간 범위 (예: 22:00-06:00)"""
        slots = ["23:00", "00:00", "01:00", "05:00", "06:00", "12:00"]
        result = filter_slots_by_time_range(slots, "22:00-06:00")

        assert "23:00" in result
        assert "00:00" in result
        assert "01:00" in result
        assert "05:00" in result
        assert "06:00" in result
        assert "12:00" not in result


# ============================================================
# 3. Error: 에러 조건 테스트
# ============================================================

class TestFilterSlotsError:
    """에러 조건 테스트"""

    def test_invalid_time_range_format_returns_all(self):
        """잘못된 시간 범위 형식이면 전체 반환"""
        slots = ["09:00", "12:00", "18:00"]
        result = filter_slots_by_time_range(slots, "invalid")

        assert result == slots

    def test_partial_time_range_format_returns_all(self):
        """불완전한 시간 범위 형식이면 전체 반환"""
        slots = ["09:00", "12:00", "18:00"]
        result = filter_slots_by_time_range(slots, "10:00")  # '-' 없음

        assert result == slots

    def test_invalid_time_value_returns_all(self):
        """잘못된 시간 값이면 전체 반환"""
        slots = ["09:00", "12:00", "18:00"]
        result = filter_slots_by_time_range(slots, "25:00-30:00")

        assert result == slots

    def test_slot_without_time_skipped(self):
        """시간 정보가 없는 슬롯은 스킵"""
        slots = ["날짜만", "09:00", "텍스트만"]
        result = filter_slots_by_time_range(slots, "08:00-10:00")

        assert len(result) == 1
        assert "09:00" in result


# ============================================================
# 4. Cross-check: 교차 검증
# ============================================================

class TestFilterSlotsCrossCheck:
    """교차 검증 테스트"""

    def test_ampm_12_hour_conversion(self):
        """오전/오후 12시간 변환 검증"""
        slots_korean = ["오전 12:00", "오후 12:00", "오전 9:00", "오후 9:00"]
        slots_24h = ["00:00", "12:00", "09:00", "21:00"]

        result_korean = filter_slots_by_time_range(slots_korean, "11:00-13:00")
        result_24h = filter_slots_by_time_range(slots_24h, "11:00-13:00")

        # 둘 다 12:00만 포함해야 함
        assert len(result_korean) == 1
        assert len(result_24h) == 1
        assert "오후 12:00" in result_korean
        assert "12:00" in result_24h

    def test_filter_and_count_consistency(self):
        """필터링된 개수와 제외된 개수의 합이 원본 개수와 같아야 함"""
        slots = ["09:00", "10:00", "11:00", "12:00", "13:00"]
        filtered = filter_slots_by_time_range(slots, "10:00-12:00")

        # 포함: 10:00, 11:00, 12:00 (3개)
        # 제외: 09:00, 13:00 (2개)
        assert len(filtered) + 2 == len(slots)
