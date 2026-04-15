"""
통합 테스트 — mock 기반 내부 파이프라인 검증
DB: 실제 SQLite(테스트용 in-memory 또는 테스트 DB)
"""
import json
from datetime import datetime
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

    async def fake_send(msg, send_desktop=False, send_telegram: bool = True, **_kwargs):
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
async def test_coupang_monitor_service_records_fetched_checked_at():
    from app.modules.coupang_travel.services.api_client import CoupangApiClient
    from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
    from app.shared.notification import NotificationService

    mock_api = AsyncMock(spec=CoupangApiClient)
    mock_api.fetch_vendor_items = AsyncMock(return_value=[
        VendorItem(vendor_item_name="특실A", sale_status="ON_SALE", stock_count=1),
    ])
    notification_service = NotificationService()
    fixed = datetime(2026, 4, 15, 10, 0, 0)

    with patch.object(notification_service, "send_notification_message", AsyncMock()):
        with patch(
            "app.modules.coupang_travel.services.monitor_service.datetime"
        ) as datetime_module:
            datetime_module.now.return_value = fixed
            with patch(
                "app.modules.coupang_travel.services.monitor_service.EventLogger.log_monitoring_event"
            ) as log_event:
                service = CoupangMonitorService(mock_api, notification_service)
                await service.check_and_notify(
                    "99999",
                    "pkg_test",
                    ["2026-04-15"],
                    AsyncMock(),
                    schedule_id=1,
                )

    kwargs = log_event.call_args.kwargs
    assert kwargs["timestamp"] == fixed


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


def test_coupang_worker_init_clears_stale_is_active_R(db_session):
    """R(Right): 워커 초기화 시 coupang 스케줄의 stale is_active를 정리."""
    from sqlalchemy import text
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    db_session.execute(text(
        "INSERT INTO businesses (business_id, name, service_type) VALUES ('cp:stale', '쿠팡상품', 'coupang')"
    ))
    business_id = db_session.execute(text(
        "SELECT id FROM businesses WHERE business_id='cp:stale'"
    )).scalar()
    db_session.execute(text(
        "INSERT INTO biz_items (business_id, biz_item_id, name, extra_desc_json) VALUES (:bid, 'stale-item', '쿠팡상품', :extra)"
    ), {
        "bid": business_id,
        "extra": json.dumps({"vendor_item_package_id": "pkg_stale", "product_id": "stale-item"}),
    })
    item_id = db_session.execute(text(
        "SELECT id FROM biz_items WHERE biz_item_id='stale-item'"
    )).scalar()
    db_session.execute(text(
        "INSERT INTO monitor_schedules (biz_item_id, date, is_enabled, is_active, run_status) VALUES (:iid, '2026-04-15', 1, 1, 'running')"
    ), {"iid": item_id})
    db_session.commit()

    worker = CoupangMonitorWorker()
    with patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=db_session):
        cleaned = worker._cleanup_stale_active_schedules()

    assert cleaned == 1
    row = db_session.execute(text(
        "SELECT is_active, run_status FROM monitor_schedules WHERE biz_item_id=:iid"
    ), {"iid": item_id}).fetchone()
    assert row[0] == 0
    assert row[1] == "idle"


def test_coupang_worker_health_recent_event_healthy(orm_db_session_with_events, monkeypatch):
    """T3: heartbeat가 없어도 최근 이벤트가 있으면 worker_health는 healthy."""
    from datetime import datetime, timedelta
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.monitoring_event import MonitoringEvent
    from app.modules.coupang_travel.routes import monitor as coupang_monitor_route

    db = orm_db_session_with_events

    biz = Business(business_id="cp:health_recent", name="건강한쿠팡", service_type="coupang")
    db.add(biz)
    db.flush()
    item = BizItem(business_id=biz.id, biz_item_id="health_recent_item", name="건강한아이템")
    db.add(item)
    db.flush()
    schedule = MonitorSchedule(biz_item_id=item.id, date="2026-12-10", is_enabled=True)
    db.add(schedule)
    db.flush()
    db.add(MonitoringEvent(
        schedule_id=schedule.id,
        event_type="check",
        status="no_slots",
        available_count=0,
        timestamp=datetime.now() - timedelta(seconds=30),
    ))
    db.commit()

    monkeypatch.setattr(coupang_monitor_route.WorkerHealthRedis, "check", lambda worker_type: None)

    health = coupang_monitor_route._build_worker_health(db)
    assert health.status == "healthy"
    assert health.last_event_at is not None
    assert "최근" in health.message or "정상" in health.message


