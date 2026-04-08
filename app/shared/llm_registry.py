"""LLM Model Registry — Quota-aware Model Picker.

단계(step)별 모델 후보 정책 + 실시간 quota 상태 기반으로 최적 모델을 선택합니다.
claude_worker / dev_runner 양쪽에서 공용으로 사용하는 shared 모듈입니다.

사용 예:
    from app.shared.llm_registry import pick_model, report_quota

    provider, model = pick_model("plan_feat")
    report_quota("claude", weekly_used_pct=80)
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator, Optional

from app.shared.io import read_json, write_json_atomic

logger = logging.getLogger("shared.llm_registry")

# ─── 경로 상수 (monkeypatch seam) ────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_FILE: Path = _PROJECT_ROOT / "data" / "llm_model_registry.json"
QUOTA_STATE_FILE: Path = _PROJECT_ROOT / "data" / "llm_quota_state.json"

# ─── Provider 정책 ────────────────────────────────────────────────────────────

# claude_worker가 실제 CLI 실행 가능한 provider (openai는 실행 경로 없음 — O-2)
SUPPORTED_EXECUTION_PROVIDERS: set[str] = {"claude", "gemini"}

# ─── CALLER_TYPE → step 매핑 (1-G) ───────────────────────────────────────────
CALLER_TYPE_TO_STEP: dict[str, str] = {
    # 생성형·고비용
    "writing": "plan_feat",
    "writing_generate": "plan_feat",
    "writing_refine": "implement",
    "report": "plan_feat",
    "pytest_fix": "plan_fix",
    "dev_runner": "implement",
    # 분석·중간
    "plan_archive_analyze": "plan_expand",
    "plan_requirements_sync": "plan_verify",
    "plan_recurrence_check": "status_tracking",
    "plan_recurrence_suggest": "ideation",
    "topic_extract": "ideation",
    # 경량·반복
    "instagram": "status_tracking",
    "universal_crawl": "status_tracking",
    "image_classify": "status_tracking",
    "event_import": "status_tracking",
    "git_repos": "status_tracking",
}

# ─── QUOTA_GROUPS — provider별 모델 그룹 (report 시 그룹 전파) ───────────────
# claude: 동일 계정 weekly quota 공유 → model 생략 시 전체 동기화
# gemini: Pro/Flash 완전 별개 → 그룹화 안 함
# openai: 현재 개별 관리 (O-1 확인 전)
QUOTA_GROUPS: dict[str, str] = {
    "claude": "claude/",  # 이 prefix로 시작하는 모든 entry에 전파
}

# ─── PROVIDER_RESET_RULES — weekly_reset_at 자동 계산 기준 (1-F) ─────────────
# weekday: 0=월, 1=화, 2=수, ..., 6=일 (isoweekday - 1)
KST = timezone(timedelta(hours=9))
PROVIDER_RESET_RULES: dict[str, dict] = {
    "claude": {"weekday": 0},   # 다음 월요일 00:00 KST
    "openai": {"weekday": 1},   # 다음 화요일 00:00 KST
    "gemini": {"weekday": 2},   # 다음 수요일 00:00 KST
}


# ─── 예외 ─────────────────────────────────────────────────────────────────────

class NoAvailableModelError(RuntimeError):
    """모든 후보가 quota/cooldown으로 차단됐을 때 발생."""
    def __init__(self, step: str, reason: str = ""):
        super().__init__(f"No available model for step={step!r}. {reason}".strip())
        self.step = step


# ─── 데이터 클래스 ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StepCandidate:
    provider: str
    model: str
    oneshot: bool = False

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass
class ModelQuota:
    weekly_used_pct: float = 0.0
    weekly_reset_at: Optional[datetime] = None   # timezone-aware (KST)
    short_cooldown_until: Optional[datetime] = None  # timezone-aware (KST)
    updated_at: Optional[datetime] = None

    def is_weekly_exhausted(self, threshold: float = 95.0) -> bool:
        return self.weekly_used_pct >= threshold

    def is_in_cooldown(self, now: datetime) -> bool:
        return self.short_cooldown_until is not None and self.short_cooldown_until > now


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _now_kst() -> datetime:
    return datetime.now(tz=KST)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """ISO 8601 문자열 → timezone-aware datetime. 파싱 실패 시 None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt
    except (ValueError, TypeError):
        return None


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _next_reset_at(provider: str, now: datetime) -> datetime:
    """1-F: provider별 PROVIDER_RESET_RULES에 따라 다음 reset 시각 계산."""
    rule = PROVIDER_RESET_RULES.get(provider, {"weekday": 0})
    target_weekday = rule["weekday"]  # 0=월...6=일
    now_kst = now.astimezone(KST)
    current_weekday = now_kst.isoweekday() % 7  # isoweekday: 1=월...7=일 → 0=월...6=일
    days_ahead = (target_weekday - current_weekday) % 7
    if days_ahead == 0:
        days_ahead = 7  # 오늘이 target이면 다음 주로
    reset_date = now_kst.date() + timedelta(days=days_ahead)
    return datetime(reset_date.year, reset_date.month, reset_date.day, tzinfo=KST)


