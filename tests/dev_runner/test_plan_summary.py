"""
plan_service._extract_summary 단위 테스트
"""
import pytest
from pathlib import Path
from unittest.mock import patch
from app.modules.dev_runner.services.plan_service import PlanService


CONTENT_WITH_SUMMARY = """\
# 테스트 Plan

## 배경 및 요약

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

## 배경 및 요약

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

## 배경 및 요약

원본 파일에만 있는 요약입니다.

## Phase 1: 구현
"""


def test_parse_summary_RIGHT():
    """## 배경 및 요약 섹션이 있는 파일에서 요약 텍스트가 정확히 추출된다."""
    result = PlanService._extract_summary(CONTENT_WITH_SUMMARY)
    assert result is not None
    assert "이것은 테스트 요약입니다." in result
    assert "두 번째 줄도 있습니다." in result


def test_parse_summary_MISSING():
    """## 배경 및 요약 섹션이 없으면 None을 반환한다."""
    result = PlanService._extract_summary(CONTENT_NO_SUMMARY)
    assert result is None


def test_parse_summary_BOUNDARY_empty_lines():
    """헤더 다음에 빈 줄만 있고 텍스트가 없으면 None을 반환한다."""
    result = PlanService._extract_summary(CONTENT_EMPTY_SUMMARY)
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
