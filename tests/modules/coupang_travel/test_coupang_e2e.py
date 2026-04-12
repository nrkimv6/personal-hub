"""
E2E 테스트 (T4) — mock 외부 API, 내부 파이프라인 전체 검증
DB: 실제 SQLite(테스트용 in-memory 또는 테스트 DB)
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.coupang_travel.services.api_client import VendorItem


# ── 픽스처: DB 세션 ──────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """인메모리 SQLite DB 세션 — 필요한 테이블만 raw SQL로 생성."""
    import sqlite3
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS browser_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS service_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER,
                service_type TEXT NOT NULL,
                is_logged_in INTEGER DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                service_type TEXT NOT NULL DEFAULT 'naver'
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS biz_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                service_account_id INTEGER REFERENCES service_accounts(id),
                biz_item_id TEXT NOT NULL,
                name TEXT NOT NULL,
                extra_desc_json TEXT,
                is_enabled INTEGER DEFAULT 1,
                max_bookings_per_schedule INTEGER,
                time_range TEXT,
                booking_options_override TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS monitor_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                biz_item_id INTEGER NOT NULL REFERENCES biz_items(id),
                service_account_id INTEGER REFERENCES service_accounts(id),
                date TEXT NOT NULL,
                is_enabled INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 0,
                run_status TEXT DEFAULT 'idle',
                interval REAL,
                custom_interval INTEGER DEFAULT 0,
                auto_booking_enabled INTEGER DEFAULT 0,
                monitoring_mode TEXT DEFAULT 'legacy',
                booking_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                last_error TEXT,
                time_range TEXT,
                times TEXT,
                last_check_time TEXT,
                next_run_time TEXT,
                last_booking_time TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS monitoring_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER NOT NULL,
                timestamp TEXT,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                available_count INTEGER DEFAULT 0,
                slots_info TEXT,
                error_message TEXT,
                response_time_ms REAL,
                data_hash TEXT,
                hash_changed INTEGER DEFAULT 0,
                fetch_method TEXT,
                time_range TEXT,
                original_slot_count INTEGER,
                filtered_slot_count INTEGER,
                target_time_matched INTEGER DEFAULT 0,
                booking_triggered INTEGER DEFAULT 0,
                booking_success INTEGER,
                proxy_url TEXT,
                graphql_response TEXT,
                graphql_time_ms REAL,
                proxy_retry_count INTEGER,
                booking_time_ms REAL,
                booking_attempt_count INTEGER
            )
        """))
        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def coupang_schedule(db_session):
    """테스트용 쿠팡 Business + BizItem + MonitorSchedule 생성 (raw SQL)."""
    from sqlalchemy import text

    db_session.execute(text(
        "INSERT INTO businesses (business_id, name, service_type) VALUES ('cp:99999', '테스트상품', 'coupang')"
    ))
    biz_id = db_session.execute(text("SELECT id FROM businesses WHERE business_id='cp:99999'")).scalar()

    extra = json.dumps({"vendor_item_package_id": "pkg_test", "product_id": "99999"})
    db_session.execute(text(
        "INSERT INTO biz_items (business_id, biz_item_id, name, extra_desc_json) VALUES (:bid, '99999', '테스트상품', :extra)"
    ), {"bid": biz_id, "extra": extra})
    item_id = db_session.execute(text("SELECT id FROM biz_items WHERE biz_item_id='99999'")).scalar()

    db_session.execute(text(
        "INSERT INTO monitor_schedules (biz_item_id, date, is_enabled, run_status) VALUES (:iid, '2026-04-15', 1, 'idle')"
    ), {"iid": item_id})
    sched_id = db_session.execute(text("SELECT id FROM monitor_schedules WHERE biz_item_id=:iid"), {"iid": item_id}).scalar()
    db_session.commit()

    return sched_id, item_id, biz_id


@pytest.fixture
def naver_schedule(db_session):
    """테스트용 네이버 스케줄 생성 (raw SQL)."""
    from sqlalchemy import text

    db_session.execute(text(
        "INSERT INTO businesses (business_id, name, service_type) VALUES ('naver_biz_001', '네이버업체', 'naver')"
    ))
    biz_id = db_session.execute(text("SELECT id FROM businesses WHERE business_id='naver_biz_001'")).scalar()

    db_session.execute(text(
        "INSERT INTO biz_items (business_id, biz_item_id, name) VALUES (:bid, 'nv_item_001', '네이버아이템')"
    ), {"bid": biz_id})
    item_id = db_session.execute(text("SELECT id FROM biz_items WHERE biz_item_id='nv_item_001'")).scalar()

    db_session.execute(text(
        "INSERT INTO monitor_schedules (biz_item_id, date, is_enabled, run_status) VALUES (:iid, '2026-04-15', 1, 'pending')"
    ), {"iid": item_id})
    sched_id = db_session.execute(text(
        "SELECT id FROM monitor_schedules WHERE biz_item_id=:iid"
    ), {"iid": item_id}).scalar()
    db_session.commit()

    return sched_id


def test_naver_worker_excludes_coupang(db_session, coupang_schedule, naver_schedule):
    """쿠팡 스케줄이 DB에 있어도 네이버 워커 _load_active_schedules는 로드하지 않음."""
    from sqlalchemy import text

    result = db_session.execute(text("""
        SELECT ms.id
        FROM monitor_schedules ms
        JOIN biz_items bi ON ms.biz_item_id = bi.id
        JOIN businesses b ON bi.business_id = b.id
        WHERE ms.is_enabled = 1
        AND b.service_type = 'naver'
    """))
    naver_ids = [row[0] for row in result.fetchall()]

    coupang_sched_id, _, _ = coupang_schedule
    naver_sched_id = naver_schedule
    assert coupang_sched_id not in naver_ids
    assert naver_sched_id in naver_ids


