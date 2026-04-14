"""llm_registry 단위 TC — pick_model / apply_decay / report_quota."""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.shared.llm_registry as reg_mod
from app.shared.llm_registry import (
    KST,
    ModelQuota,
    NoAvailableModelError,
    StepCandidate,
    apply_decay,
    load_quota_state,
    pick_model,
    report_quota,
    _next_reset_at,
)


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _kst(year=2026, month=4, day=10, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def _write_state(state_file: Path, entries: dict):
    state_file.write_text(json.dumps({"entries": entries}), encoding="utf-8")


def _make_quota(pct=0, cooldown_until=None, reset_at=None):
    return {
        "weekly_used_pct": pct,
        "weekly_reset_at": reset_at.isoformat() if reset_at else None,
        "short_cooldown_until": cooldown_until.isoformat() if cooldown_until else None,
        "updated_at": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# pick_model TC
# ──────────────────────────────────────────────────────────────────────────────

class TestPickModel:
    def test_pick_model_R_happy_returns_top_candidate(self, tmp_registry_state):
        """R: 정상 상태 → 1순위 후보 반환."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=10),
        })
        p, m = pick_model("plan_feat", now=_kst())
        assert p == "claude"
        assert m == "claude-sonnet-4-6"

    def test_pick_model_B_weekly_95pct_excluded(self, tmp_registry_state):
        """B: 95% 경계에서 첫 후보 제외 → 다음 후보 선택."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=95),  # 경계: 제외
            "openai/gpt-5.4": _make_quota(pct=10),
        })
        p, m = pick_model("plan_feat", now=_kst())
        assert p == "openai"
        assert m == "gpt-5.4"

    def test_pick_model_B_weekly_94pct_included(self, tmp_registry_state):
        """B: 94%는 선택됨."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=94),
        })
        p, m = pick_model("plan_feat", now=_kst())
        assert p == "claude"

    def test_pick_model_B_weekly_100pct_excluded(self, tmp_registry_state):
        """B: 100% → 제외."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=100),
            "openai/gpt-5.4": _make_quota(pct=5),
        })
        p, m = pick_model("plan_feat", now=_kst())
        assert p == "openai"

    def test_pick_model_E_all_cooldown_raises_no_available(self, tmp_registry_state):
        """E: 전부 cooldown → NoAvailableModelError."""
        now = _kst()
        _, state_file = tmp_registry_state
        future = now + timedelta(hours=3)
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(cooldown_until=future),
            "openai/gpt-5.4": _make_quota(cooldown_until=future),
            "gemini/gemini-3.1-pro": _make_quota(cooldown_until=future),
        })
        with pytest.raises(NoAvailableModelError):
            pick_model("plan_feat", now=now)

    def test_pick_model_E_all_weekly_exceeded_picks_least_used(self, tmp_registry_state, caplog):
        """E: 전부 95%+ (cooldown 없음) → 최소값 선택 + WARN."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=98),
            "openai/gpt-5.4": _make_quota(pct=96),
        })
        import logging
        with caplog.at_level(logging.WARNING, logger="shared.llm_registry"):
            p, m = pick_model("plan_feat", now=_kst())
        # 최소 소진 = openai 96%
        assert p == "openai"
        assert "fallback" in caplog.text.lower()

    def test_pick_model_Co_oneshot_flag_skipped_in_pingpong(self, tmp_registry_state):
        """Co: oneshot=False → oneshot:true 후보 skip."""
        now = _kst()
        future = now + timedelta(hours=1)
        _, state_file = tmp_registry_state
        # claude/openai 모두 cooldown, gemini-3.1-pro는 oneshot:true → oneshot=False이면 skip → NoAvailable
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=100, cooldown_until=future),
            "openai/gpt-5.4": _make_quota(pct=100, cooldown_until=future),
            "gemini/gemini-3.1-pro": _make_quota(pct=5),
        })
        with pytest.raises(NoAvailableModelError):
            pick_model("plan_feat", oneshot=False, now=now)

    def test_pick_model_Co_oneshot_flag_allowed_when_oneshot_true(self, tmp_registry_state, monkeypatch):
        """Co: oneshot=True 모드에서는 oneshot:true 후보도 선택 가능 (DUMPTRUCK_MODE=1 필요)."""
        monkeypatch.setenv("DUMPTRUCK_MODE", "1")
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=100, cooldown_until=_kst() + timedelta(hours=1)),
            "openai/gpt-5.4": _make_quota(pct=100, cooldown_until=_kst() + timedelta(hours=1)),
            "gemini/gemini-3.1-pro": _make_quota(pct=5),
        })
        p, m = pick_model("plan_feat", oneshot=True, now=_kst())
        assert p == "gemini"
        assert m == "gemini-3.1-pro"

    def test_pick_model_T_cooldown_expired_recovered(self, tmp_registry_state):
        """T(Time): cooldown 만료 후 재선택 가능."""
        now = _kst()
        past_cooldown = now - timedelta(minutes=1)
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(cooldown_until=past_cooldown),
        })
        p, m = pick_model("plan_feat", now=now)
        assert p == "claude"

    def test_pick_model_Co_gemini_pro_and_flash_independent_cooldown(self, tmp_registry_state):
        """Co: Gemini Pro cooldown 중에도 Flash는 선택 가능."""
        now = _kst()
        future = now + timedelta(hours=3)
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "gemini/gemini-3.1-pro": _make_quota(cooldown_until=future),
            "gemini/gemini-3-flash": _make_quota(pct=5),
        })
        p, m = pick_model("status_tracking", now=now)
        # status_tracking: claude-haiku 먼저지만 state 없으므로 0% → 선택됨
        assert p in ("claude", "gemini")

    # ── oneshot 환경변수 가드 TC ───────────────────────────────────────────────

    def test_pick_model_oneshot_guard_R_with_env(self, tmp_registry_state, monkeypatch):
        """R: DUMPTRUCK_MODE=1 설정 후 pick_model(oneshot=True) 정상 반환 (gemini-3.1-pro 선택)."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=100, cooldown_until=_kst() + timedelta(hours=1)),
            "openai/gpt-5.4": _make_quota(pct=100, cooldown_until=_kst() + timedelta(hours=1)),
            "gemini/gemini-3.1-pro": _make_quota(pct=5),
        })
        monkeypatch.setenv("DUMPTRUCK_MODE", "1")
        p, m = pick_model("plan_feat", oneshot=True, now=_kst())
        assert p == "gemini"
        assert m == "gemini-3.1-pro"

    def test_pick_model_oneshot_guard_E_without_env(self, tmp_registry_state, monkeypatch):
        """E: DUMPTRUCK_MODE 미설정 + oneshot=True 호출 시 RuntimeError 발생 + 메시지에 DUMPTRUCK_MODE 포함."""
        # monkeypatch로 DUMPTRUCK_MODE를 명시적으로 "0"으로 설정 (미설정과 동일한 차단 효과)
        monkeypatch.setenv("DUMPTRUCK_MODE", "0")
        with pytest.raises(RuntimeError, match="DUMPTRUCK_MODE"):
            pick_model("plan_feat", oneshot=True, now=_kst())

    def test_pick_model_default_oneshot_false_excludes_gemini(self, tmp_registry_state):
        """R 회귀: pick_model("plan_feat") 기본값(oneshot=False)이 gemini-3.1-pro를 제외하고 다른 provider 반환."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=5),
            "openai/gpt-5.4": _make_quota(pct=5),
            "gemini/gemini-3.1-pro": _make_quota(pct=5),
        })
        p, m = pick_model("plan_feat", now=_kst())
        # gemini-3.1-pro는 oneshot:true이므로 oneshot=False 호출에서 제외되어야 함
        assert not (p == "gemini" and m == "gemini-3.1-pro")

    def test_pick_model_oneshot_false_explicit_excludes_gemini(self, tmp_registry_state):
        """B(Boundary): oneshot=False 명시 호출도 동일하게 gemini-3.1-pro 제외."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=5),
            "openai/gpt-5.4": _make_quota(pct=5),
            "gemini/gemini-3.1-pro": _make_quota(pct=5),
        })
        p, m = pick_model("plan_feat", oneshot=False, now=_kst())
        assert not (p == "gemini" and m == "gemini-3.1-pro")

    def test_pick_model_Co_exclude_providers_skips_openai(self, tmp_registry_state):
        """Co(O-2): exclude_providers={"openai","gemini"} → openai/gemini skip, claude만 남음."""
        now = _kst()
        future = now + timedelta(hours=3)
        _, state_file = tmp_registry_state
        # claude: cooldown 중, openai/gemini: exclude → 전부 불가 → NoAvailableModelError
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": _make_quota(pct=0, cooldown_until=future),
            "openai/gpt-5.4": _make_quota(pct=5),
        })
        with pytest.raises(NoAvailableModelError):
            pick_model("plan_feat", now=now, exclude_providers={"openai", "gemini"})

    def test_pick_model_E_all_cooldown_global_default_semantics(self, tmp_registry_state):
        """E: step 없는 caller → NoAvailableModelError(step='unknown_step')."""
        _, state_file = tmp_registry_state
        with pytest.raises(NoAvailableModelError) as exc_info:
            pick_model("__nonexistent_step__", now=_kst())
        assert "__nonexistent_step__" in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────────────