def test_coupang_worker_health_stale_then_not_started(orm_db_session_with_events, monkeypatch):
    """T3: 오래된 이벤트는 stale, 이벤트도 없으면 not_started."""
    from datetime import datetime, timedelta
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.monitoring_event import MonitoringEvent
    from app.modules.coupang_travel.routes import monitor as coupang_monitor_route

    db = orm_db_session_with_events
    monkeypatch.setattr(coupang_monitor_route.WorkerHealthRedis, "check", lambda worker_type: None)

    biz = Business(business_id="cp:health_stale", name="오래된쿠팡", service_type="coupang")
    db.add(biz)
    db.flush()
    item = BizItem(business_id=biz.id, biz_item_id="health_stale_item", name="오래된아이템")
    db.add(item)
    db.flush()
    schedule = MonitorSchedule(biz_item_id=item.id, date="2026-12-11", is_enabled=True)
    db.add(schedule)
    db.flush()
    db.add(MonitoringEvent(
        schedule_id=schedule.id,
        event_type="check",
        status="no_slots",
        available_count=0,
        timestamp=datetime.now() - timedelta(seconds=120),
    ))
    db.commit()

    stale_health = coupang_monitor_route._build_worker_health(db)
    assert stale_health.status == "stale"
    assert stale_health.last_event_at is not None

    db.query(MonitoringEvent).delete()
    db.query(MonitorSchedule).delete()
    db.query(BizItem).delete()
    db.query(Business).delete()
    db.commit()

    not_started_health = coupang_monitor_route._build_worker_health(db)
    assert not_started_health.status == "not_started"
    assert not_started_health.last_event_at is None


# ── T4: 알림 시간대 필터링 E2E ────────────────────────────────────────────────

