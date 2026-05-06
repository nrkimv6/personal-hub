"""
monitor.db에서 monitor_v2.db로 데이터 마이그레이션

사용법:
    python migrate_to_v2.py
"""
import re
import sqlite3
from datetime import datetime


def parse_url(url: str) -> dict:
    """
    네이버 예약 URL에서 파라미터 추출

    URL 형식:
        https://booking.naver.com/booking/{business_type_id}/bizes/{business_id}/items/{biz_item_id}?startDate={date}
    """
    result = {
        "business_type_id": None,
        "business_id": None,
        "biz_item_id": None,
        "date": None,
        "service_type": "naver",
    }

    # 쿠팡 체크
    if "coupang.com" in url:
        result["service_type"] = "coupang"
        # 쿠팡 URL 패턴: https://trip.coupang.com/api/products/{product_id}/vendor-items
        coupang_pattern = r'products/(\d+)/vendor-items'
        match = re.search(coupang_pattern, url)
        if match:
            result["business_id"] = match.group(1)
            result["biz_item_id"] = match.group(1)
        return result

    # 네이버 URL 패턴 매칭
    url_pattern = r'booking/(\d+)/bizes/(\d+)/items/(\d+)'
    url_match = re.search(url_pattern, url)
    if url_match:
        result["business_type_id"] = int(url_match.group(1))
        result["business_id"] = url_match.group(2)
        result["biz_item_id"] = url_match.group(3)

    # 날짜 추출
    date_pattern = r'start(?:Date|DateTime)=(\d{4}-\d{2}-\d{2})'
    date_match = re.search(date_pattern, url)
    if date_match:
        result["date"] = date_match.group(1)

    return result


