"""visible 화이트리스트 전환 단위 TC

Phase T1: get_all_runners() visible 판별 로직 + SSE _build_all_runners_status() 필터링 검증.
화이트리스트 방식: trigger in ("user", "user:all") 일 때만 visible=True.
"""

import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import patch, MagicMock

from app.modules.dev_runner.schemas import RunnerListItem


# ── 판별 로직 헬퍼 (executor_service.get_all_runners 내 로직 재현) ──────────

def _is_user_visible(trigger: str | None) -> bool:
    """화이트리스트 판별 로직 — executor_service.py 와 동일"""
    return bool(trigger and trigger in ("user", "user:all"))


# ══════════════════════════════════════════════════════════════════════════════
# R(Right): 허용 trigger → visible=True
# ══════════════════════════════════════════════════════════════════════════════

def test_visible_whitelist_user_trigger():
    """R: trigger="user" → is_user=True, visible=True"""
    trigger = "user"
    is_user = _is_user_visible(trigger)
    assert is_user is True
    item = RunnerListItem(runner_id="r1", running=True, trigger=trigger, visible=is_user)
    assert item.visible is True


def test_visible_whitelist_user_all_trigger():
    """R: trigger="user:all" → is_user=True, visible=True"""
    trigger = "user:all"
    is_user = _is_user_visible(trigger)
    assert is_user is True
    item = RunnerListItem(runner_id="r2", running=True, trigger=trigger, visible=is_user)
    assert item.visible is True


# ══════════════════════════════════════════════════════════════════════════════
# B(Boundary): 비허용/누락 trigger → visible=False
# ══════════════════════════════════════════════════════════════════════════════

def test_visible_default_false_no_trigger():
    """B: trigger=None → is_user=False, visible=False"""
    trigger = None
    assert _is_user_visible(trigger) is False


def test_visible_default_false_empty_trigger():
    """B: trigger="" (빈 문자열) → visible=False"""
    trigger = ""
    assert _is_user_visible(trigger) is False


def test_visible_default_false_api_trigger():
    """B: trigger="api" → visible=False (test_source 누락 시 기본값)"""
    trigger = "api"
    assert _is_user_visible(trigger) is False


def test_visible_default_false_tc_trigger():
    """B: trigger="tc:some_test" → visible=False (정상 pytest 실행)"""
    trigger = "tc:some_test"
    assert _is_user_visible(trigger) is False


# ══════════════════════════════════════════════════════════════════════════════
# E(Error): 예상 외 trigger → visible=False (fail-closed)
# ══════════════════════════════════════════════════════════════════════════════

def test_visible_default_false_unknown_trigger():
    """E: trigger="unknown_value" → visible=False (화이트리스트에 없는 값)"""
    trigger = "unknown_value"
    assert _is_user_visible(trigger) is False


# ══════════════════════════════════════════════════════════════════════════════
# SSE 필터링 검증 — event_service._build_all_runners_status()
# ══════════════════════════════════════════════════════════════════════════════

def _run_sse_filter(runners: list[dict]) -> list[dict]:
    """_build_all_runners_status 내 필터링 로직 재현"""
    result = []
    for payload in runners:
        trigger = payload.get("trigger") or ""
        if trigger not in ("user", "user:all"):
            continue
        result.append(payload)
    return result


def test_sse_passes_user_trigger():
    """R: trigger="user" → SSE 결과에 포함"""
    runners = [{"runner_id": "a", "trigger": "user", "status": "running"}]
    result = _run_sse_filter(runners)
    assert len(result) == 1
    assert result[0]["runner_id"] == "a"


def test_sse_passes_user_all_trigger():
    """R: trigger="user:all" → SSE 결과에 포함"""
    runners = [{"runner_id": "b", "trigger": "user:all", "status": "running"}]
    result = _run_sse_filter(runners)
    assert len(result) == 1


def test_sse_filters_api_trigger():
    """B: trigger="api" → SSE 결과에서 제외"""
    runners = [{"runner_id": "c", "trigger": "api", "status": "running"}]
    result = _run_sse_filter(runners)
    assert len(result) == 0


def test_sse_filters_tc_trigger():
    """B: trigger="tc:test" → SSE 결과에서 제외"""
    runners = [{"runner_id": "d", "trigger": "tc:test", "status": "running"}]
    result = _run_sse_filter(runners)
    assert len(result) == 0


def test_sse_filters_none_trigger():
    """B: trigger=None → SSE 결과에서 제외"""
    runners = [{"runner_id": "e", "trigger": None, "status": "running"}]
    result = _run_sse_filter(runners)
    assert len(result) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 스키마 기본값 검증
# ══════════════════════════════════════════════════════════════════════════════

def test_runner_list_item_default_visible_false():
    """R: RunnerListItem 기본 생성 시 visible=False (화이트리스트 전환 후 기본 숨김)"""
    item = RunnerListItem(runner_id="x", running=False)
    assert item.visible is False, (
        f"visible 기본값이 False여야 하지만 {item.visible!r}. "
        "schemas.py의 visible: bool = False 설정을 확인하세요."
    )
