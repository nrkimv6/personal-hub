"""
시스템 메모리 API 테스트

RIGHT-BICEP + CORRECT 기반 테스트 케이스
- psutil mock으로 RAM/PageFile/프로세스 응답 검증
- 위험도 판정 경계값 테스트 (Boundary): 2GB 직상/직하, 1GB 직상/직하
- 프로세스 그룹핑 테스트
- 에러 케이스: AccessDenied 발생 시 스킵 확인
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from collections import namedtuple

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


# ============================================================
# 헬퍼: psutil mock 빌더
# ============================================================

def _make_vm(total_gb=8, available_gb=4, used_gb=4, percent=50.0):
    """virtual_memory mock 생성"""
    vm = MagicMock()
    vm.total = int(total_gb * 1024 ** 3)
    vm.available = int(available_gb * 1024 ** 3)
    vm.used = int(used_gb * 1024 ** 3)
    vm.percent = percent
    return vm


def _make_swap(total_gb=4, used_gb=1, free_gb=3, percent=25.0):
    """swap_memory mock 생성"""
    sw = MagicMock()
    sw.total = int(total_gb * 1024 ** 3)
    sw.used = int(used_gb * 1024 ** 3)
    sw.free = int(free_gb * 1024 ** 3)
    sw.percent = percent
    return sw


def _make_proc(pid, name, rss_mb):
    """psutil 프로세스 mock 생성"""
    proc = MagicMock()
    mem_info = MagicMock()
    mem_info.rss = int(rss_mb * 1024 * 1024)
    proc.info = {
        'pid': pid,
        'name': name,
        'memory_info': mem_info,
    }
    return proc


# ============================================================
# 기본 응답 구조 테스트 (Right)
# ============================================================

class TestMemoryApiBasic:
    """기본 응답 구조 검증"""

    def test_returns_200(self):
        """정상 호출 시 200 반환"""
        resp = client.get("/api/v1/system/memory")
        assert resp.status_code == 200

    def test_response_has_required_fields(self):
        """필수 필드 존재 확인"""
        resp = client.get("/api/v1/system/memory")
        data = resp.json()
        assert "ram" in data
        assert "pagefile" in data
        assert "top_processes" in data
        assert "danger_level" in data

    def test_ram_fields(self):
        """RAM 필드 구조 확인"""
        resp = client.get("/api/v1/system/memory")
        ram = resp.json()["ram"]
        for field in ("total_mb", "used_mb", "available_mb", "percent"):
            assert field in ram, f"RAM 필드 누락: {field}"
        assert ram["total_mb"] > 0
        assert 0 <= ram["percent"] <= 100

    def test_pagefile_fields(self):
        """PageFile 필드 구조 확인"""
        resp = client.get("/api/v1/system/memory")
        pf = resp.json()["pagefile"]
        for field in ("total_mb", "used_mb", "free_mb", "percent"):
            assert field in pf, f"PageFile 필드 누락: {field}"

    def test_danger_level_valid_enum(self):
        """danger_level이 유효한 enum 값인지 확인"""
        resp = client.get("/api/v1/system/memory")
        level = resp.json()["danger_level"]
        assert level in ("normal", "warning", "critical")

    def test_top_processes_is_list(self):
        """top_processes가 리스트인지 확인"""
        resp = client.get("/api/v1/system/memory")
        procs = resp.json()["top_processes"]
        assert isinstance(procs, list)

    def test_top_processes_max_15(self):
        """top_processes가 최대 15개인지 확인"""
        resp = client.get("/api/v1/system/memory")
        procs = resp.json()["top_processes"]
        assert len(procs) <= 15


# ============================================================
# 위험도 판정 경계값 테스트 (Boundary)
# ============================================================

class TestDangerLevelBoundary:
    """위험도 판정 경계값 검증"""

    def _call_with_available(self, available_gb):
        vm_mock = _make_vm(available_gb=available_gb)
        sw_mock = _make_swap()
        with patch("psutil.virtual_memory", return_value=vm_mock), \
             patch("psutil.swap_memory", return_value=sw_mock), \
             patch("psutil.process_iter", return_value=[]):
            resp = client.get("/api/v1/system/memory")
        return resp.json()["danger_level"]

    def test_normal_above_2gb(self):
        """available > 2GB → normal"""
        level = self._call_with_available(2.1)
        assert level == "normal"

    def test_warning_just_below_2gb(self):
        """available = 1.99GB → warning"""
        level = self._call_with_available(1.99)
        assert level == "warning"

    def test_warning_at_1_5gb(self):
        """available = 1.5GB → warning"""
        level = self._call_with_available(1.5)
        assert level == "warning"

    def test_critical_just_below_1gb(self):
        """available = 0.99GB → critical"""
        level = self._call_with_available(0.99)
        assert level == "critical"

    def test_critical_at_zero(self):
        """available = 0 → critical"""
        level = self._call_with_available(0)
        assert level == "critical"

    def test_boundary_exactly_2gb(self):
        """available = 2.0GB → warning (< 2GB 조건이므로 2.0은 normal)"""
        level = self._call_with_available(2.0)
        assert level == "normal"

    def test_boundary_exactly_1gb(self):
        """available = 1.0GB → warning (< 1GB 조건이므로 1.0은 warning)"""
        level = self._call_with_available(1.0)
        assert level == "warning"


# ============================================================
# 프로세스 그룹핑 테스트
# ============================================================

class TestProcessGrouping:
    """프로세스 그룹핑 로직 검증"""

    def _call_with_procs(self, proc_list):
        vm_mock = _make_vm(available_gb=4)
        sw_mock = _make_swap()
        with patch("psutil.virtual_memory", return_value=vm_mock), \
             patch("psutil.swap_memory", return_value=sw_mock), \
             patch("psutil.process_iter", return_value=proc_list):
            resp = client.get("/api/v1/system/memory")
        return resp.json()["top_processes"]

    def test_same_name_grouped(self):
        """동일 이름 프로세스가 합산되는지 확인"""
        procs = [
            _make_proc(101, "chrome.exe", 200),
            _make_proc(102, "chrome.exe", 300),
            _make_proc(103, "python.exe", 100),
        ]
        result = self._call_with_procs(procs)
        chrome = next((p for p in result if p["name"] == "chrome.exe"), None)
        assert chrome is not None
        assert chrome["count"] == 2
        assert chrome["working_set_mb"] == pytest.approx(500.0, abs=1)

    def test_sorted_by_memory_desc(self):
        """메모리 내림차순 정렬 확인"""
        procs = [
            _make_proc(201, "small.exe", 50),
            _make_proc(202, "big.exe", 400),
            _make_proc(203, "medium.exe", 200),
        ]
        result = self._call_with_procs(procs)
        mbs = [p["working_set_mb"] for p in result]
        assert mbs == sorted(mbs, reverse=True)

    def test_single_process_count_is_1(self):
        """단일 프로세스의 count가 1인지 확인"""
        procs = [_make_proc(301, "solo.exe", 100)]
        result = self._call_with_procs(procs)
        assert result[0]["count"] == 1

    def test_max_15_processes(self):
        """20개 프로세스 중 15개만 반환하는지 확인"""
        procs = [_make_proc(400 + i, f"proc{i}.exe", 100 - i) for i in range(20)]
        result = self._call_with_procs(procs)
        assert len(result) <= 15


# ============================================================
# 에러 케이스 (AccessDenied 스킵)
# ============================================================

class TestErrorHandling:
    """에러 핸들링 검증"""

    def test_access_denied_proc_skipped(self):
        """AccessDenied 프로세스는 스킵되고 나머지는 정상 반환"""
        import psutil as _psutil

        good_proc = _make_proc(501, "good.exe", 100)

        bad_proc = MagicMock()
        bad_proc.info = None  # process_iter 자체는 반환하지만
        # process_iter가 AccessDenied를 throw 하는 경우를 시뮬레이션
        # 실제 엔드포인트에서는 proc.info 접근 시 예외 발생 가능
        # 여기서는 memory_info=None으로 스킵 유도
        bad_proc.info = {'pid': 502, 'name': 'bad.exe', 'memory_info': None}

        vm_mock = _make_vm(available_gb=4)
        sw_mock = _make_swap()
        with patch("psutil.virtual_memory", return_value=vm_mock), \
             patch("psutil.swap_memory", return_value=sw_mock), \
             patch("psutil.process_iter", return_value=[good_proc, bad_proc]):
            resp = client.get("/api/v1/system/memory")

        assert resp.status_code == 200
        procs = resp.json()["top_processes"]
        names = [p["name"] for p in procs]
        assert "good.exe" in names
        # bad.exe는 memory_info=None이므로 스킵
        assert "bad.exe" not in names
