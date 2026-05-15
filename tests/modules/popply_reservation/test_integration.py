import json
from datetime import datetime
from pathlib import Path

import pytest

from app.modules.availability.services.state import determine_availability_status
from app.modules.popply_reservation.services.adapter import PopplyReservationAdapter


class FixtureClient:
    def __init__(self, payload):
        self.payload = payload

    async def fetch_reservation(self, store_id, reservation_type):
        return self.payload


@pytest.mark.asyncio
async def test_popply_4727_link_group_no_slots_but_public_available():
    fixture_path = Path(__file__).parent / "fixtures" / "popply_4727_pre.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    adapter = PopplyReservationAdapter(FixtureClient(payload))

    result = await adapter.check(
        store_id="4727",
        reservation_type="PRE",
        target_schedule_group="q%2Fvz6hSqSFn1IMrEDVkTtDUvIPrnxtkqkn08sdn8T9EA7XyWkp5tej4hrzR0jbrmHagBNt3As8YgLwKGsTL89A%3D%3D",
        schedule_date="2026-06-01",
        now=datetime(2026, 5, 1),
    )

    assert result.available_count == 0
    assert determine_availability_status(result.slots, available_count=result.available_count) == "no_slots"
    assert result.slots[0].raw["storeId"] == "4727"
