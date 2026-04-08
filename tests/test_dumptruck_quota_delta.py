"""
Phase T1: dumptruck quota delta 환산 로직 단위 테스트

dumptruck_run.ps1의 est_tokens → delta_pct 환산 로직과 동등한 Python 함수를 이용해
경계값 및 fallback 동작을 검증한다.

PowerShell 원본 로직:
    $DeltaPct = [math]::Max(1, [math]::Min(100, [math]::Ceiling($EstTokens / 2_000_000 * 100)))
    파싱 실패 시: $DeltaPct = 10 (fallback)
"""
import math
import re
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 환산 로직 (PowerShell 로직과 1:1 동등)
# ─────────────────────────────────────────────────────────────────────────────

def calc_delta_pct(est_tokens: int) -> int:
    """est_tokens → delta_pct 환산 (2M 컨텍스트 기준, 1~100% clamp)."""
    return max(1, min(100, math.ceil(est_tokens / 2_000_000 * 100)))


def parse_est_tokens_from_stderr(stderr_content: str) -> tuple[int | None, int]:
    """
    stderr 문자열에서 est_tokens 파싱 후 delta_pct 반환.

    Returns:
        (est_tokens, delta_pct) — 파싱 실패 시 (None, 10) fallback
    """
    FALLBACK_DELTA = 10
    match = re.search(r'est_tokens=([\d,]+)', stderr_content)
    if not match:
        return None, FALLBACK_DELTA
    try:
        est_tokens = int(match.group(1).replace(',', ''))
        return est_tokens, calc_delta_pct(est_tokens)
    except ValueError:
        return None, FALLBACK_DELTA


# ─────────────────────────────────────────────────────────────────────────────
# TC: calc_delta_pct 경계값
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("est_tokens,expected_delta", [
    (0,          1),    # 최솟값 clamp: ceiling(0)=0 → max(1,...)=1
    (200_000,   10),    # 정상 범위: 200000/2M*100 = 10.0 → ceiling=10
    (1_500_000, 75),    # Gemini 2M 75%: 1500000/2M*100 = 75.0
    (2_000_000, 100),   # 정확히 100%
    (2_500_000, 100),   # 초과 clamp: ceiling(125)=125 → min(100,...)=100
])
def test_calc_delta_pct(est_tokens: int, expected_delta: int) -> None:
    """est_tokens → delta_pct 환산 경계값 검증."""
    assert calc_delta_pct(est_tokens) == expected_delta


# ─────────────────────────────────────────────────────────────────────────────
# TC: stderr 파싱 — 정상 경로
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_stderr_normal() -> None:
    """정상 stderr: 천 단위 쉼표 포함 est_tokens 파싱."""
    stderr = "[INFO] total_bytes=3,145,728 est_tokens=1,500,000"
    est_tokens, delta_pct = parse_est_tokens_from_stderr(stderr)
    assert est_tokens == 1_500_000
    assert delta_pct == 75


def test_parse_stderr_no_comma() -> None:
    """쉼표 없는 소규모 est_tokens 파싱."""
    stderr = "[INFO] total_bytes=204800 est_tokens=200000"
    est_tokens, delta_pct = parse_est_tokens_from_stderr(stderr)
    assert est_tokens == 200_000
    assert delta_pct == 10


def test_parse_stderr_zero_tokens() -> None:
    """est_tokens=0 → delta_pct=1 (최솟값 clamp)."""
    stderr = "[INFO] total_bytes=0 est_tokens=0"
    est_tokens, delta_pct = parse_est_tokens_from_stderr(stderr)
    assert est_tokens == 0
    assert delta_pct == 1


def test_parse_stderr_exact_2m() -> None:
    """est_tokens=2,000,000 → delta_pct=100."""
    stderr = "[INFO] total_bytes=8,000,000 est_tokens=2,000,000"
    est_tokens, delta_pct = parse_est_tokens_from_stderr(stderr)
    assert est_tokens == 2_000_000
    assert delta_pct == 100


def test_parse_stderr_over_2m() -> None:
    """est_tokens > 2M → delta_pct=100 (초과 clamp)."""
    stderr = "[INFO] total_bytes=10,000,000 est_tokens=2,500,000"
    est_tokens, delta_pct = parse_est_tokens_from_stderr(stderr)
    assert est_tokens == 2_500_000
    assert delta_pct == 100


# ─────────────────────────────────────────────────────────────────────────────
# TC: stderr 파싱 실패 → fallback=10
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_stderr_empty_string() -> None:
    """빈 문자열 → fallback delta=10."""
    est_tokens, delta_pct = parse_est_tokens_from_stderr("")
    assert est_tokens is None
    assert delta_pct == 10


def test_parse_stderr_no_est_tokens_key() -> None:
    """est_tokens 키 없음 → fallback delta=10."""
    stderr = "[INFO] total_bytes=1,024 some_other_key=999"
    est_tokens, delta_pct = parse_est_tokens_from_stderr(stderr)
    assert est_tokens is None
    assert delta_pct == 10


def test_parse_stderr_builder_error_output() -> None:
    """빌더 에러 출력(est_tokens 없음) → fallback delta=10."""
    stderr = "[ERROR] Template not found: unknown_template"
    est_tokens, delta_pct = parse_est_tokens_from_stderr(stderr)
    assert est_tokens is None
    assert delta_pct == 10


# ─────────────────────────────────────────────────────────────────────────────
# TC: 비율 계산 세부 검증 (소규모/중간 규모)
# ─────────────────────────────────────────────────────────────────────────────

def test_small_dump_rounds_up() -> None:
    """소규모 덤프(100K 토큰): ceiling(5.0) = 5."""
    assert calc_delta_pct(100_000) == 5


def test_tiny_dump_clamps_to_1() -> None:
    """극소규모(1 토큰): ceiling(0.00005) = 1 → clamp to 1."""
    assert calc_delta_pct(1) == 1


def test_just_above_threshold() -> None:
    """1.5M+1 토큰: ceiling(75.00005) = 76."""
    assert calc_delta_pct(1_500_001) == 76