# ─── 파일 lock (O-3) ──────────────────────────────────────────────────────────

@contextmanager
def _state_lock(timeout: float = 3.0) -> Generator[None, None, None]:
    """파일 기반 advisory lock. Windows 호환."""
    lock_path = Path(str(QUOTA_STATE_FILE) + ".lock")
    deadline = time.monotonic() + timeout
    acquired = False
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            time.sleep(0.05)
    if not acquired:
        raise TimeoutError(f"LLM quota state lock 획득 실패 (timeout={timeout}s)")
    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


# ─── Registry 로더 ────────────────────────────────────────────────────────────

def load_registry() -> dict[str, list[StepCandidate]]:
    """data/llm_model_registry.json 로드 → {step: [StepCandidate]}."""
    raw = read_json(REGISTRY_FILE, default={"steps": {}})
    steps_raw = raw.get("steps", {}) if isinstance(raw, dict) else {}
    result: dict[str, list[StepCandidate]] = {}
    for step, candidates_raw in steps_raw.items():
        candidates: list[StepCandidate] = []
        for c in candidates_raw:
            if not isinstance(c, dict):
                continue
            provider = c.get("provider", "")
            model = c.get("model", "")
            oneshot = bool(c.get("oneshot", False))
            if provider and model:
                candidates.append(StepCandidate(provider=provider, model=model, oneshot=oneshot))
        result[step] = candidates
    return result


def _raw_state_to_quotas(raw: dict) -> dict[str, ModelQuota]:
    entries_raw = raw.get("entries", {}) if isinstance(raw, dict) else {}
    state: dict[str, ModelQuota] = {}
    for key, entry in entries_raw.items():
        if not isinstance(entry, dict):
            continue
        state[key] = ModelQuota(
            weekly_used_pct=float(entry.get("weekly_used_pct", 0.0)),
            weekly_reset_at=_parse_dt(entry.get("weekly_reset_at")),
            short_cooldown_until=_parse_dt(entry.get("short_cooldown_until")),
            updated_at=_parse_dt(entry.get("updated_at")),
        )
    return state


def _quotas_to_raw(state: dict[str, ModelQuota]) -> dict:
    entries: dict = {}
    for key, quota in state.items():
        entries[key] = {
            "weekly_used_pct": quota.weekly_used_pct,
            "weekly_reset_at": _dt_to_str(quota.weekly_reset_at),
            "short_cooldown_until": _dt_to_str(quota.short_cooldown_until),
            "updated_at": _dt_to_str(quota.updated_at),
        }
    return {"entries": entries}


def load_quota_state(apply_decay_in_memory: bool = True, now: Optional[datetime] = None) -> dict[str, ModelQuota]:
    """data/llm_quota_state.json 로드 → {key: ModelQuota}.

    apply_decay_in_memory=True(기본)이면 decay를 적용한 사본을 반환하되
    파일은 절대 수정하지 않습니다 (O-6).
    """
    raw = read_json(QUOTA_STATE_FILE, default={"entries": {}})
    state = _raw_state_to_quotas(raw)
    if apply_decay_in_memory:
        _now = now or _now_kst()
        state = apply_decay(state, _now)
    return state


def save_quota_state(state: dict[str, ModelQuota]) -> None:
    """lock 범위 내에서 호출 가정. 직접 호출 시 _state_lock() 사용."""
    write_json_atomic(QUOTA_STATE_FILE, _quotas_to_raw(state))


# ─── apply_decay (in-memory 순수 함수, IO 없음) ───────────────────────────────

