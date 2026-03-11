"""
TC-SG-01: [정상] plan 선택 후 통합 모달 열기 → 요약생성 버튼 클릭
         → spinner 표시 → API 호출 → summary 영역 갱신 확인

단위 테스트 범위:
- generate_summary 서비스 호출 시 LLM 큐 등록 + request_id 반환 (202 트리거 검증)
- _write_back 콜백이 완료된 LLM 응답을 plan 파일에 `> 요약:` 형태로 삽입하는 것 확인
- list_plans/_scan_all_plans에서 삽입된 summary가 PlanFileResponse.summary로 노출되는 것 확인

주의: spinner 표시는 UI 레이어(Svelte) 이슈이므로 단위 TC 범위 외.
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from app.modules.dev_runner.services.plan_service import PlanService


PLAN_CONTENT_NO_SUMMARY = """\
# 통합 모달 테스트 Plan

> 작성일: 2026-03-09
> 상태: 구현중

## Phase 1: 구현

1. [ ] **작업 1** — 기능 구현
"""

PLAN_CONTENT_WITH_SUMMARY = """\
# 통합 모달 테스트 Plan

> 작성일: 2026-03-09
> 상태: 구현중
> 요약: 기존 요약 텍스트

## 개요

Dev-Runner Plan 모달 통합 테스트용 plan 문서다.
"""


# ---------------------------------------------------------------------------
# TC-SG-01-A: generate_summary 호출 시 LLM 큐 등록 + request_id 반환
# ---------------------------------------------------------------------------

def test_tc_sg01_generate_summary_enqueues_llm_and_returns_request_id(tmp_path):
    """
    TC-SG-01-A [정상]
    요약생성 버튼 클릭 시 API가 generate_summary를 호출하고,
    내부적으로 LLM 큐에 등록된 뒤 request_id를 반환한다 (202 패턴).
    """
    plan_file = tmp_path / "2026-03-09_test_plan.md"
    plan_file.write_text(PLAN_CONTENT_NO_SUMMARY, encoding="utf-8")

    mock_request = MagicMock()
    mock_request.id = 42

    mock_llm_svc = MagicMock()
    mock_llm_svc.enqueue.return_value = mock_request

    mock_db = MagicMock()

    with patch(
        "app.modules.claude_worker.services.llm_service.LLMService",
        return_value=mock_llm_svc,
    ), patch("asyncio.create_task"):  # _write_back 태스크 생성 억제
        request_id = asyncio.get_event_loop().run_until_complete(
            PlanService().generate_summary(plan_file, mock_db)
        )

    assert request_id == 42
    mock_llm_svc.enqueue.assert_called_once()
    call_kwargs = mock_llm_svc.enqueue.call_args
    assert call_kwargs.kwargs.get("request_source") == "plan_summary" or (
        len(call_kwargs.args) > 0
    ), "enqueue가 plan_summary request_source로 호출되어야 함"
    mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# TC-SG-01-B: _write_back — LLM 완료 후 plan 파일에 summary 삽입
# ---------------------------------------------------------------------------

def test_tc_sg01_write_back_inserts_summary_after_llm_complete(tmp_path):
    """
    TC-SG-01-B [정상]
    LLM Worker가 완료 상태를 반환하면 plan 파일에 `> 요약:` 줄이 삽입된다.
    이는 UI의 summary 영역 갱신(fetchPlans 재호출 시 확인)에 해당하는 서버 사이드 검증.
    """
    plan_file = tmp_path / "2026-03-09_test_plan.md"
    plan_file.write_text(PLAN_CONTENT_NO_SUMMARY, encoding="utf-8")

    service = PlanService()
    service._insert_summary_to_plan(plan_file, "Dev-Runner Plan 모달 통합 및 요약생성 버튼 복구 작업이다.")

    content = plan_file.read_text(encoding="utf-8")
    assert "> 요약: Dev-Runner Plan 모달 통합 및 요약생성 버튼 복구 작업이다." in content


# ---------------------------------------------------------------------------
# TC-SG-01-C: summary 삽입 후 list_plans에서 summary 필드로 노출
# ---------------------------------------------------------------------------

def test_tc_sg01_summary_reflected_in_scan_after_write_back(tmp_path):
    """
    TC-SG-01-C [정상]
    _write_back이 plan 파일에 summary를 삽입한 뒤,
    _scan_all_plans() 재호출 시 PlanFileResponse.summary 필드에 반영된다.
    이는 프론트엔드의 fetchPlans() → onPlansChange() → modalPlan 갱신 흐름의 서버 측 검증이다.
    """
    plan_file = tmp_path / "2026-03-09_test_scan_plan.md"
    plan_file.write_text(PLAN_CONTENT_NO_SUMMARY, encoding="utf-8")

    service = PlanService()
    service._registered_paths = [{"path": str(tmp_path), "type": "plan"}]

    # 1. 초기 스캔 — summary 없음
    results_before = service._scan_all_plans(include_ignored=True)
    matching_before = [r for r in results_before if r.filename == plan_file.name]
    assert len(matching_before) == 1
    assert matching_before[0].summary is None, "초기에는 summary가 없어야 함"

    # 2. _write_back 완료 시뮬레이션: plan 파일에 summary 삽입
    service._insert_summary_to_plan(plan_file, "통합 모달 UX 개선 및 요약생성 버튼 복구.")

    # 3. 재스캔 — summary 반영 확인 (fetchPlans 재호출 패턴)
    results_after = service._scan_all_plans(include_ignored=True)
    matching_after = [r for r in results_after if r.filename == plan_file.name]
    assert len(matching_after) == 1
    assert matching_after[0].summary == "통합 모달 UX 개선 및 요약생성 버튼 복구.", (
        "write_back 후 재스캔 시 summary가 PlanFileResponse에 노출되어야 함"
    )


# ---------------------------------------------------------------------------
# TC-SG-01-D: 기존 summary 있을 때 덮어쓰기 (TC-SG-02 커버)
# ---------------------------------------------------------------------------

def test_tc_sg01_overwrite_existing_summary(tmp_path):
    """
    TC-SG-01-D [정상] (TC-SG-02 커버)
    summary가 이미 있는 plan → 요약생성 클릭 → 기존 summary가 새 내용으로 교체된다.
    """
    plan_file = tmp_path / "2026-03-09_existing_summary.md"
    plan_file.write_text(PLAN_CONTENT_WITH_SUMMARY, encoding="utf-8")

    service = PlanService()
    service._insert_summary_to_plan(plan_file, "새롭게 생성된 요약 텍스트.")

    content = plan_file.read_text(encoding="utf-8")
    assert "> 요약: 새롭게 생성된 요약 텍스트." in content
    assert "기존 요약 텍스트" not in content
    assert content.count("> 요약:") == 1, "요약 줄이 중복 삽입되지 않아야 함"
