"""
T3: fetchone/fetchall + 인덱스 접근 → .mappings() 이름 기반 전환 통합 TC

실제 DB 세션을 사용해 이름 기반 접근으로 올바른 값을 읽는지 재현한다.
"""
import os
import pytest
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TESTING", "1")

from sqlalchemy import text


@pytest.fixture
def seeded_worker_status(test_db_session):
    """worker_status 테이블에 active_tabs/browser_contexts 값을 seed"""
    test_db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS worker_status (
            id INTEGER PRIMARY KEY,
            pid INTEGER,
            status TEXT DEFAULT 'not_started',
            active_tasks INTEGER DEFAULT 0,
            last_heartbeat TIMESTAMP,
            memory_usage_mb REAL,
            started_at TIMESTAMP,
            global_pause INTEGER DEFAULT 0,
            paused_at TIMESTAMP,
            updated_at TIMESTAMP,
            active_tabs INTEGER DEFAULT 0,
            browser_contexts INTEGER DEFAULT 0
        )
    """))
    test_db_session.execute(text(
        "INSERT INTO worker_status (id, pid, status, active_tabs, browser_contexts) "
        "VALUES (1, 9999, 'running', 7, 3) "
        "ON CONFLICT (id) DO UPDATE SET active_tabs=7, browser_contexts=3"
    ))
    test_db_session.commit()
    return test_db_session


@pytest.fixture
def seeded_monitor_schedules(test_db_session):
    """monitor_schedules에 run_status별 행 seed (Business, BizItem 선행)"""
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule

    biz = Business(business_id="test_biz_integ", name="통합테스트업체",
                   business_type_id=13, service_type="naver")
    test_db_session.add(biz)
    test_db_session.flush()

    item = BizItem(business_id=biz.id, biz_item_id="item_integ", name="통합아이템")
    test_db_session.add(item)
    test_db_session.flush()

    for status, count in [("running", 2), ("queued", 5), ("error", 1)]:
        for i in range(count):
            test_db_session.add(MonitorSchedule(
                biz_item_id=item.id,
                date=f"2026-04-2{i}",
                is_enabled=True,
                run_status=status,
            ))
    test_db_session.commit()
    return test_db_session


@pytest.fixture
def seeded_notification_settings(test_db_session):
    """notification_settings 테이블에 1행 seed"""
    import json
    states = json.dumps(["available", "booking_success"])
    test_db_session.execute(text(
        "INSERT INTO notification_settings (id, enable_telegram, enable_desktop, notify_states) "
        "VALUES (1, true, false, :states) "
        "ON CONFLICT (id) DO UPDATE SET enable_telegram=true, enable_desktop=false, notify_states=:states"
    ), {"states": states})
    test_db_session.commit()
    return test_db_session


@pytest.fixture
def seeded_queue_schedules(test_db_session):
    """queued 스케줄 seed — get_monitoring_queue() JOIN 대상"""
    from app.models.business import Business
    from app.models.biz_item import BizItem
    from app.models.monitor_schedule import MonitorSchedule

    biz = Business(business_id="queue_biz", name="큐테스트업체",
                   business_type_id=13, service_type="naver")
    biz.business_id = "1630978"
    test_db_session.add(biz)
    test_db_session.flush()

    item = BizItem(business_id=biz.id, biz_item_id="6309731", name="큐테스트아이템")
    test_db_session.add(item)
    test_db_session.flush()

    test_db_session.add(MonitorSchedule(
        biz_item_id=item.id,
        date="2026-04-24",
        is_enabled=True,
        run_status="queued",
        interval=60,
        custom_interval=None,
    ))
    test_db_session.commit()
    return test_db_session, biz, item


class TestGetSystemResourceIntegration:

    def test_get_system_resource_reads_named_active_tabs(self, seeded_worker_status):
        """T3-R: 실 DB에서 worker_status 행을 seed하고 이름 기반으로 active_tabs/browser_contexts 읽기"""
        from app.routes.dashboard import get_system_resource

        with patch("app.routes.dashboard.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 10.0
            mem = type("M", (), {"percent": 50.0, "used": 1024**3, "total": 2 * 1024**3})()
            mock_psutil.virtual_memory.return_value = mem

            result = get_system_resource(seeded_worker_status)

        assert result.active_tabs == 7
        assert result.browser_contexts == 3


class TestGetMonitoringStatsIntegration:

    def test_get_monitoring_stats_reads_named_run_status(self, seeded_monitor_schedules):
        """T3-R: 실 DB에서 monitor_schedules seed 후 grouped status counts 읽기"""
        from app.routes.dashboard import get_monitoring_stats

        result = get_monitoring_stats(seeded_monitor_schedules)

        assert result.running == 2
        assert result.queued == 5
        assert result.error == 1


class TestGetNotificationSettingsIntegration:

    def test_get_notification_settings_reads_from_real_db(self, seeded_notification_settings):
        """T3-R: 실 DB에서 notification_settings seed 후 이름 기반 접근 검증"""
        from app.routes.notification import get_notification_settings_from_db

        Session = sessionmaker(bind=seeded_notification_settings.get_bind())

        with patch("app.routes.notification.SessionLocal", Session):
            result = get_notification_settings_from_db()

        assert result.enable_telegram is True
        assert result.enable_desktop is False
        assert "available" in result.notify_states


class TestGetMonitoringQueueIntegration:

    def test_get_monitoring_queue_reads_named_url_fields(self, seeded_queue_schedules):
        """T3-R: 실 DB에서 queued schedule seed 후 URL/interval이 이름 기반으로 생성되는지 검증"""
        from app.routes.system import get_monitoring_queue
        import asyncio

        db_session, biz, item = seeded_queue_schedules
        Session = sessionmaker(bind=db_session.get_bind())

        with patch("app.routes.system.SessionLocal", Session):
            items = asyncio.get_event_loop().run_until_complete(get_monitoring_queue())

        queue_item = next((i for i in items if i.biz_item_name == "큐테스트아이템"), None)
        assert queue_item is not None
        assert queue_item.interval == 60
        assert f"/items/{item.biz_item_id}" in queue_item.url

    def test_get_monitoring_queue_custom_interval_precedence(self, test_db_session):
        """T3-Re: custom_interval이 있으면 interval보다 우선 사용됨"""
        from app.models.business import Business
        from app.models.biz_item import BizItem
        from app.models.monitor_schedule import MonitorSchedule
        from app.routes.system import get_monitoring_queue
        import asyncio

        biz = Business(business_id="custom_biz_ci", name="커스텀업체",
                       business_type_id=13, service_type="naver")
        test_db_session.add(biz)
        test_db_session.flush()

        item = BizItem(business_id=biz.id, biz_item_id="ci_item", name="커스텀아이템")
        test_db_session.add(item)
        test_db_session.flush()

        test_db_session.add(MonitorSchedule(
            biz_item_id=item.id,
            date="2026-04-24",
            is_enabled=True,
            run_status="queued",
            interval=60,
            custom_interval=30,
        ))
        test_db_session.commit()

        Session = sessionmaker(bind=test_db_session.get_bind())
        with patch("app.routes.system.SessionLocal", Session):
            items = asyncio.get_event_loop().run_until_complete(get_monitoring_queue())

        ci_item = next((i for i in items if i.biz_item_name == "커스텀아이템"), None)
        assert ci_item is not None
        assert ci_item.interval == 30
