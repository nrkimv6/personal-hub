"""
네이버 예약 슬롯 정보 확인 스크립트

Usage:
    cd D:/work/project/tools/monitor-page
    python scripts/check_slots.py

릴리영N강남 (business_id=1269828):
- 에스테덤 (6309738)
- LBB (6309741)
- 리쥬란 (6309745)
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.naver_graphql_client import NaverGraphQLClient


# 릴리영N강남 상품 정보
BUSINESS_TYPE_ID = 13
BUSINESS_ID = "1269828"

# 상품 ID
ITEMS = {
    "에스테덤": "6309738",
    "LBB": "6309741",
    "리쥬란": "6309745",
}


async def check_item_slots(client: NaverGraphQLClient, item_name: str, biz_item_id: str, start_date: str):
    """특정 상품의 슬롯 정보 조회"""
    print(f"\n{'='*60}")
    print(f"상품: {item_name} (biz_item_id={biz_item_id})")
    print(f"{'='*60}")

    schedule = await client.fetch_schedule(
        business_type_id=BUSINESS_TYPE_ID,
        business_id=BUSINESS_ID,
        biz_item_id=biz_item_id,
        start_date=start_date,
        days_ahead=14  # 2주간 조회
    )

    if not schedule:
        print("❌ 스케줄 정보를 가져올 수 없습니다.")
        return

    print(f"\n📅 예약 가능 날짜: {schedule.available_dates or '없음'}")
    print(f"📊 총 슬롯 수: {len(schedule.slots)}")

    if not schedule.slots:
        print("⚠️ 슬롯 데이터가 없습니다.")
        return

    # 날짜별 슬롯 정보 출력
    for date in sorted(schedule.slots_by_date.keys()):
        slots = schedule.slots_by_date[date]

        # 예약이 있는 슬롯 (실제 판매된 시간)
        booked_slots = [s for s in slots if (s.unit_booking_count or 0) > 0]
        # 예약 가능한 슬롯
        available_slots = [s for s in slots if (s.stock or 0) > 0]

        print(f"\n📆 {date} (전체:{len(slots)}개)")

        # 예약된 슬롯이 있으면 표시
        if booked_slots:
            times = sorted([s.time for s in booked_slots])
            print(f"  🎫 예약된 슬롯 ({len(booked_slots)}개): {times[0]} ~ {times[-1]}")
            for slot in booked_slots:
                print(f"     📌 {slot.time} | 예약:{slot.unit_booking_count}명 | unitStock:{slot.unit_stock}")

        # 예약 가능한 슬롯 표시
        if available_slots:
            times = sorted([s.time for s in available_slots])
            print(f"  ✅ 예약 가능 ({len(available_slots)}개): {times[0]} ~ {times[-1]}")
            for slot in available_slots:
                print(f"     ✅ {slot.time} | stock:{slot.stock} | unitStock:{slot.unit_stock}")
        else:
            print(f"  ⛔ 예약 가능 슬롯 없음 (stock=0)")

        # 모든 슬롯 요약
        with_unit_stock = [s for s in slots if (s.unit_stock or 0) > 0]
        if with_unit_stock:
            times = sorted([s.time for s in with_unit_stock])
            print(f"  📊 unitStock>0 범위: {times[0]} ~ {times[-1]} ({len(with_unit_stock)}개)")

    # 첫 슬롯의 raw_data 샘플 출력
    if schedule.slots:
        print(f"\n🔍 슬롯 데이터 샘플 (첫 번째 슬롯):")
        sample = schedule.slots[0]
        print(f"   slot_id: {sample.slot_id}")
        print(f"   start_time: {sample.start_time}")
        print(f"   is_business_day: {sample.is_business_day}")
        print(f"   is_sale_day: {sample.is_sale_day}")
        print(f"   stock: {sample.stock}")
        print(f"   unit_stock: {sample.unit_stock}")
        print(f"   unit_booking_count: {sample.unit_booking_count}")
        print(f"   duration: {sample.duration}")
        print(f"   min_booking_count: {sample.min_booking_count}")
        print(f"   max_booking_count: {sample.max_booking_count}")

        # raw_data 전체 출력
        print(f"\n🔍 Raw 데이터 (첫 번째 슬롯):")
        import json
        print(json.dumps(sample.raw_data, indent=2, ensure_ascii=False))


async def check_all_items():
    """모든 상품 슬롯 정보 조회"""
    client = NaverGraphQLClient()
    try:
        # 조회 시작일 설정 (오늘부터)
        start_date = datetime.now().strftime("%Y-%m-%d")

        print(f"\n🏪 릴리영N강남 (business_id={BUSINESS_ID})")
        print(f"📆 조회 시작일: {start_date}")
        print(f"📆 조회 기간: 14일")

        # 업체 정보 조회
        business_info = await client.fetch_business_info(BUSINESS_ID)
        if business_info:
            print(f"\n📋 업체 정보:")
            print(f"   이름: {business_info.name}")
            print(f"   business_type_id: {business_info.business_type_id}")
            print(f"   service_name: {business_info.service_name}")

        # 상품 목록 조회 (raw 데이터 포함)
        items = await client.fetch_biz_items(BUSINESS_ID)
        print(f"\n📦 상품 목록 (API에서 조회):")
        for item in items:
            print(f"   - {item.name} (biz_item_id={item.biz_item_id})")
            # raw_data에 영업시간 정보가 있는지 확인
            if hasattr(item, 'raw_data') and item.raw_data:
                bookable = item.raw_data.get('bookableSettingJson')
                if bookable:
                    print(f"     bookableSettingJson: {bookable}")

        # 각 상품별 슬롯 조회
        for item_name, biz_item_id in ITEMS.items():
            try:
                await check_item_slots(client, item_name, biz_item_id, start_date)
            except Exception as e:
                print(f"\n❌ {item_name} 조회 실패: {e}")
    finally:
        await client.close()


async def check_specific_item(item_name: str = None, biz_item_id: str = None, target_date: str = None):
    """특정 상품만 조회"""
    client = NaverGraphQLClient()
    try:
        if item_name and item_name in ITEMS:
            biz_item_id = ITEMS[item_name]
        elif not biz_item_id:
            print("상품명 또는 biz_item_id를 지정해주세요.")
            print(f"가능한 상품: {list(ITEMS.keys())}")
            return

        start_date = target_date or datetime.now().strftime("%Y-%m-%d")
        await check_item_slots(client, item_name or biz_item_id, biz_item_id, start_date)
    finally:
        await client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="네이버 예약 슬롯 정보 확인")
    parser.add_argument("--item", "-i", help="상품명 (에스테덤, LBB, 리쥬란)")
    parser.add_argument("--item-id", help="biz_item_id 직접 지정")
    parser.add_argument("--date", "-d", help="조회 시작일 (YYYY-MM-DD)")
    parser.add_argument("--all", "-a", action="store_true", help="모든 상품 조회")

    args = parser.parse_args()

    if args.all or (not args.item and not args.item_id):
        asyncio.run(check_all_items())
    else:
        asyncio.run(check_specific_item(args.item, args.item_id, args.date))
