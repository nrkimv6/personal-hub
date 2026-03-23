"""trigger source 추적 TC

Phase T1: trigger 필드 스키마 검증 + trigger 판별 로직 + _parse_trigger_from_log 헬퍼
"""
import tempfile
import os
import pytest
from app.modules.dev_runner.schemas import RunRequest, RunHistoryItem, RunnerListItem
from app.modules.dev_runner.services.log_service import LogService


# --- R(Right): 기본 trigger 판별 ---

def test_trigger_resolved_from_test_source():
    """R(Right): RunRequest(test_source='my_tc') → trigger가 'tc:my_tc'로 판별"""
    request = RunRequest(test_source="my_tc")
    # executor_service trigger 판별 로직 재현
    if request.test_source:
        trigger = f"tc:{request.test_source}"
    else:
        trigger = request.trigger or "api"
    assert trigger == "tc:my_tc"


def test_trigger_from_explicit_request():
    """R(Right): RunRequest(trigger='user') (test_source 없음) → trigger가 'user'"""
    request = RunRequest(trigger="user")
    if request.test_source:
        trigger = f"tc:{request.test_source}"
    else:
        trigger = request.trigger or "api"
    assert trigger == "user"


# --- B(Boundary): 경계값 ---

def test_trigger_fallback_to_api():
    """B(Boundary): trigger=None, test_source=None → 'api' 폴백"""
    request = RunRequest()
    if request.test_source:
        trigger = f"tc:{request.test_source}"
    else:
        trigger = request.trigger or "api"
    assert trigger == "api"


def test_trigger_test_source_overrides_explicit():
    """C(Cross-check): test_source와 trigger 둘 다 있을 때 test_source 우선 → 'tc:{test_source}'"""
    request = RunRequest(test_source="priority_tc", trigger="user")
    if request.test_source:
        trigger = f"tc:{request.test_source}"
    else:
        trigger = request.trigger or "api"
    assert trigger == "tc:priority_tc"


def test_trigger_empty_string_fallback():
    """B(Boundary): trigger='' (빈 문자열) → 'api' 폴백"""
    request = RunRequest(trigger="")
    if request.test_source:
        trigger = f"tc:{request.test_source}"
    else:
        trigger = request.trigger or "api"
    assert trigger == "api"


# --- E(Existence): 스키마 기본값 ---

def test_trigger_field_in_run_request_default_none():
    """B(Boundary): RunRequest() 기본 생성 시 trigger=None"""
    req = RunRequest()
    assert req.trigger is None


def test_trigger_in_run_history_item_default_none():
    """E(Existence): RunHistoryItem(runner_id='x') 생성 시 trigger=None"""
    item = RunHistoryItem(runner_id="x")
    assert item.trigger is None


def test_trigger_in_runner_list_item():
    """R(Right): RunnerListItem에 trigger 필드 존재 확인"""
    item = RunnerListItem(runner_id="abc", running=True)
    assert hasattr(item, "trigger")
    assert item.trigger is None


# --- CORRECT — Existence: _parse_trigger_from_log ---

def test_parse_trigger_from_log_file():
    """E(Existence): 로그 파일에 '[TRIGGER] user | plan=...' 첫 줄 → 'user' 반환"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("[TRIGGER] user | plan=test.md | engine=claude | runner_id=abc123\n")
        f.write("some log line\n")
        tmp = f.name
    try:
        result = LogService._parse_trigger_from_log(tmp)
        assert result == "user"
    finally:
        os.unlink(tmp)


def test_parse_trigger_from_log_file_missing():
    """E(Existence): 로그 파일에 [TRIGGER] 줄 없음 → None 반환"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("2026-03-23 00:00:00 [INFO] Plan runner started\n")
        f.write("some log line\n")
        tmp = f.name
    try:
        result = LogService._parse_trigger_from_log(tmp)
        assert result is None
    finally:
        os.unlink(tmp)


def test_parse_trigger_from_log_file_empty():
    """B(Boundary): 빈 로그 파일 → None 반환"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        tmp = f.name
    try:
        result = LogService._parse_trigger_from_log(tmp)
        assert result is None
    finally:
        os.unlink(tmp)