def apply_decay(state: dict[str, ModelQuota], now: datetime) -> dict[str, ModelQuota]:
    """reset/cooldown 만료를 적용한 새 dict 반환. 원본 불변."""
    result: dict[str, ModelQuota] = {}
    for key, quota in state.items():
        provider = key.split("/")[0] if "/" in key else key
        new_weekly_pct = quota.weekly_used_pct
        new_reset_at = quota.weekly_reset_at
        new_cooldown = quota.short_cooldown_until

        # weekly 리셋
        if quota.weekly_reset_at is not None and quota.weekly_reset_at <= now:
            new_weekly_pct = 0.0
            new_reset_at = _next_reset_at(provider, now)

        # cooldown 만료
        if quota.short_cooldown_until is not None and quota.short_cooldown_until <= now:
            new_cooldown = None

        result[key] = ModelQuota(
            weekly_used_pct=new_weekly_pct,
            weekly_reset_at=new_reset_at,
            short_cooldown_until=new_cooldown,
            updated_at=quota.updated_at,
        )
    return result


# ─── pick_model ───────────────────────────────────────────────────────────────

def pick_model(
    step: str,
    oneshot: bool = False,
    now: Optional[datetime] = None,
    exclude_providers: Optional[set[str]] = None,
) -> tuple[str, str]:
    """step에 맞는 최우선 사용 가능 모델 (provider, model) 반환.

    제외 규칙 (3가지):
    1. weekly_used_pct >= 95 → 제외
    2. short_cooldown_until > now → 제외
    3. candidate.oneshot=True 인데 oneshot=False 호출 → 제외

    1-E fallback:
    - 전부 제외 + cooldown 아닌 후보 있음 → weekly_used_pct 최소 선택 + WARN
    - 전부 cooldown → NoAvailableModelError
    """
    if oneshot and os.environ.get("DUMPTRUCK_MODE") != "1":
        raise RuntimeError(
            "oneshot=True 호출은 DUMPTRUCK_MODE=1 환경에서만 허용됩니다 (핑퐁 차단)"
        )

    _now = now or _now_kst()
    exclude = exclude_providers or set()

    registry = load_registry()
    candidates = registry.get(step, [])
    if not candidates:
        raise NoAvailableModelError(step, f"registry에 step={step!r} 미존재")

    state = load_quota_state(apply_decay_in_memory=True, now=_now)

    available: list[tuple[StepCandidate, ModelQuota]] = []
    excluded_cooldown: list[tuple[StepCandidate, ModelQuota]] = []

    for cand in candidates:
        # exclude_providers 필터
        if cand.provider in exclude:
            continue
        # oneshot 필터
        if cand.oneshot and not oneshot:
            continue

        quota = state.get(cand.key, ModelQuota())

        if quota.is_in_cooldown(_now):
            excluded_cooldown.append((cand, quota))
            continue
        if quota.is_weekly_exhausted():
            excluded_cooldown.append((cand, quota))  # weekly 초과도 "불가"로 분류
            continue

        available.append((cand, quota))

    if available:
        # 정상 경로: 첫 후보 반환 (registry 우선순위 유지)
        return available[0][0].provider, available[0][0].model

    # 1-E fallback
    # cooldown 중이 아니지만 weekly 초과인 후보가 있으면 가장 덜 소진된 것 선택
    weekly_exceeded_only = [
        (cand, quota) for cand, quota in excluded_cooldown
        if not quota.is_in_cooldown(_now)
    ]
    if weekly_exceeded_only:
        best_cand, best_quota = min(weekly_exceeded_only, key=lambda x: x[1].weekly_used_pct)
        logger.warning(
            "[llm_registry] 전부 제외(weekly 초과) — 최소 소진 후보로 fallback: "
            f"{best_cand.key} ({best_quota.weekly_used_pct:.0f}%)"
        )
        return best_cand.provider, best_cand.model

    raise NoAvailableModelError(
        step,
        f"후보 {len(candidates)}개 모두 cooldown 중 (oneshot={oneshot}, exclude={exclude})"
    )


# ─── report_quota ─────────────────────────────────────────────────────────────