@pytest.fixture
def orm_db_session():
    """ORM 기반 in-memory SQLite 세션 — schedule_service.get_all_with_context() 테스트용.
    MonitoringEvent 포함 (get_all_with_context가 _get_last_events 서브쿼리를 사용하므로 필수).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.base import Base
    from app.models.browser_profile import BrowserProfile
    from app.models.service_account import ServiceAccount
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.monitoring_event import MonitoringEvent

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        BrowserProfile.__table__,
        ServiceAccount.__table__,
        Business.__table__,
        BizItem.__table__,
        MonitorSchedule.__table__,
        MonitoringEvent.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)

    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_coupang_e2e_notify_time_filter_pipeline():
    """T4: notify_times 필터링 E2E — 10:00은 알림 없음, 16:00은 알림 1회."""
    from datetime import datetime
    from unittest.mock import patch
    from app.modules.coupang_travel.services.api_client import CoupangApiClient
    from app.modules.coupang_travel.services import monitor_service as service_module
    from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
    from app.shared.notification import NotificationService

    def _make_side_effect():
        return [
            [VendorItem(vendor_item_name="특실A", sale_status="OFF_SALE", stock_count=0)],
            [VendorItem(vendor_item_name="특실A", sale_status="ON_SALE", stock_count=3)],
        ]

    # ─ 시나리오 1: 10:00 → 알림 시간 밖 → 알림 0회 ─
    mock_api_1 = AsyncMock(spec=CoupangApiClient)
    mock_api_1.fetch_vendor_items = AsyncMock(side_effect=_make_side_effect())
    notif_1 = NotificationService()
    sent_1 = []

    async def fake_send_1(msg, send_desktop=False, send_telegram: bool = True, **_kwargs):
        sent_1.append(msg)

    service_1 = CoupangMonitorService(mock_api_1, notif_1, db_logging=False)

    with patch.object(service_module.settings, "MEGABEAUTY_KAKAO_ALERT_ENABLED", False):
        with patch.object(notif_1, "send_notification_message", side_effect=fake_send_1):
            page = AsyncMock()
            fixed_outside = datetime(2026, 4, 17, 10, 0, 0)
            with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_outside
                await service_1.check_and_notify("99999", "pkg_test", ["2026-04-17"], page, notify_times=["14:00-19:00"])
                changes_1 = await service_1.check_and_notify("99999", "pkg_test", ["2026-04-17"], page, notify_times=["14:00-19:00"])

    assert len(changes_1) == 1, "변경은 감지되어야 함"
    assert len(sent_1) == 0, f"10:00은 알림 시간 밖 → 알림 없어야 함, 실제: {len(sent_1)}"

    # ─ 시나리오 2: 16:00 → 알림 시간 안 → 알림 1회 ─
    mock_api_2 = AsyncMock(spec=CoupangApiClient)
    mock_api_2.fetch_vendor_items = AsyncMock(side_effect=_make_side_effect())
    notif_2 = NotificationService()
    sent_2 = []

    async def fake_send_2(msg, send_desktop=False, send_telegram: bool = True, **_kwargs):
        sent_2.append(msg)

    service_2 = CoupangMonitorService(mock_api_2, notif_2, db_logging=False)

    with patch.object(service_module.settings, "MEGABEAUTY_KAKAO_ALERT_ENABLED", False):
        with patch.object(notif_2, "send_notification_message", side_effect=fake_send_2):
            page2 = AsyncMock()
            fixed_inside = datetime(2026, 4, 17, 16, 0, 0)
            with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt2:
                mock_dt2.now.return_value = fixed_inside
                await service_2.check_and_notify("99999", "pkg_test", ["2026-04-17"], page2, notify_times=["14:00-19:00"])
                changes_2 = await service_2.check_and_notify("99999", "pkg_test", ["2026-04-17"], page2, notify_times=["14:00-19:00"])

    assert len(changes_2) == 1, "변경은 감지되어야 함"
    assert len(sent_2) == 1, f"16:00은 알림 시간 안 → 알림 1회여야 함, 실제: {len(sent_2)}"


def test_coupang_e2e_schedule_with_times_in_context(orm_db_session):
    """T4: times 필드 포함 스케줄 → schedule_service.get_all_with_context()가 List[str]로 반환."""
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.services.schedule_service import schedule_service

    db = orm_db_session

    biz = Business(business_id="cp:times_test_99999", name="시간대테스트상품", service_type="coupang")
    db.add(biz)
    db.flush()

    item = BizItem(business_id=biz.id, biz_item_id="times_test_99999", name="시간대테스트아이템")
    db.add(item)
    db.flush()

    schedule = MonitorSchedule(
        biz_item_id=item.id,
        date="2026-04-17",
        is_enabled=True,
        times='["10:00","14:00-19:00"]',
    )
    db.add(schedule)
    db.commit()

    contexts = schedule_service.get_all_with_context(db, service_type="coupang")
    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx["times"] == ["10:00", "14:00-19:00"], (
        f"times가 List[str]로 파싱되어야 함, 실제: {ctx['times']!r}"
    )


# ── T3: last_event 통합 TC ──────────────────────────────────────────────────────

@pytest.fixture
def orm_db_session_with_events():
    """ORM 기반 in-memory SQLite — MonitoringEvent 포함 (T3 last_event 통합 검증용)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.base import Base
    from app.models.browser_profile import BrowserProfile
    from app.models.service_account import ServiceAccount
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.monitoring_event import MonitoringEvent

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        BrowserProfile.__table__,
        ServiceAccount.__table__,
        Business.__table__,
        BizItem.__table__,
        MonitorSchedule.__table__,
        MonitoringEvent.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)

    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()
    engine.dispose()


