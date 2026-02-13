"""API 비용 추적 모듈 테스트"""
import pytest
from sqlalchemy import text
from datetime import date
from app.modules.image_classifier.workers.cost_tracker import CostTracker


@pytest.fixture
def cost_tracker(test_db):
    """CostTracker 인스턴스 생성"""
    return CostTracker(test_db)


# ================================================
# Right: 기본 동작
# ================================================

def test_record_usage_claude(cost_tracker, test_db):
    """18.1 Right: record_usage (Claude) → DB 저장"""
    cost = cost_tracker.record_usage(
        model="claude-3-sonnet",
        input_tokens=1000,
        output_tokens=500,
        image_count=10
    )

    # 비용 계산 확인 (0보다 커야 함)
    assert cost > 0

    # DB 확인
    today = date.today().isoformat()
    usage = test_db.execute(text("""
        SELECT model, input_tokens, output_tokens, image_count, estimated_cost_usd
        FROM api_usage
        WHERE date = :date AND model = 'claude-3-sonnet'
    """), {"date": today}).fetchone()

    assert usage is not None
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.image_count == 10
    assert usage.estimated_cost_usd > 0


def test_calculate_cost_claude(cost_tracker):
    """18.2 Right: _calculate_cost (Claude) → 요금 계산"""
    cost = cost_tracker._calculate_cost(
        model="claude-3-sonnet",
        input_tokens=1_000_000,  # 1M tokens
        output_tokens=1_000_000,  # 1M tokens
        image_count=1000
    )

    # Claude: $3 input + $15 output + ~$0.48 per 1K images
    # 예상: 3 + 15 + 0.48 = ~18.48
    assert 18.0 < cost < 20.0


def test_calculate_cost_gemini(cost_tracker):
    """18.3 Right: _calculate_cost (Gemini) → 저렴한 요금"""
    cost = cost_tracker._calculate_cost(
        model="gemini-flash",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        image_count=1000
    )

    # Gemini: $0.075 input + $0.30 output + ~$0.01 per 1K images
    # 예상: 0.075 + 0.30 + 0.01 = ~0.385
    assert 0.3 < cost < 0.5


def test_get_daily_usage(cost_tracker, test_db):
    """18.4 Right: get_daily_usage → 일일 사용량"""
    today = date.today().isoformat()

    # 사용량 기록
    test_db.execute(text("""
        INSERT INTO api_usage (date, model, input_tokens, output_tokens, image_count, estimated_cost_usd)
        VALUES (:date, 'claude', 1000, 500, 10, 0.025)
    """), {"date": today})
    test_db.commit()

    usage = cost_tracker.get_daily_usage(today)

    assert usage["date"] == today
    assert usage["input_tokens"] == 1000
    assert usage["output_tokens"] == 500
    assert usage["images"] == 10
    assert usage["cost"] == 0.025


def test_get_monthly_usage(cost_tracker, test_db):
    """18.5 Right: get_monthly_usage → 월간 사용량"""
    # 2023년 4월 사용량 기록
    test_db.execute(text("""
        INSERT INTO api_usage (date, model, input_tokens, output_tokens, image_count, estimated_cost_usd) VALUES
        ('2023-04-01', 'claude', 1000, 500, 10, 0.025),
        ('2023-04-15', 'gemini', 2000, 1000, 20, 0.010),
        ('2023-04-30', 'claude', 1500, 750, 15, 0.030)
    """))
    test_db.commit()

    usage = cost_tracker.get_monthly_usage(2023, 4)

    assert usage["year"] == 2023
    assert usage["month"] == 4
    assert usage["input_tokens"] == 4500
    assert usage["output_tokens"] == 2250
    assert usage["images"] == 45
    assert 0.060 < usage["cost"] < 0.070  # 합계 ~0.065


def test_check_limits_no_limit(cost_tracker, test_db):
    """18.6 Boundary: check_limits (리밋 없음) → percent=0"""
    limits = cost_tracker.check_limits()

    assert "daily" in limits
    assert "monthly" in limits

    # 리밋이 설정되지 않았으면 percent=0
    assert limits["daily"]["percent"] == 0.0
    assert limits["monthly"]["percent"] == 0.0


def test_check_limits_warning(cost_tracker, test_db):
    """18.7 Right: check_limits (80% 이상) → warning=True"""
    today = date.today().isoformat()

    # 일일 리밋 설정
    test_db.execute(text("""
        INSERT INTO api_limits (limit_type, max_cost_usd, max_images, is_active)
        VALUES ('daily', 1.0, 1000, 1)
    """))

    # 사용량 기록 (0.85 = 85%)
    test_db.execute(text("""
        INSERT INTO api_usage (date, model, input_tokens, output_tokens, image_count, estimated_cost_usd)
        VALUES (:date, 'claude', 10000, 5000, 100, 0.85)
    """), {"date": today})
    test_db.commit()

    limits = cost_tracker.check_limits()

    assert limits["daily"]["percent"] == 85.0
    assert limits["daily"]["warning"] is True
    assert limits["daily"]["exceeded"] is False


def test_should_switch_model_exceeded(cost_tracker, test_db):
    """18.8 Right: should_switch_model (초과) → 'cli' 권장"""
    today = date.today().isoformat()

    # 일일 리밋 설정
    test_db.execute(text("""
        INSERT INTO api_limits (limit_type, max_cost_usd, max_images, is_active)
        VALUES ('daily', 1.0, 1000, 1)
    """))

    # 사용량 기록 (1.5 = 150%)
    test_db.execute(text("""
        INSERT INTO api_usage (date, model, input_tokens, output_tokens, image_count, estimated_cost_usd)
        VALUES (:date, 'claude', 10000, 5000, 100, 1.5)
    """), {"date": today})
    test_db.commit()

    recommended_model = cost_tracker.should_switch_model()

    assert recommended_model == "cli"