def report_quota(
    provider: str,
    model: Optional[str] = None,
    weekly_used_pct: Optional[float] = None,
    delta_weekly_pct: Optional[float] = None,
    weekly_reset_at: Optional[datetime] = None,
    short_cooldown_minutes: Optional[int] = None,
    source: str = "manual",
) -> None:
    """quota 상태를 갱신합니다.

    Args:
        provider: 'claude', 'gemini', 'openai' 등
        model: None이면 QUOTA_GROUPS에 따라 그룹 전체 적용
        weekly_used_pct: 절대값 (0~100), delta_weekly_pct와 상호 배타
        delta_weekly_pct: 증분값 (현재값에 가산 후 0~100 clamp)
        weekly_reset_at: 명시 지정 시 그대로 사용. 없으면 1-F 규칙으로 자동 계산
        short_cooldown_minutes: 분 단위 cooldown 시간
        source: 로깅용 출처 ('manual', 'auto_quota_detect')
    """
    if weekly_used_pct is not None and delta_weekly_pct is not None:
        raise ValueError("weekly_used_pct와 delta_weekly_pct는 동시에 지정할 수 없습니다.")

    now = _now_kst()

    with _state_lock():
        raw = read_json(QUOTA_STATE_FILE, default={"entries": {}})
        state = _raw_state_to_quotas(raw)
        state = apply_decay(state, now)

        # 대상 key 목록 결정
        target_keys: list[str] = []
        if model is None:
            # QUOTA_GROUPS 전파: prefix 매칭
            group_prefix = QUOTA_GROUPS.get(provider)
            if group_prefix:
                target_keys = [k for k in state if k.startswith(group_prefix)]
                if not target_keys:
                    # state에 아직 없으면 빈 리스트 유지 (신규 모델들이 report 시 생성됨)
                    # provider/* 패턴으로 registry에서 찾기
                    registry = load_registry()
                    all_keys = set()
                    for candidates in registry.values():
                        for c in candidates:
                            if c.provider == provider:
                                all_keys.add(c.key)
                    target_keys = list(all_keys)
            else:
                # 그룹 없음: provider/* 모든 기존 entry
                target_keys = [k for k in state if k.startswith(f"{provider}/")]
        else:
            target_keys = [f"{provider}/{model}"]

        # 대상 key별 갱신
        for key in target_keys:
            quota = state.get(key, ModelQuota())
            _provider = key.split("/")[0]

            # weekly_used_pct 갱신
            if weekly_used_pct is not None:
                new_pct = max(0.0, min(100.0, float(weekly_used_pct)))
            elif delta_weekly_pct is not None:
                new_pct = max(0.0, min(100.0, quota.weekly_used_pct + float(delta_weekly_pct)))
            else:
                new_pct = quota.weekly_used_pct

            # weekly_reset_at: 1-F trigger 조건
            if weekly_reset_at is not None:
                new_reset = weekly_reset_at
            elif quota.weekly_reset_at is None or quota.weekly_reset_at <= now:
                # 신규 or 이미 과거
                new_reset = _next_reset_at(_provider, now)
            else:
                new_reset = quota.weekly_reset_at

            # short_cooldown_until
            if short_cooldown_minutes is not None:
                if short_cooldown_minutes <= 0:
                    new_cooldown = None
                else:
                    new_cooldown = now + timedelta(minutes=short_cooldown_minutes)
            else:
                new_cooldown = quota.short_cooldown_until

            state[key] = ModelQuota(
                weekly_used_pct=new_pct,
                weekly_reset_at=new_reset,
                short_cooldown_until=new_cooldown,
                updated_at=now,
            )
            logger.info(
                f"[llm_registry] quota updated: key={key} pct={new_pct:.0f}% "
                f"cooldown={new_cooldown} source={source}"
            )

        # model 지정됐지만 state에 없는 신규 entry
        if model is not None and f"{provider}/{model}" not in state:
            # 위 루프에서 이미 처리됐을 것이지만 안전하게 재확인
            key = f"{provider}/{model}"
            if key not in state:
                quota = ModelQuota()
                new_pct = max(0.0, min(100.0, float(weekly_used_pct or 0.0)))
                new_reset = weekly_reset_at or _next_reset_at(provider, now)
                new_cooldown = (
                    now + timedelta(minutes=short_cooldown_minutes)
                    if short_cooldown_minutes and short_cooldown_minutes > 0
                    else None
                )
                state[key] = ModelQuota(
                    weekly_used_pct=new_pct,
                    weekly_reset_at=new_reset,
                    short_cooldown_until=new_cooldown,
                    updated_at=now,
                )

        save_quota_state(state)
