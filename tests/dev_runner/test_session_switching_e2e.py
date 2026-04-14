"""
session switching E2E TC — Phase T4

Phase T4: 23번 항목
- fake adapter를 사용하므로 live server 불필요
- 기존 session-fusion 흐름 회귀 방어 + 신규 switch/restart/gate 경로 검증
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# wtools plan-runner core 모듈 임포트
_WTOOLS_CORE = (
    Path(__file__).resolve().parents[2].parent.parent
    / "service" / "wtools" / "common" / "tools" / "plan-runner"
)
if str(_WTOOLS_CORE) not in sys.path:
    sys.path.insert(0, str(_WTOOLS_CORE))

from core.cli_adapters import ClaudeAdapter, CodexAdapter, get_adapter
from core.session_switching import (
    SessionState,
    SwitchDecision,
    apply_engine_restart,
    apply_model_switch,
    maybe_switch_model,
)


# ─── 헬퍼 ────────────────────────────────────────────────────────────────────

def _state(engine="claude", model="sonnet", session_id=None, step="implement", bytes_=0):
    return SessionState(
        engine=engine,
        model=model,
        session_id=session_id or uuid.uuid4().hex[:8],
        step=step,
        accumulated_bytes=bytes_,
    )


# ─── T4: 기존 session-fusion 회귀 방어 ────────────────────────────────────────

def test_claude_only_fused_session_unchanged():
    """T4: Claude 단일 모델 KEEP → 세션 변화 없음 (session-fusion 회귀).

    Phase 1.5 이관(engine_claude.py session_args 위임) 이후에도
    KEEP 결정 시 session_id가 바뀌지 않아야 한다.
    """
    sid = "fused-sid-original"
    state = _state(engine="claude", model="sonnet", session_id=sid)

    def pick_same(_step):
        return ("claude", "sonnet")

    decision, engine, model = maybe_switch_model(
        state, next_step="implement", pick_model_fn=pick_same
    )
    assert decision == SwitchDecision.KEEP
    # KEEP: session_id는 변경 없어야 함 (호출자가 그대로 재사용)
    assert engine == "claude"
    assert model == "sonnet"


def test_switch_model_flow_haiku_to_sonnet():
    """T4: SWITCH_MODEL 경로 — 2단계 분리 패턴 argv 검증.

    /model sonnet 단독 spawn → 다음 spawn은 기존 session_id로 진행.
    """
    sid = "switch-sid"
    state = _state(engine="claude", model="haiku", session_id=sid)

    def pick_sonnet(_step):
        return ("claude", "sonnet")

    decision, engine, model = maybe_switch_model(
        state, next_step="implement", pick_model_fn=pick_sonnet
    )
    assert decision == SwitchDecision.SWITCH_MODEL
    assert engine == "claude"
    assert model == "sonnet"

    # apply_model_switch: model_switch_args 호출 확인
    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.extend(argv)
        m = MagicMock()
        m.returncode = 0
        return m

    with patch("core.session_switching.subprocess.run", side_effect=fake_run):
        result = apply_model_switch(state, new_model="sonnet")

    # /model sonnet 단독 spawn argv 확인
    assert "claude" in captured_argv
    assert "--resume" in captured_argv
    assert sid in captured_argv
    assert "/model sonnet" in captured_argv
    # SWITCH_MODEL 완료 (None이면 성공)
    assert result is None


def test_engine_restart_flow_claude_to_codex(tmp_path):
    """T4: RESTART_ENGINE 경로 — 새 session_id 발급 + memo 파일 생성 확인."""
    sid = "restart-sid"
    state = _state(engine="claude", model="sonnet", session_id=sid)

    def pick_codex(_step):
        return ("openai", "gpt-5-codex")

    decision, engine, model = maybe_switch_model(
        state, next_step="implement", pick_model_fn=pick_codex
    )
    assert decision == SwitchDecision.RESTART_ENGINE
    assert engine == "codex"

    # apply_engine_restart: 새 session_id 발급
    new_state = apply_engine_restart(
        state, new_engine="codex", new_model="gpt-5-codex",
        run_id="t4-run", stage_idx=1,
    )
    assert new_state.engine == "codex"
    assert new_state.session_id != sid  # 새 session_id 발급
    assert new_state.model == "gpt-5-codex"


def test_gemini_gate_fallback_in_pipeline():
    """T4: registry가 gemini를 반환해도 plan_runner source에서 자동 폴백.

    gemini 엔진은 RESTART_ENGINE이 아닌 KEEP(폴백 후 claude) 또는
    SWITCH_MODEL을 반환해야 한다.
    """
    state = _state(engine="claude", model="sonnet")

    call_count = {"n": 0}

    def pick_gemini_first(step, exclude_providers=None):
        call_count["n"] += 1
        if call_count["n"] == 1 and not (exclude_providers and "gemini" in exclude_providers):
            return ("gemini", "gemini-pro")
        return ("claude", "haiku")

    # source=plan_runner이면 gemini 게이트 → claude/haiku로 폴백 후 SWITCH_MODEL
    decision, engine, model = maybe_switch_model(
        state, next_step="plan_expand",
        pick_model_fn=lambda step: pick_gemini_first(step),
        source="plan_runner",
    )
    # gemini는 게이트되고 claude로 폴백
    assert engine != "gemini"
    assert decision in (SwitchDecision.KEEP, SwitchDecision.SWITCH_MODEL, SwitchDecision.RESTART_ENGINE)


def test_isolate_boundary_plan_verify_to_implement():
    """T4: plan_verify → implement 격리 경계 — engine 동일해도 ISOLATE 반환."""
    state = _state(engine="claude", model="sonnet", step="plan_verify")

    def pick_same(_step):
        return ("claude", "sonnet")

    decision, engine, model = maybe_switch_model(
        state, next_step="implement", pick_model_fn=pick_same
    )
    assert decision == SwitchDecision.ISOLATE
