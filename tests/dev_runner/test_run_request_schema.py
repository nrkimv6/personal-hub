"""RunStatusResponse / PlanFileResponse 스키마 단위 테스트 — claim 필드 직렬화 검증

대상 소스: app/modules/dev_runner/schemas.py
RIGHT-BICEP: Right(정상), Boundary(빈/None), Error(타입 불일치)
"""
import json
import pytest
from app.modules.dev_runner.schemas import RunStatusResponse, PlanFileResponse


# ========== RunStatusResponse — claim 필드 ==========

class TestRunStatusResponseClaimFields:

    def test_R_claim_fields_omitted_by_default(self):
        """R: claim 필드 미지정 시 None으로 기본화"""
        resp = RunStatusResponse(running=True)
        assert resp.claim_id is None
        assert resp.claim_state is None
        assert resp.claim_owner_runner_id is None
        assert resp.claim_message is None

    def test_R_claim_fields_set_correctly(self):
        """R: claim 필드 지정 시 값이 정확히 설정된다"""
        resp = RunStatusResponse(
            running=True,
            claim_id="abc-123",
            claim_state="queued",
            claim_owner_runner_id="runner-001",
            claim_message="plan already claimed",
        )
        assert resp.claim_id == "abc-123"
        assert resp.claim_state == "queued"
        assert resp.claim_owner_runner_id == "runner-001"
        assert resp.claim_message == "plan already claimed"

    def test_R_serializes_to_json_with_nulls(self):
        """R: JSON 직렬화 시 None 필드가 null로 포함된다"""
        resp = RunStatusResponse(running=False)
        data = resp.model_dump()
        assert "claim_id" in data
        assert data["claim_id"] is None

    def test_R_serializes_with_claim_values(self):
        """R: claim 값이 있을 때 JSON 직렬화 정상"""
        resp = RunStatusResponse(
            running=True,
            claim_id="cid-xyz",
            claim_state="active",
        )
        raw = json.dumps(resp.model_dump())
        parsed = json.loads(raw)
        assert parsed["claim_id"] == "cid-xyz"
        assert parsed["claim_state"] == "active"

    def test_B_claim_state_empty_string(self):
        """B: claim_state가 빈 문자열이어도 직렬화/역직렬화가 깨지지 않는다"""
        resp = RunStatusResponse(running=True, claim_state="")
        data = resp.model_dump()
        assert data["claim_state"] == ""

    def test_B_all_claim_fields_none(self):
        """B: 모든 claim 필드 None → 정상 직렬화"""
        resp = RunStatusResponse(
            running=True,
            claim_id=None,
            claim_state=None,
            claim_owner_runner_id=None,
            claim_message=None,
        )
        data = resp.model_dump()
        assert data["claim_id"] is None
        assert data["claim_state"] is None

    def test_Co_non_claim_fields_unaffected(self):
        """Co: claim 필드 추가가 runner_id, attached 등 기존 필드에 영향 없다"""
        resp = RunStatusResponse(
            running=True,
            runner_id="r-abc",
            attached=True,
            claim_id="c-001",
        )
        assert resp.runner_id == "r-abc"
        assert resp.attached is True
        assert resp.claim_id == "c-001"


# ========== PlanFileResponse — execution_claim 필드 ==========

class TestPlanFileResponseClaimFields:

    _BASE = dict(path="docs/plan/test.md", filename="test.md", status="검토완료", source="common")

    def test_R_claim_fields_omitted_by_default(self):
        """R: claim 필드 미지정 시 None + False"""
        resp = PlanFileResponse(**self._BASE)
        assert resp.execution_claim_id is None
        assert resp.execution_claim_state is None
        assert resp.execution_claim_runner_id is None
        assert resp.execution_claim_stale is False

    def test_R_claim_fields_set_correctly(self):
        """R: claim 필드 지정 시 값이 정확히 반영된다"""
        resp = PlanFileResponse(
            **self._BASE,
            execution_claim_id="claim-abc",
            execution_claim_state="active",
            execution_claim_runner_id="runner-xyz",
            execution_claim_stale=True,
        )
        assert resp.execution_claim_id == "claim-abc"
        assert resp.execution_claim_state == "active"
        assert resp.execution_claim_runner_id == "runner-xyz"
        assert resp.execution_claim_stale is True

    def test_R_serializes_claim_to_json(self):
        """R: JSON 직렬화 시 claim 필드가 포함된다"""
        resp = PlanFileResponse(
            **self._BASE,
            execution_claim_id="cid-1",
            execution_claim_state="queued",
        )
        raw = json.dumps(resp.model_dump())
        parsed = json.loads(raw)
        assert parsed["execution_claim_id"] == "cid-1"
        assert parsed["execution_claim_state"] == "queued"
        assert parsed["execution_claim_stale"] is False

    def test_B_stale_defaults_to_false_not_none(self):
        """B: execution_claim_stale는 bool 기본값 False (None 아님)"""
        resp = PlanFileResponse(**self._BASE)
        # bool이어야 한다 (None이면 프론트 타입 에러 가능)
        assert isinstance(resp.execution_claim_stale, bool)

    def test_B_claim_state_queued_keyword(self):
        """B: execution_claim_state='queued' 값 그대로 통과"""
        resp = PlanFileResponse(**self._BASE, execution_claim_state="queued")
        assert resp.execution_claim_state == "queued"

    def test_B_claim_state_stale_keyword(self):
        """B: execution_claim_state='stale' 값 그대로 통과"""
        resp = PlanFileResponse(**self._BASE, execution_claim_state="stale")
        assert resp.execution_claim_state == "stale"

    def test_Co_existing_fields_unaffected_by_claim(self):
        """Co: claim 필드 추가 후 path, status, branch 등 기존 필드가 정상이다"""
        resp = PlanFileResponse(
            **self._BASE,
            branch="impl/test",
            execution_claim_id="c-001",
        )
        assert resp.path == "docs/plan/test.md"
        assert resp.status == "검토완료"
        assert resp.branch == "impl/test"
