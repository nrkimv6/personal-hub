"""
쿠팡 모니터링 알림 시간대 필터링 유닛/통합 테스트 (T1/T2).

대상:
- CoupangMonitorService._is_within_notify_times()
- CoupangMonitorService.check_and_notify() — notify_times 시간 밖에서 알림 스킵
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
from app.modules.coupang_travel.services.api_client import VendorItem


# ── _is_within_notify_times 유닛 TC ─────────────────────────────────────────

class TestIsWithinNotifyTimes:
    """CoupangMonitorService._is_within_notify_times() 유닛 테스트."""

    def _make_dt(self, hhmm: str) -> datetime:
        """HH:MM 문자열을 datetime으로 변환 (날짜 무관)."""
        h, m = hhmm.split(":")
        return datetime(2026, 4, 12, int(h), int(m), 0)

    def test__is_within_notify_times_R_single_time(self):
        """R: times=["10:00"], 현재 10:00 → True"""
        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = self._make_dt("10:00")
            result = CoupangMonitorService._is_within_notify_times(["10:00"])
        assert result is True

    def test__is_within_notify_times_R_range(self):
        """R: times=["14:00-19:00"], 현재 15:00 → True"""
        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = self._make_dt("15:00")
            result = CoupangMonitorService._is_within_notify_times(["14:00-19:00"])
        assert result is True

    def test__is_within_notify_times_R_mixed(self):
        """R: times=["10:00","14:00-19:00"], 현재 10:00 → True (개별 시간 일치)"""
        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = self._make_dt("10:00")
            result = CoupangMonitorService._is_within_notify_times(["10:00", "14:00-19:00"])
        assert result is True

    def test__is_within_notify_times_B_empty(self):
        """B: times=None → 항상 True (미설정 = 모든 시간에 알림)"""
        result = CoupangMonitorService._is_within_notify_times(None)
        assert result is True

    def test__is_within_notify_times_B_boundary_start(self):
        """B: times=["14:00-19:00"], 정확히 14:00 → True (경계 포함)"""
        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = self._make_dt("14:00")
            result = CoupangMonitorService._is_within_notify_times(["14:00-19:00"])
        assert result is True

    def test__is_within_notify_times_B_boundary_end(self):
        """B: times=["14:00-19:00"], 정확히 19:00 → True (경계 포함)"""
        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = self._make_dt("19:00")
            result = CoupangMonitorService._is_within_notify_times(["14:00-19:00"])
        assert result is True

    def test__is_within_notify_times_E_outside_range(self):
        """E: times=["14:00-19:00"], 13:59 → False (범위 밖)"""
        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = self._make_dt("13:59")
            result = CoupangMonitorService._is_within_notify_times(["14:00-19:00"])
        assert result is False

    def test__is_within_notify_times_E_invalid_format(self):
        """E: times=["abc"] → True (파싱 실패 안전 기본값)"""
        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = self._make_dt("10:00")
            result = CoupangMonitorService._is_within_notify_times(["abc"])
        assert result is True


# ── check_and_notify 시간 필터 통합 TC ─────────────────────────────────────

class TestCheckAndNotifyTimeFilter:
    """check_and_notify()의 notify_times 필터링 동작 검증."""

    def _make_service(self):
        """mock 의존성으로 CoupangMonitorService 생성."""
        api_client = MagicMock()
        notification_service = MagicMock()
        notification_service.send_notification_message = AsyncMock()
        service = CoupangMonitorService(api_client, notification_service, db_logging=False)
        return service, api_client, notification_service

    def _make_items(self, sale_status="ON_SALE", stock_count=5):
        return [VendorItem(
            vendor_item_name="테스트상품",
            sale_status=sale_status,
            stock_count=stock_count,
        )]

    @pytest.mark.asyncio
    async def test_check_and_notify_skips_notification_outside_time(self):
        """R: notify_times=["14:00-19:00"], 현재 10:00, 변경 감지 시 _send_notification 호출 0회,
        _log_monitoring_event 미호출 (db_logging=False), _previous_statuses는 갱신됨."""
        service, api_client, notif_svc = self._make_service()

        # 1회차: 초기 상태 저장 (items 반환)
        initial_items = self._make_items(sale_status="OFF_SALE", stock_count=0)
        changed_items = self._make_items(sale_status="ON_SALE", stock_count=3)
        page = AsyncMock()

        api_client.fetch_vendor_items = AsyncMock(side_effect=[initial_items, changed_items])

        fixed_time = datetime(2026, 4, 12, 10, 0, 0)

        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_time
            # 1회차: 초기 상태 저장
            await service.check_and_notify(
                product_id="99999",
                vendor_item_package_id="pkg_test",
                dates=["2026-04-17"],
                page=page,
                notify_times=["14:00-19:00"],
            )
            # 2회차: 변경 감지, 10:00은 14:00-19:00 밖 → 알림 스킵
            changes = await service.check_and_notify(
                product_id="99999",
                vendor_item_package_id="pkg_test",
                dates=["2026-04-17"],
                page=page,
                notify_times=["14:00-19:00"],
            )

        # 변경은 감지되었지만 알림은 발송되지 않음
        assert len(changes) == 1
        notif_svc.send_notification_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_notify_sends_notification_inside_time(self):
        """R: notify_times=["14:00-19:00"], 현재 16:00, 변경 감지 시 알림 1회 발송."""
        service, api_client, notif_svc = self._make_service()

        initial_items = self._make_items(sale_status="OFF_SALE", stock_count=0)
        changed_items = self._make_items(sale_status="ON_SALE", stock_count=3)
        page = AsyncMock()

        api_client.fetch_vendor_items = AsyncMock(side_effect=[initial_items, changed_items])

        fixed_time = datetime(2026, 4, 12, 16, 0, 0)

        with patch("app.modules.coupang_travel.services.monitor_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_time
            await service.check_and_notify(
                product_id="99999",
                vendor_item_package_id="pkg_test",
                dates=["2026-04-17"],
                page=page,
                notify_times=["14:00-19:00"],
            )
            changes = await service.check_and_notify(
                product_id="99999",
                vendor_item_package_id="pkg_test",
                dates=["2026-04-17"],
                page=page,
                notify_times=["14:00-19:00"],
            )

        assert len(changes) == 1
        notif_svc.send_notification_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_notify_no_times_always_notifies(self):
        """B: notify_times=None (미설정), 변경 감지 시 항상 알림 발송."""
        service, api_client, notif_svc = self._make_service()

        initial_items = self._make_items(sale_status="OFF_SALE", stock_count=0)
        changed_items = self._make_items(sale_status="ON_SALE", stock_count=3)
        page = AsyncMock()

        api_client.fetch_vendor_items = AsyncMock(side_effect=[initial_items, changed_items])

        await service.check_and_notify(
            product_id="99999",
            vendor_item_package_id="pkg_test",
            dates=["2026-04-17"],
            page=page,
            notify_times=None,
        )
        await service.check_and_notify(
            product_id="99999",
            vendor_item_package_id="pkg_test",
            dates=["2026-04-17"],
            page=page,
            notify_times=None,
        )

        notif_svc.send_notification_message.assert_called_once()