def test_get_all_with_context_last_event_fields_T3(orm_db_session_with_events):
    """T3: schedule + event 삽입 후 get_all_with_context() 호출 →
    last_event_at / last_event_status가 실제 값으로 반환됨 (mock 최소화, 인메모리 DB).
    """
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.monitoring_event import MonitoringEvent
    from app.services.schedule_service import schedule_service

    db = orm_db_session_with_events

    biz = Business(business_id="cp:t3_test_001", name="T3테스트상품", service_type="coupang")
    db.add(biz)
    db.flush()

    item = BizItem(business_id=biz.id, biz_item_id="t3_item_001", name="T3아이템")
    db.add(item)
    db.flush()

    schedule = MonitorSchedule(biz_item_id=item.id, date="2026-11-20", is_enabled=True)
    db.add(schedule)
    db.flush()

    event = MonitoringEvent(
        schedule_id=schedule.id,
        event_type="check",
        status="success",
        available_count=2,
    )
    db.add(event)
    db.commit()

    contexts = schedule_service.get_all_with_context(db, service_type="coupang")
    assert len(contexts) == 1
    ctx = contexts[0]

    assert "last_event_at" in ctx, "last_event_at 키가 없음"
    assert "last_event_status" in ctx, "last_event_status 키가 없음"
    assert ctx["last_event_at"] is not None, "이벤트가 있는데 last_event_at이 None"
    assert ctx["last_event_status"] == "success", (
        f"last_event_status가 'success'여야 함, 실제: {ctx['last_event_status']!r}"
    )


def test_get_all_with_context_no_event_null_T3(orm_db_session_with_events):
    """T3: 이벤트 없는 schedule → last_event_at=None, last_event_status=None."""
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.services.schedule_service import schedule_service

    db = orm_db_session_with_events

    biz = Business(business_id="cp:t3_test_002", name="T3테스트상품2", service_type="coupang")
    db.add(biz)
    db.flush()

    item = BizItem(business_id=biz.id, biz_item_id="t3_item_002", name="T3아이템2")
    db.add(item)
    db.flush()

    schedule = MonitorSchedule(biz_item_id=item.id, date="2026-11-21", is_enabled=True)
    db.add(schedule)
    db.commit()

    contexts = schedule_service.get_all_with_context(db, service_type="coupang")
    assert len(contexts) == 1
    ctx = contexts[0]

    assert ctx.get("last_event_at") is None, (
        f"이벤트 없는데 last_event_at={ctx.get('last_event_at')!r}"
    )
    assert ctx.get("last_event_status") is None


# ── T4: last_event 혼합 상태 ─────────────────────────────────────────────────────

def test_schedule_last_event_mixed_status_e2e(orm_db_session_with_events):
    """T4: schedule 2개, event 각각 success/error → last_event_status 독립 반환."""
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.monitoring_event import MonitoringEvent
    from app.services.schedule_service import schedule_service

    db = orm_db_session_with_events

    # Schedule A — success 이벤트
    biz_a = Business(business_id="cp:t4_mixed_001", name="T4혼합상품A", service_type="coupang")
    db.add(biz_a)
    db.flush()
    item_a = BizItem(business_id=biz_a.id, biz_item_id="t4_item_001a", name="T4아이템A")
    db.add(item_a)
    db.flush()
    sched_a = MonitorSchedule(biz_item_id=item_a.id, date="2026-12-01", is_enabled=True)
    db.add(sched_a)
    db.flush()
    db.add(MonitoringEvent(schedule_id=sched_a.id, event_type="check", status="success", available_count=1))

    # Schedule B — error 이벤트
    biz_b = Business(business_id="cp:t4_mixed_002", name="T4혼합상품B", service_type="coupang")
    db.add(biz_b)
    db.flush()
    item_b = BizItem(business_id=biz_b.id, biz_item_id="t4_item_001b", name="T4아이템B")
    db.add(item_b)
    db.flush()
    sched_b = MonitorSchedule(biz_item_id=item_b.id, date="2026-12-02", is_enabled=True)
    db.add(sched_b)
    db.flush()
    db.add(MonitoringEvent(schedule_id=sched_b.id, event_type="check", status="error", available_count=0))

    db.commit()

    contexts = schedule_service.get_all_with_context(db, service_type="coupang")
    assert len(contexts) == 2, f"schedule 2개여야 함, 실제: {len(contexts)}"

    ctx_by_id = {c["id"]: c for c in contexts}

    ctx_a = ctx_by_id[sched_a.id]
    ctx_b = ctx_by_id[sched_b.id]

    assert ctx_a["last_event_status"] == "success", (
        f"A의 last_event_status가 'success'여야 함, 실제: {ctx_a['last_event_status']!r}"
    )
    assert ctx_a["last_event_at"] is not None

    assert ctx_b["last_event_status"] == "error", (
        f"B의 last_event_status가 'error'여야 함, 실제: {ctx_b['last_event_status']!r}"
    )
    assert ctx_b["last_event_at"] is not None