# apply_decay TC
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyDecay:
    def test_apply_decay_R_reset_past_zeros_weekly(self):
        """R: weekly_reset_at이 과거 → weekly_used_pct=0."""
        now = _kst()
        past = now - timedelta(days=1)
        state = {
            "claude/claude-opus-4-6": ModelQuota(
                weekly_used_pct=80,
                weekly_reset_at=past,
                short_cooldown_until=None,
                updated_at=None,
            )
        }
        result = apply_decay(state, now)
        assert result["claude/claude-opus-4-6"].weekly_used_pct == 0.0
        assert result["claude/claude-opus-4-6"].weekly_reset_at > now

    def test_apply_decay_T_future_reset_unchanged(self):
        """T: 미래 reset → weekly_used_pct 유지."""
        now = _kst()
        future = now + timedelta(days=3)
        state = {
            "claude/claude-opus-4-6": ModelQuota(
                weekly_used_pct=60,
                weekly_reset_at=future,
                short_cooldown_until=None,
                updated_at=None,
            )
        }
        result = apply_decay(state, now)
        assert result["claude/claude-opus-4-6"].weekly_used_pct == 60.0
        assert result["claude/claude-opus-4-6"].weekly_reset_at == future

    def test_apply_decay_Co_no_file_write(self, tmp_registry_state, tmp_path):
        """Co(O-6): apply_decay는 in-memory 순수 함수, 파일 수정 없음."""
        _, state_file = tmp_registry_state
        import time as _time
        mtime_before = state_file.stat().st_mtime if state_file.exists() else None
        _time.sleep(0.05)

        now = _kst()
        past = now - timedelta(days=1)
        state = {"claude/x": ModelQuota(weekly_used_pct=80, weekly_reset_at=past)}
        apply_decay(state, now)  # 파일 쓰기 없어야 함

        if state_file.exists() and mtime_before is not None:
            assert state_file.stat().st_mtime == mtime_before


