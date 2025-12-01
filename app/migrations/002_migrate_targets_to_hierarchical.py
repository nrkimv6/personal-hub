"""
기존 monitor_targets 데이터를 새 계층 구조로 마이그레이션

사용법:
    python -m app.migrations.002_migrate_targets_to_hierarchical

설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
import re
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.database import SessionLocal


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
    }

    # URL 패턴 매칭
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
    db = SessionLocal()
    try:
        print("=" * 60)
        print("monitor_targets → 계층 구조 마이그레이션 시작")
        print("=" * 60)

        # 1. 기존 targets 조회
        targets = db.execute(text("SELECT * FROM monitor_targets")).fetchall()
        print(f"\n기존 targets 수: {len(targets)}")

        if not targets:
            print("마이그레이션할 데이터가 없습니다.")
            return

        # 컬럼 이름 가져오기
        columns = db.execute(text("PRAGMA table_info(monitor_targets)")).fetchall()
        column_names = [col[1] for col in columns]
        print(f"컬럼: {column_names}")

        stats = {
            "businesses_created": 0,
            "items_created": 0,
            "schedules_created": 0,
            "skipped": 0,
            "errors": 0,
        }

        for row in targets:
            # row를 dict로 변환
            target = dict(zip(column_names, row))

            try:
                url = target.get("url", "")
                parsed = parse_url(url)

                if not parsed["business_id"] or not parsed["biz_item_id"]:
                    print(f"  [SKIP] URL 파싱 실패: {url[:50]}...")
                    stats["skipped"] += 1
                    continue

                # 2. Business 생성/조회
                existing_business = db.execute(
                    text("SELECT id FROM businesses WHERE business_id = :bid"),
                    {"bid": parsed["business_id"]}
                ).fetchone()

                if existing_business:
                    business_pk = existing_business[0]
                else:
                    # 라벨에서 업체명 추출 시도
                    label = target.get("label", "")
                    business_name = label.split("-")[0].strip() if "-" in label else label
                    if not business_name:
                        business_name = f"Business_{parsed['business_id']}"

                    db.execute(text("""
                        INSERT INTO businesses (business_id, business_type_id, name, service_type, category, booking_options)
                        VALUES (:business_id, :business_type_id, :name, :service_type, :category, :booking_options)
                    """), {
                        "business_id": parsed["business_id"],
                        "business_type_id": parsed["business_type_id"],
                        "name": business_name,
                        "service_type": target.get("service_type", "naver"),
                        "category": target.get("category"),
                        "booking_options": target.get("booking_options")
                    })
                    db.commit()

                    business_pk = db.execute(text("SELECT last_insert_rowid()")).scalar()
                    stats["businesses_created"] += 1
                    print(f"  [NEW] Business: {business_name} (ID: {business_pk})")

                # 3. BizItem 생성/조회
                existing_item = db.execute(
                    text("SELECT id FROM biz_items WHERE business_id = :bpk AND biz_item_id = :iid"),
                    {"bpk": business_pk, "iid": parsed["biz_item_id"]}
                ).fetchone()

                if existing_item:
                    item_pk = existing_item[0]
                else:
                    item_name = target.get("label", f"Item_{parsed['biz_item_id']}")

                    db.execute(text("""
                        INSERT INTO biz_items (business_id, biz_item_id, name, base_url, time_range, auto_booking_enabled, max_bookings_per_schedule)
                        VALUES (:business_id, :biz_item_id, :name, :base_url, :time_range, :auto_booking_enabled, :max_bookings)
                    """), {
                        "business_id": business_pk,
                        "biz_item_id": parsed["biz_item_id"],
                        "name": item_name,
                        "base_url": target.get("base_url"),
                        "time_range": target.get("time_range"),
                        "auto_booking_enabled": 1 if target.get("auto_booking_enabled") else 0,
                        "max_bookings": target.get("max_bookings", 1)
                    })
                    db.commit()

                    item_pk = db.execute(text("SELECT last_insert_rowid()")).scalar()
                    stats["items_created"] += 1
                    print(f"  [NEW] BizItem: {item_name[:30]} (ID: {item_pk})")

                # 4. MonitorSchedule 생성
                schedule_date = parsed["date"] or target.get("date")
                if not schedule_date:
                    print(f"  [SKIP] 날짜 없음: {target.get('label')}")
                    stats["skipped"] += 1
                    continue

                # 중복 체크
                existing_schedule = db.execute(
                    text("SELECT id FROM monitor_schedules WHERE biz_item_id = :iid AND date = :date"),
                    {"iid": item_pk, "date": schedule_date}
                ).fetchone()

                if existing_schedule:
                    print(f"  [SKIP] 일정 이미 존재: {schedule_date}")
                    stats["skipped"] += 1
                    continue

                db.execute(text("""
                    INSERT INTO monitor_schedules
                    (biz_item_id, date, times, is_enabled, is_active, run_status, last_error, error_count, interval, custom_interval, booking_count, last_booking_time)
                    VALUES (:biz_item_id, :date, :times, :is_enabled, :is_active, :run_status, :last_error, :error_count, :interval, :custom_interval, :booking_count, :last_booking_time)
                """), {
                    "biz_item_id": item_pk,
                    "date": schedule_date,
                    "times": target.get("times"),
                    "is_enabled": 1 if target.get("is_enabled", True) else 0,
                    "is_active": 1 if target.get("is_active", False) else 0,
                    "run_status": target.get("run_status", "idle"),
                    "last_error": target.get("last_error"),
                    "error_count": target.get("error_count", 0),
                    "interval": target.get("interval"),
                    "custom_interval": 1 if target.get("custom_interval") else 0,
                    "booking_count": target.get("booking_count", 0),
                    "last_booking_time": target.get("last_booking_time")
                })
                db.commit()

                stats["schedules_created"] += 1
                print(f"  [NEW] Schedule: {schedule_date}")

            except Exception as e:
                print(f"  [ERROR] {str(e)}")
                stats["errors"] += 1
                db.rollback()

        print("\n" + "=" * 60)
        print("마이그레이션 완료")
        print("=" * 60)
        print(f"Businesses 생성: {stats['businesses_created']}")
        print(f"BizItems 생성: {stats['items_created']}")
        print(f"Schedules 생성: {stats['schedules_created']}")
        print(f"스킵: {stats['skipped']}")
        print(f"에러: {stats['errors']}")

        # 최종 확인
        business_count = db.execute(text("SELECT COUNT(*) FROM businesses")).scalar()
        item_count = db.execute(text("SELECT COUNT(*) FROM biz_items")).scalar()
        schedule_count = db.execute(text("SELECT COUNT(*) FROM monitor_schedules")).scalar()

        print(f"\n최종 데이터:")
        print(f"  businesses: {business_count}")
        print(f"  biz_items: {item_count}")
        print(f"  monitor_schedules: {schedule_count}")

    except Exception as e:
        print(f"마이그레이션 실패: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
