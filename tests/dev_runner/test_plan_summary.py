"""
plan_service._extract_summary + list_plans summary 단위 테스트
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from app.modules.dev_runner.services.plan_service import PlanService


CONTENT_WITH_SUMMARY = """\
# 테스트 Plan

## 요약

이것은 테스트 요약입니다.
두 번째 줄도 있습니다.

## Phase 1: 구현

1. [ ] **작업 1**
"""

CONTENT_NO_SUMMARY = """\
# 테스트 Plan

## Phase 1: 구현

1. [ ] **작업 1**
"""

CONTENT_EMPTY_SUMMARY = """\
# 테스트 Plan

## 요약

## Phase 1: 구현

1. [ ] **작업 1**
"""

CONTENT_TODO_NO_SUMMARY = """\
# 테스트 Plan — TODO

## Phase 1: 구현

1. [ ] **작업 1**
"""

CONTENT_ORIG_WITH_SUMMARY = """\
# 테스트 Plan

## 요약

원본 파일에만 있는 요약입니다.

## Phase 1: 구현
"""


def test_parse_summary_RIGHT():
    """## 요약 섹션이 있는 파일에서 요약 텍스트가 정확히 추출된다."""
    result = PlanService._extract_summary(CONTENT_WITH_SUMMARY)
    assert result is not None
    assert "이것은 테스트 요약입니다." in result
    assert "두 번째 줄도 있습니다." in result


def test_parse_summary_MISSING():
    """## 요약 섹션이 없으면 None을 반환한다."""
    result = PlanService._extract_summary(CONTENT_NO_SUMMARY)
    assert result is None


def test_parse_summary_BOUNDARY_empty_lines():
    """헤더 다음에 빈 줄만 있고 텍스트가 없으면 None을 반환한다."""
    result = PlanService._extract_summary(CONTENT_EMPTY_SUMMARY)
    assert result is None


CONTENT_BLOCKQUOTE_SUMMARY = """\
# 테스트 Plan

> 작성일: 2026-02-27
> 상태: 초안
> 요약: 블록쿼트 포맷의 요약 텍스트입니다.

---

## 개요

개요 섹션 본문입니다.
"""

CONTENT_BLOCKQUOTE_WITH_BACKTICK = """\
# 테스트 Plan

> 요약: `get_plan_progress` 정규식이 번호 목록 직접 체크박스를 인식하지 못해 오류 발생.

## 개요
"""

CONTENT_BLOCKQUOTE_EMPTY = """\
# 테스트 Plan

> 요약:

## 개요

개요 섹션 텍스트입니다.
"""

CONTENT_개요_SECTION = """\
# 테스트 Plan

## 개요

개요 첫 번째 단락 텍스트입니다.

개요 두 번째 단락 — 이건 포함 안 됨.

## TODO
"""

CONTENT_개요_CODEBLOCK_ONLY = """\
# 테스트 Plan

## 개요

```python
# 코드블럭만 있는 경우
x = 1
```

## TODO
"""

CONTENT_BOTH_BLOCKQUOTE_AND_개요 = """\
# 테스트 Plan

> 요약: 블록쿼트 요약이 우선합니다.

## 개요

개요 섹션 텍스트입니다.
"""


def test_extract_summary_blockquote_RIGHT():
    """`> 요약: 텍스트` 포맷에서 텍스트를 정확히 추출한다."""
    result = PlanService._extract_summary(CONTENT_BLOCKQUOTE_SUMMARY)
    assert result == "블록쿼트 포맷의 요약 텍스트입니다."


def test_extract_summary_blockquote_with_backtick_RIGHT():
    """`> 요약:` 뒤에 백틱 인라인 코드가 있어도 그대로 추출한다."""
    result = PlanService._extract_summary(CONTENT_BLOCKQUOTE_WITH_BACKTICK)
    assert result is not None
    assert "`get_plan_progress`" in result


def test_extract_summary_blockquote_empty_BOUNDARY():
    """`> 요약:` 뒤 값이 없으면 다음 포맷(## 개요)으로 fallback한다."""
    result = PlanService._extract_summary(CONTENT_BLOCKQUOTE_EMPTY)
    assert result == "개요 섹션 텍스트입니다."


def test_extract_summary_section_개요_RIGHT():
    """`## 개요` 섹션의 첫 단락만 추출한다."""
    result = PlanService._extract_summary(CONTENT_개요_SECTION)
    assert result == "개요 첫 번째 단락 텍스트입니다."
    assert "두 번째 단락" not in result


def test_extract_summary_section_개요_skips_codeblock_RIGHT():
    """`## 개요` 아래 코드블럭만 있으면 None을 반환한다."""
    result = PlanService._extract_summary(CONTENT_개요_CODEBLOCK_ONLY)
    assert result is None


def test_extract_summary_priority_RIGHT():
    """`> 요약:`과 `## 개요` 모두 있을 때 `> 요약:`이 우선한다."""
    result = PlanService._extract_summary(CONTENT_BOTH_BLOCKQUOTE_AND_개요)
    assert result == "블록쿼트 요약이 우선합니다."


