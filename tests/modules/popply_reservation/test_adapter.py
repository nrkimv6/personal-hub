from datetime import datetime

import pytest

from app.modules.popply_reservation.services.adapter import PopplyReservationAdapter


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    async def fetch_reservation(self, store_id, reservation_type):
        return self.payload


@pytest.mark.asyncio
async def test_popply_adapter_RIGHT_filters_target_schedule_group():
    adapter = PopplyReservationAdapter(
        FakeClient(
            {
                "reservationSchedule": [
                    {
                        "scheduleGroup": "other",
                        "reservationDate": "2026-06-01",
                        "reservationStartTime": "2026-06-01T10:00:00",
                        "currentAvailableGuests": 9,
                    },
                    {
                        "scheduleGroup": "target",
                        "reservationDate": "2026-06-01",
                        "reservationStartTime": "2026-06-01T11:00:00",
                        "currentAvailableGuests": 2,
                    },
                ]
            }
        )
    )

    result = await adapter.check(
        store_id="4727",
        reservation_type="PRE",
        target_schedule_group="target",
        schedule_date="2026-06-01",
        now=datetime(2026, 5, 1),
    )

    assert result.available_count == 2
    assert len(result.slots) == 1
    assert result.slots[0].raw["scheduleGroup"] == "target"


@pytest.mark.asyncio
async def test_popply_adapter_BOUNDARY_zero_available_guests_maps_no_slots():
    adapter = PopplyReservationAdapter(
        FakeClient(
            {
                "reservationSchedule": [
                    {
                        "scheduleGroup": "target",
                        "reservationDate": "2026-06-01",
                        "reservationStartTime": "2026-06-01T11:00:00",
                        "currentAvailableGuests": 0,
                    }
                ]
            }
        )
    )

    result = await adapter.check(
        store_id="4727",
        reservation_type="PRE",
        target_schedule_group="target",
        schedule_date="2026-06-01",
        now=datetime(2026, 5, 1),
    )

    assert result.error_message is None
    assert result.available_count == 0
    assert len(result.slots) == 1


@pytest.mark.asyncio
async def test_popply_adapter_ERROR_missing_schedule_returns_error_result():
    adapter = PopplyReservationAdapter(FakeClient({"data": {}}))

    result = await adapter.check(
        store_id="4727",
        reservation_type="PRE",
        target_schedule_group="target",
        schedule_date="2026-06-01",
    )

    assert result.error_message == "reservationSchedule missing"


@pytest.mark.asyncio
async def test_popply_adapter_RIGHT_reads_nested_reservation_schedule_and_normalizes_group():
    adapter = PopplyReservationAdapter(
        FakeClient(
            {
                "data": {
                    "reservation": {
                        "reservationSchedule": [
                            {
                                "scheduleGroup": "q%252Fabc%253D%253D",
                                "reservationDate": "2026-05-17",
                                "reservationStartTime": "2026-05-17T11:00:00",
                                "currentAvailableGuests": 1,
                            }
                        ]
                    }
                }
            }
        )
    )

    result = await adapter.check(
        store_id="4727",
        reservation_type="PRE",
        target_schedule_group="q%2Fabc%3D%3D",
        schedule_date="2026-05-17",
        now=datetime(2026, 5, 1),
    )

    assert result.error_message is None
    assert result.available_count == 1
    assert len(result.slots) == 1
    assert result.slots[0].raw["scheduleGroup"] == "q%252Fabc%253D%253D"