def migrate():
    """마이그레이션 수행"""
    source_db = sqlite3.connect('monitor.db')
    target_db = sqlite3.connect('monitor_v2.db')

    source_cursor = source_db.cursor()
    target_cursor = target_db.cursor()

    try:
        print("=" * 60)
        print("monitor.db → monitor_v2.db 마이그레이션 시작")
        print("=" * 60)

        # 1. 기존 targets 조회
        source_cursor.execute("SELECT * FROM monitor_targets")
        targets = source_cursor.fetchall()

        source_cursor.execute("PRAGMA table_info(monitor_targets)")
        column_names = [col[1] for col in source_cursor.fetchall()]

        print(f"\n기존 targets 수: {len(targets)}")

        if not targets:
            print("마이그레이션할 데이터가 없습니다.")
            return

        stats = {
            "businesses_created": 0,
            "items_created": 0,
            "schedules_created": 0,
            "skipped": 0,
            "errors": 0,
        }

        # 캐시: business_id -> pk, (business_pk, biz_item_id) -> pk
        business_cache = {}
        item_cache = {}

        for row in targets:
            target = dict(zip(column_names, row))

            try:
                url = target.get("url", "")
                parsed = parse_url(url)

                if not parsed["business_id"]:
                    print(f"  [SKIP] URL 파싱 실패: {url[:50]}...")
                    stats["skipped"] += 1
                    continue

                # 2. Business 생성/조회
                if parsed["business_id"] in business_cache:
                    business_pk = business_cache[parsed["business_id"]]
                else:
                    target_cursor.execute(
                        "SELECT id FROM businesses WHERE business_id = ?",
                        (parsed["business_id"],)
                    )
                    existing = target_cursor.fetchone()

                    if existing:
                        business_pk = existing[0]
                    else:
                        # 라벨에서 업체명 추출 시도 (언더스코어 앞부분 사용)
                        label = target.get("label", "")
                        # 언더스코어로 분리 후 마지막 날짜 부분 제거
                        parts = label.rsplit("_", 1)
                        business_name = parts[0].strip() if parts else label
                        if not business_name:
                            business_name = f"Business_{parsed['business_id']}"

                        service_type = parsed["service_type"] or target.get("service_type") or "naver"
                        if not service_type:
                            service_type = "naver"

                        target_cursor.execute("""
                            INSERT INTO businesses (business_id, business_type_id, name, service_type, category, booking_options, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            parsed["business_id"],
                            parsed["business_type_id"],
                            business_name,
                            service_type,
                            target.get("category"),
                            target.get("booking_options"),
                            datetime.now().isoformat(),
                            datetime.now().isoformat(),
                        ))
                        target_db.commit()

                        business_pk = target_cursor.lastrowid
                        stats["businesses_created"] += 1
                        print(f"  [NEW] Business: {business_name} (ID: {business_pk})")

                    business_cache[parsed["business_id"]] = business_pk

                # 3. BizItem 생성/조회
                item_key = (business_pk, parsed["biz_item_id"])
                if item_key in item_cache:
                    item_pk = item_cache[item_key]
                else:
                    target_cursor.execute(
                        "SELECT id FROM biz_items WHERE business_id = ? AND biz_item_id = ?",
                        (business_pk, parsed["biz_item_id"])
                    )
                    existing = target_cursor.fetchone()

                    if existing:
                        item_pk = existing[0]
                    else:
                        # 아이템 이름: 라벨 또는 기본값
                        label = target.get("label", "")
                        parts = label.rsplit("_", 1)
                        item_name = parts[0].strip() if parts else label
                        if not item_name:
                            item_name = f"Item_{parsed['biz_item_id']}"

                        # base_url에서 items/{id} 포함하도록 정리
                        base_url = target.get("base_url", "")
                        if parsed["biz_item_id"] and parsed["biz_item_id"] not in base_url:
                            # URL에서 날짜 파라미터 제거한 기본 URL 구성
                            url = target.get("url", "")
                            if "?" in url:
                                base_url = url.split("?")[0]

                        target_cursor.execute("""
                            INSERT INTO biz_items (business_id, biz_item_id, name, base_url, time_range, auto_booking_enabled, max_bookings_per_schedule, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            business_pk,
                            parsed["biz_item_id"],
                            item_name,
                            base_url,
                            target.get("time_range"),
                            1 if target.get("auto_booking_enabled") else 0,
                            target.get("max_bookings", 1),
                            datetime.now().isoformat(),
                            datetime.now().isoformat(),
                        ))
                        target_db.commit()

                        item_pk = target_cursor.lastrowid
                        stats["items_created"] += 1
                        print(f"  [NEW] BizItem: {item_name[:30]} (ID: {item_pk})")

                    item_cache[item_key] = item_pk

                # 4. MonitorSchedule 생성
                schedule_date = parsed["date"] or target.get("date")

                # 날짜 형식 정리 (YYYY-MM-DDTHH:MM:SS 형식에서 날짜만 추출)
                if schedule_date and "T" in schedule_date:
                    schedule_date = schedule_date.split("T")[0]

                if not schedule_date:
                    print(f"  [SKIP] 날짜 없음: {target.get('label')}")
                    stats["skipped"] += 1
                    continue

                target_cursor.execute("""
                    INSERT INTO monitor_schedules
                    (biz_item_id, date, times, is_enabled, is_active, run_status, last_error, error_count, interval, custom_interval, booking_count, last_booking_time, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_pk,
                    schedule_date,
                    target.get("times"),
                    1 if target.get("is_enabled", True) else 0,
                    1 if target.get("is_active", False) else 0,
                    target.get("run_status", "idle"),
                    target.get("last_error"),
                    target.get("error_count", 0),
                    target.get("interval"),
                    1 if target.get("custom_interval") else 0,
                    target.get("booking_count", 0),
                    target.get("last_booking_time"),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ))
                target_db.commit()

                stats["schedules_created"] += 1
                print(f"  [NEW] Schedule: {schedule_date}")

            except Exception as e:
                print(f"  [ERROR] {str(e)}")
                stats["errors"] += 1
                target_db.rollback()

        print("\n" + "=" * 60)
        print("마이그레이션 완료")
        print("=" * 60)
        print(f"Businesses 생성: {stats['businesses_created']}")
        print(f"BizItems 생성: {stats['items_created']}")
        print(f"Schedules 생성: {stats['schedules_created']}")
        print(f"스킵: {stats['skipped']}")
        print(f"에러: {stats['errors']}")

        # 최종 확인
        target_cursor.execute("SELECT COUNT(*) FROM businesses")
        business_count = target_cursor.fetchone()[0]
        target_cursor.execute("SELECT COUNT(*) FROM biz_items")
        item_count = target_cursor.fetchone()[0]
        target_cursor.execute("SELECT COUNT(*) FROM monitor_schedules")
        schedule_count = target_cursor.fetchone()[0]

        print(f"\n최종 데이터:")
        print(f"  businesses: {business_count}")
        print(f"  biz_items: {item_count}")
        print(f"  monitor_schedules: {schedule_count}")

    except Exception as e:
        print(f"마이그레이션 실패: {str(e)}")
        target_db.rollback()
        raise
    finally:
        source_db.close()
        target_db.close()


if __name__ == "__main__":
    migrate()