def test_extract_summary_legacy_배경및요약_RIGHT():
    """구형 `## 요약` 포맷에서 여전히 요약을 추출한다."""
    result = PlanService._extract_summary(CONTENT_WITH_SUMMARY)
    assert result is not None
    assert "이것은 테스트 요약입니다." in result


def test_extract_summary_none_BOUNDARY():
    """어떤 포맷도 없으면 None을 반환한다."""
    result = PlanService._extract_summary(CONTENT_NO_SUMMARY)
    assert result is None


def test_parse_summary_TODO_OVERRIDE(tmp_path):
    """_todo.md에 요약 섹션이 없고 원본에만 있을 때 원본에서 fallback 추출한다."""
    # 원본 plan 파일 생성
    orig = tmp_path / "2026-02-26_test.md"
    orig.write_text(CONTENT_ORIG_WITH_SUMMARY, encoding="utf-8")

    # _todo.md 파일 (요약 없음)
    todo = tmp_path / "2026-02-26_test_todo.md"
    todo.write_text(CONTENT_TODO_NO_SUMMARY, encoding="utf-8")

    service = PlanService()
    detail = service.parse_plan_items(orig)

    assert detail.summary is not None
    assert "원본 파일에만 있는 요약" in detail.summary

# ============================================================
# 신규 TC: list_plans summary 포함 확인 + generate_summary
# ============================================================

def test_plan_service_extract_summary_right():
    """R: > 요약: 패턴이 있는 content에서 정상 summary 문자열 추출."""
    content = "# Plan\n\n> 요약: 이것은 요약입니다.\n\n## 내용\n"
    result = PlanService._extract_summary(content)
    assert result == "이것은 요약입니다."


def test_plan_service_extract_summary_boundary_empty():
    """B: 요약 헤더가 없는 plan content에서 None 반환."""
    content = "# Plan\n\n## Phase 1\n\n1. [ ] 작업\n"
    result = PlanService._extract_summary(content)
    assert result is None


def test_plan_service_extract_summary_error_malformed():
    """E: 빈 문자열 및 None에 준하는 content 처리 — 예외 없이 None 반환."""
    assert PlanService._extract_summary("") is None
    assert PlanService._extract_summary("   ") is None


def test_plan_service_list_plans_includes_summary(tmp_path):
    """R: _scan_all_plans() 결과의 각 PlanFileResponse에 summary 필드 포함."""
    plan_file = tmp_path / "2026-03-08_test_plan.md"
    plan_file.write_text(
        "# Test Plan\n\n> 요약: 테스트 요약 텍스트\n\n## Phase 1\n\n- [ ] 작업\n",
        encoding="utf-8",
    )

    service = PlanService()
    service._registered_paths = [{"path": str(tmp_path), "type": "plan"}]
    results = service._scan_all_plans(include_ignored=True)

    matching = [r for r in results if r.filename == plan_file.name]
    assert len(matching) == 1
    assert matching[0].summary == "테스트 요약 텍스트"


def test_plan_service_list_plans_no_summary_returns_none(tmp_path):
    """B: 요약 없는 plan에서 summary 필드가 None."""
    plan_file = tmp_path / "2026-03-08_no_summary.md"
    plan_file.write_text(
        "# No Summary Plan\n\n## Phase 1\n\n- [ ] 작업\n",
        encoding="utf-8",
    )

    service = PlanService()
    service._registered_paths = [{"path": str(tmp_path), "type": "plan"}]
    results = service._scan_all_plans(include_ignored=True)

    matching = [r for r in results if r.filename == plan_file.name]
    assert len(matching) == 1
    assert matching[0].summary is None


def test_insert_summary_to_plan_right(tmp_path):
    """R: _insert_summary_to_plan이 > 요약: 줄을 삽입한다."""
    plan_file = tmp_path / "test.md"
    plan_file.write_text("# Plan\n\n> 상태: 초안\n\n## 내용\n", encoding="utf-8")

    service = PlanService()
    service._insert_summary_to_plan(plan_file, "새 요약 텍스트")

    content = plan_file.read_text(encoding="utf-8")
    assert "> 요약: 새 요약 텍스트" in content


def test_insert_summary_to_plan_boundary_already_exists(tmp_path):
    """B: 이미 > 요약: 있을 때 기존 줄을 교체한다."""
    plan_file = tmp_path / "test.md"
    plan_file.write_text("# Plan\n\n> 요약: 기존 요약\n\n## 내용\n", encoding="utf-8")

    service = PlanService()
    service._insert_summary_to_plan(plan_file, "업데이트된 요약")

    content = plan_file.read_text(encoding="utf-8")
    assert "> 요약: 업데이트된 요약" in content
    assert "기존 요약" not in content
    assert content.count("> 요약:") == 1


def test_generate_summary_error_file_not_found():
    """E: 존재하지 않는 plan 경로 시 FileNotFoundError 발생 (read_text에서)."""
    import asyncio

    service = PlanService()
    non_existent = Path("/nonexistent/path/plan.md")
    mock_db = MagicMock()

    with pytest.raises(FileNotFoundError):
        asyncio.run(service.generate_summary(non_existent, mock_db))