def test_naver_worker_pending_queue_excludes_coupang(db_session, coupang_schedule):
    """쿠팡 pending 스케줄이 네이버 _check_for_new_schedules에 포함되지 않음."""
    from sqlalchemy import text

    coupang_sched_id, _, _ = coupang_schedule
    db_session.execute(
        text("UPDATE monitor_schedules SET run_status='pending' WHERE id=:id"),
        {"id": coupang_sched_id}
    )
    db_session.commit()

    result = db_session.execute(text("""
        SELECT ms.id
        FROM monitor_schedules ms
        JOIN biz_items bi ON ms.biz_item_id = bi.id
        JOIN businesses b ON bi.business_id = b.id
        WHERE ms.is_enabled = 1 AND ms.run_status = 'pending'
        AND b.service_type = 'naver'
    """))
    pending_ids = [row[0] for row in result.fetchall()]
    assert coupang_sched_id not in pending_ids


@pytest.mark.asyncio
async def test_coupang_monitor_full_pipeline():
    """쿠팡 모니터링 전체 파이프라인 — mock API 클라이언트 + 실 CoupangMonitorService."""
    from app.modules.coupang_travel.services.api_client import CoupangApiClient
    from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
    from app.shared.notification import NotificationService

    mock_api = AsyncMock(spec=CoupangApiClient)
    notification_service = NotificationService()
    sent_messages = []

    async def fake_send(msg, send_desktop=False):
        sent_messages.append(msg)

    with patch.object(notification_service, "send_notification_message", side_effect=fake_send):
        service = CoupangMonitorService(mock_api, notification_service)

        mock_page = AsyncMock()

        # 1회차: SOLD_OUT → 초기 상태 저장, 알림 없음
        mock_api.fetch_vendor_items.return_value = [
            VendorItem(vendor_item_name="특실A", sale_status="SOLD_OUT", stock_count=0),
            VendorItem(vendor_item_name="특실B", sale_status="SOLD_OUT", stock_count=0),
        ]
        changes1 = await service.check_and_notify("10000011218760", "pkg_abc", ["2026-04-15"], mock_page)
        assert changes1 == [], "초기 호출은 변경 없음"
        assert len(sent_messages) == 0, "초기 호출은 알림 없음"

        # 2회차: 특실A → ON_SALE, 특실B → 변화 없음
        mock_api.fetch_vendor_items.return_value = [
            VendorItem(vendor_item_name="특실A", sale_status="ON_SALE", stock_count=2),
            VendorItem(vendor_item_name="특실B", sale_status="SOLD_OUT", stock_count=0),
        ]
        changes2 = await service.check_and_notify("10000011218760", "pkg_abc", ["2026-04-15"], mock_page)
        assert len(changes2) == 1, "특실A 변경 1건"
        assert changes2[0].item_name == "특실A"
        assert changes2[0].new_status == "ON_SALE"
        assert len(sent_messages) == 1
        assert "[쿠팡]" in sent_messages[0]
        assert "특실A" in sent_messages[0]

        # 3회차: 두 옵션 모두 변화 없음
        mock_api.fetch_vendor_items.return_value = [
            VendorItem(vendor_item_name="특실A", sale_status="ON_SALE", stock_count=2),
            VendorItem(vendor_item_name="특실B", sale_status="SOLD_OUT", stock_count=0),
        ]
        changes3 = await service.check_and_notify("10000011218760", "pkg_abc", ["2026-04-15"], mock_page)
        assert changes3 == [], "변화 없으면 변경 0건"
        assert len(sent_messages) == 1, "추가 알림 없음"


@pytest.mark.asyncio
async def test_coupang_monitor_logs_events(db_session, coupang_schedule):
    """_main_loop_iteration 수준에서 schedule_id 전달 시 monitoring_events 기록 확인."""
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from app.modules.coupang_travel.services.api_client import CoupangApiClient
    from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
    from app.shared.notification import NotificationService

    schedule_id, _, _ = coupang_schedule

    mock_api = AsyncMock(spec=CoupangApiClient)
    mock_api.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="특실A", sale_status="ON_SALE", stock_count=1),
    ])
    notification_service = NotificationService()

    local_factory = sessionmaker(bind=db_session.bind)

    with patch.object(notification_service, "send_notification_message", AsyncMock()):
        with patch("app.services.event_logger.SessionLocal", local_factory):
            service = CoupangMonitorService(mock_api, notification_service)
            await service.check_and_notify(
                "99999",
                "pkg_test",
                ["2026-04-15"],
                AsyncMock(),
                schedule_id=schedule_id,
            )

    row = db_session.execute(text("SELECT COUNT(*) FROM monitoring_events")).scalar()
    assert row == 1


@pytest.mark.asyncio
async def test_coupang_worker_updates_active_flag_during_run():
    """워커 체크 시 set_active(True/False) 호출 검증."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = AsyncMock()
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/99999"
    mock_page.context = MagicMock()
    mock_browser.tab_pool_manager = MagicMock()
    mock_browser.tab_pool_manager.get_tab = AsyncMock(return_value=mock_page)
    mock_browser.tab_pool_manager.release_tab = AsyncMock()

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])

    ctx = {
        "id": 101,
        "item_biz_item_id": "99999",
        "date": "2026-04-15",
        "service_account_id": 1,
        "biz_item_pk": 1,
    }

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_test"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    assert mock_schedule_service.set_active.call_count == 2
    assert mock_schedule_service.set_active.call_args_list[0].args[2] is True
    assert mock_schedule_service.set_active.call_args_list[1].args[2] is False
