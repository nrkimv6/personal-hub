"""STATUS_FIELDS 상수 정합 검증 — drift 구조적 방지 TC"""
import pytest

from app.modules.dev_runner.services.event_payload import STATUS_FIELDS, build_status_payload
from app.modules.dev_runner.services.event_routing import RUNNER_KEY_PREFIX
from tests.dev_runner.test_event_service import _status_values


class TestStatusFieldsConstant:
    def test_status_fields_B_immutable_tuple_type(self):
        """B: STATUS_FIELDS는 tuple이어야 한다 — list 변경으로 인한 부작용 차단"""
        assert isinstance(STATUS_FIELDS, tuple)
        assert len(STATUS_FIELDS) == 16

    def test_status_fields_R_build_payload_returns_all_keys(self):
        """R: build_status_payload 반환 dict는 STATUS_FIELDS 키를 모두 포함한다"""
        import fakeredis

        r = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "sf-test-01"
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:execution_count", "3")

        payload = build_status_payload(r, runner_id)
        assert payload is not None
        expected_keys = set(STATUS_FIELDS) | {"runner_id", "visible"}
        assert expected_keys.issubset(set(payload.keys()))

    def test_status_fields_E_status_values_missing_key_raises(self):
        """E: STATUS_FIELDS에 미등록 키 추가 시 AssertionError 발생 — drift 즉시 감지"""
        import tests.dev_runner.test_event_service as tes

        original = tes.STATUS_FIELDS
        tes.STATUS_FIELDS = original + ("phantom_field_xyz",)
        try:
            with pytest.raises((AssertionError, KeyError)):
                _status_values()
        finally:
            tes.STATUS_FIELDS = original
