"""
NssmService 단위 테스트
"""
import pytest


def test_nssm_service_import():
    """R(Right): NssmService import 성공"""
    from app.modules.system.services.nssm_service import NssmService
    assert NssmService is not None


def test_unregistered_sentinel_shape():
    """R(Right): _unregistered_sentinel 반환 shape 검증"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    result = svc._unregistered_sentinel("test-prefix", "my-project")
    assert result["name"] == "test-prefix"
    assert result["project"] == "my-project"
    assert result["status"] == "Unregistered"
    assert result["start_type"] == "N/A"
    assert "미등록" in result["display_name"]


def test_normalize_status_int():
    """R(Right): 정수 상태 → 문자열 변환"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    assert svc._normalize_status(4) == "Running"
    assert svc._normalize_status(1) == "Stopped"
    assert svc._normalize_status(2) == "StartPending"
    assert svc._normalize_status(3) == "StopPending"


def test_normalize_status_boundary():
    """B(Boundary): None, 0, 5 등 매핑 외 값 → 'Unknown'"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    assert svc._normalize_status(None) == "Unknown"
    assert svc._normalize_status(0) == "Unknown"
    assert svc._normalize_status(5) == "Unknown"
    assert svc._normalize_status(99) == "Unknown"


def test_normalize_status_string():
    """R(Right): 문자열 상태는 그대로 반환"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    assert svc._normalize_status("Running") == "Running"
    assert svc._normalize_status("Stopped") == "Stopped"