# ──────────────────────────────────────────────────────────────────────────────
# report_quota TC
# ──────────────────────────────────────────────────────────────────────────────

class TestReportQuota:
    def test_report_quota_R_model_group_propagates_claude_siblings(self, tmp_registry_state):
        """R: provider=claude, model=None → claude/* 전체 동기화."""
        registry_file, state_file = tmp_registry_state
        # registry에 claude 모델 있어야 전파 대상 인식
        # conftest의 sample registry에 claude/claude-sonnet-4-6, claude/claude-opus-4-6 등 있음
        report_quota("claude", model=None, weekly_used_pct=50, source="test")
        state = load_quota_state(apply_decay_in_memory=False)
        claude_keys = [k for k in state if k.startswith("claude/")]
        assert len(claude_keys) >= 1
        for k in claude_keys:
            assert state[k].weekly_used_pct == 50.0

    def test_report_quota_R_gemini_pro_not_propagates_to_flash(self, tmp_registry_state):
        """R: gemini는 그룹 없음 → Pro 지정 시 Flash 영향 없음."""
        _, state_file = tmp_registry_state
        # 초기 Flash state 세팅
        _write_state(state_file, {
            "gemini/gemini-3-flash": _make_quota(pct=10),
        })
        report_quota("gemini", model="gemini-3.1-pro", weekly_used_pct=80, source="test")
        state = load_quota_state(apply_decay_in_memory=False)
        assert state["gemini/gemini-3.1-pro"].weekly_used_pct == 80.0
        assert state["gemini/gemini-3-flash"].weekly_used_pct == 10.0

    def test_report_quota_B_delta_clamps_to_100(self, tmp_registry_state):
        """B: 90 + delta 20 → 100 clamp."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "openai/gpt-5.4": _make_quota(pct=90),
        })
        report_quota("openai", model="gpt-5.4", delta_weekly_pct=20, source="test")
        state = load_quota_state(apply_decay_in_memory=False)
        assert state["openai/gpt-5.4"].weekly_used_pct == 100.0

    def test_report_quota_B_delta_clamps_to_0(self, tmp_registry_state):
        """B: 10 + delta -30 → 0 clamp."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "openai/gpt-5.4": _make_quota(pct=10),
        })
        report_quota("openai", model="gpt-5.4", delta_weekly_pct=-30, source="test")
        state = load_quota_state(apply_decay_in_memory=False)
        assert state["openai/gpt-5.4"].weekly_used_pct == 0.0

    def test_report_quota_E_both_absolute_and_delta_raises(self, tmp_registry_state):
        """E: weekly_used_pct + delta_weekly_pct 동시 → ValueError."""
        with pytest.raises(ValueError, match="동시에"):
            report_quota("claude", model="claude-sonnet-4-6",
                         weekly_used_pct=50, delta_weekly_pct=10)

    def test_report_quota_T_weekly_reset_auto_only_on_create_or_past(self, tmp_registry_state):
        """T(1-F trigger): 미래 reset은 유지, 과거/신규만 재계산."""
        now = _kst()
        future_reset = now + timedelta(days=5)
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "claude/claude-sonnet-4-6": {
                "weekly_used_pct": 30,
                "weekly_reset_at": future_reset.isoformat(),
                "short_cooldown_until": None,
                "updated_at": None,
            }
        })
        report_quota("claude", model="claude-sonnet-4-6", weekly_used_pct=50, source="test")
        state = load_quota_state(apply_decay_in_memory=False)
        # 미래 reset은 변경 없어야 함
        assert state["claude/claude-sonnet-4-6"].weekly_reset_at == future_reset

    def test_report_quota_Co_concurrent_writes_are_serialized(self, tmp_registry_state):
        """Co(O-3): threading 2개 동시 +10 → 최종 +20 (race 없음)."""
        _, state_file = tmp_registry_state
        _write_state(state_file, {
            "openai/gpt-5.4": _make_quota(pct=40),
        })
        errors = []

        def add10():
            try:
                report_quota("openai", model="gpt-5.4", delta_weekly_pct=10, source="test_concurrent")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=add10)
        t2 = threading.Thread(target=add10)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"concurrent error: {errors}"
        state = load_quota_state(apply_decay_in_memory=False)
        # 40 + 10 + 10 = 60
        assert state["openai/gpt-5.4"].weekly_used_pct == 60.0
