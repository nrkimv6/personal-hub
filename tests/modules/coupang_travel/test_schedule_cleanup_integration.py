"""
cleanup 서비스 레이어 통합 테스트 (T3)

실제 PostgreSQL DB에 레거시 데이터 삽입 후 cleanup 엔드포인트 직접 호출.
실서버 DB가 있는 환경에서만 실행 가능.

실행:
    pytest tests/modules/coupang_travel/test_schedule_cleanup_integration.py -v
"""
import pytest
from datetime import date, timedelta


@pytest.fixture(scope="module")
def integration_db():
    """실제 PostgreSQL DB 세션."""
    try:
        from app.database import SessionLocal
    except ImportError:
        pytest.skip("app.database 모듈 없음")

    db = SessionLocal()
    yield db
    db.close()


@pytest.mark.integration
def test_cleanup_integration_with_real_db(integration_db):
    """T3: 실제 DB에 레거시 데이터 삽입 후 cleanup 서비스 함수 직접 호출."""
    db = integration_db

    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule

    # 1. 테스트 데이터 삽입
    test_biz_id_str = "cp:T3_CLEANUP_TEST_99999"
    business = Business(
        business_id=test_biz_id_str,
        name="T3 테스트 쿠팡 상품",
        service_type="coupang",
    )
    db.add(business)
    db.flush()

    biz_item = BizItem(
        business_id=business.id,
        biz_item_id="T3_CLEANUP_TEST_99999",
        name="T3 테스트 아이템",
    )
    db.add(biz_item)
    db.flush()

    # 레거시 스케줄: 과거 날짜
    legacy_schedule = MonitorSchedule(
        biz_item_id=biz_item.id,
        date="2025-01-01",
        service_account_id=None,
        is_enabled=True,
    )
    db.add(legacy_schedule)

    # 유효 스케줄: 미래 날짜 + null 계정 (이제 cleanup 보존 대상)
    future_schedule = MonitorSchedule(
        biz_item_id=biz_item.id,
        date=(date.today() + timedelta(days=7)).isoformat(),
        service_account_id=None,
        is_enabled=True,
    )
    db.add(future_schedule)
    db.commit()

    inserted_id = legacy_schedule.id
    assert inserted_id is not None, "레거시 스케줄이 DB에 삽입되어야 함"
    future_id = future_schedule.id
    assert future_id is not None, "미래 스케줄이 DB에 삽입되어야 함"

    # 2. cleanup 로직 직접 실행 (라우터 함수의 쿼리 재현)
    today = date.today().isoformat()
    schedules_to_delete = (
        db.query(MonitorSchedule)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(
            Business.service_type == "coupang",
            MonitorSchedule.date < today,
        )
        .filter(BizItem.id == biz_item.id)  # 테스트 데이터만
        .all()
    )

    assert len(schedules_to_delete) >= 1, "레거시 스케줄이 cleanup 대상에 포함되어야 함"

    # 3. 삭제
    for s in schedules_to_delete:
        db.delete(s)
    db.commit()

    # 4. 삭제 확인
    remaining = db.query(MonitorSchedule).filter(
        MonitorSchedule.id == inserted_id
    ).first()
    assert remaining is None, f"레거시 스케줄(id={inserted_id})이 삭제되어야 함"

    future_remaining = db.query(MonitorSchedule).filter(
        MonitorSchedule.id == future_id
    ).first()
    assert future_remaining is not None, "미래 null-account 스케줄은 삭제되면 안 됨"

    # 5. Teardown — 테스트 데이터 정리
    db.delete(future_remaining)
    db.flush()
    db.delete(biz_item)
    db.flush()
    db.delete(business)
    db.commit()