# ── T4: 프록시 E2E 파이프라인 ───────────────────────────────────────────────────

async def test_coupang_proxy_e2e():
    """T4: mock ProxyManager + mock aiohttp → CoupangHttpClient → CoupangMonitorService 전체 흐름 검증.

    검증 대상:
    - HTTP 클라이언트가 ProxyManager에서 프록시를 획득하여 vendor-items API 호출
    - 응답을 CoupangMonitorService.check_and_notify(prefetched_items=...) 경로로 전달
    - ProxyUsageLogger.log_attempt() 호출 확인 (성공 경로)
    - 상태 변경 감지 후 알림 발송 확인
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.coupang_travel.services.api_client import VendorItem
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient
    from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
    from app.shared.notification import NotificationService

    # ─ mock ProxyManager ─
    mock_pm = MagicMock()
    mock_pm.get_fresh_proxy = MagicMock(return_value="http://proxy1:8080")
    mock_pm.mark_failed = MagicMock()

    # ─ mock ProxyUsageLogger ─
    mock_logger = MagicMock()
    mock_logger.start_request = MagicMock(return_value="req-e2e-001")
    mock_logger.log_attempt = MagicMock()

    # ─ mock aiohttp 응답 ─
    vendor_items_data = {
        "travelItems": [
            {
                "vendorItems": [
                    {"vendorItemName": "한라산E2E", "saleStatus": "AVAILABLE", "stockCount": 2},
                ]
            }
        ]
    }
    get_resp = MagicMock()
    get_resp.status = 200
    get_resp.__aenter__ = AsyncMock(return_value=get_resp)
    get_resp.__aexit__ = AsyncMock(return_value=None)

    post_resp = MagicMock()
    post_resp.status = 200
    post_resp.json = AsyncMock(return_value=vendor_items_data)
    post_resp.__aenter__ = AsyncMock(return_value=post_resp)
    post_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=get_resp)
    mock_session.post = MagicMock(return_value=post_resp)

    # ─ HTTP 클라이언트 초기화 ─
    http_client = CoupangHttpClient(proxy_manager=mock_pm, proxy_usage_logger=mock_logger)
    http_client._session = mock_session

    # ─ HTTP 호출 ─
    items = await http_client.fetch_vendor_items(
        product_id="e2e_product",
        vendor_item_package_id="pkg_e2e",
        select_date="2026-05-01",
        schedule_id=99,
    )
    assert items is not None
    assert len(items) == 1
    assert items[0].sale_status == "AVAILABLE"

    # ProxyUsageLogger 호출 검증
    mock_logger.start_request.assert_called_once()
    mock_logger.log_attempt.assert_called_once()
    log_call = mock_logger.log_attempt.call_args.kwargs
    assert log_call["success"] is True

    # ─ MonitorService에 prefetched_items 전달 → 상태 변경 감지 ─
    mock_api = AsyncMock()
    notif_svc = NotificationService()
    notifications_sent = []

    async def fake_send(msg, send_desktop=False, send_telegram: bool = True, **_kwargs):
        notifications_sent.append(msg)

    service = CoupangMonitorService(mock_api, notif_svc, db_logging=False)

    with patch.object(notif_svc, "send_notification_message", side_effect=fake_send):
        # 1차 호출: 상태 초기화 (알림 없음)
        changes1 = await service.check_and_notify(
            product_id="e2e_product",
            vendor_item_package_id="pkg_e2e",
            dates=["2026-05-01"],
            prefetched_items=items,
        )
        assert changes1 == []  # 최초 → 알림 없음

        # 2차 호출: 상태 변경 (SOLD_OUT)
        changed_items = [VendorItem(vendor_item_name="한라산E2E", sale_status="SOLD_OUT", stock_count=0)]
        changes2 = await service.check_and_notify(
            product_id="e2e_product",
            vendor_item_package_id="pkg_e2e",
            dates=["2026-05-01"],
            prefetched_items=changed_items,
        )
        assert len(changes2) == 1
        assert changes2[0].new_status == "SOLD_OUT"
        assert len(notifications_sent) == 1  # 알림 발송됨
