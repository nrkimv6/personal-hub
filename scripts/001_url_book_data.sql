-- url_book.py 데이터 마이그레이션
-- 생성일: 2025-11-30
-- 원본 파일: old/url_book.py

-- =====================================================
-- monitor_targets 테이블 INSERT
-- =====================================================

-- 1. 코스알엑스_1130
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1540627/items/7208177?startDate=2025-11-30',
    'https://booking.naver.com',
    '코스알엑스_1130',
    '2025-11-30',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '10:00-21:00'
);

-- 2. 풀메이크업
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6308953?startDate=2025-12-06',
    'https://booking.naver.com',
    '풀메이크업',
    '2025-12-06',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '10:00-21:00'
);

-- 3. 에스테덤_1130
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309738?startDate=2025-11-30',
    'https://booking.naver.com',
    '에스테덤_1130',
    '2025-11-30',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '10:00-21:00'
);

-- 4. 에스테덤_1201
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309738?startDate=2025-12-01',
    'https://booking.naver.com',
    '에스테덤_1201',
    '2025-12-01',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '18:00-21:00'
);

-- 5. 에스테덤_1203
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309738?startDate=2025-12-03',
    'https://booking.naver.com',
    '에스테덤_1203',
    '2025-12-03',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '18:00-21:00'
);

-- 6. LBB_1201
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309741?startDate=2025-12-01',
    'https://booking.naver.com',
    'LBB_1201',
    '2025-12-01',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '18:00-21:00'
);

-- 7. LBB_1203
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309741?startDate=2025-12-03',
    'https://booking.naver.com',
    'LBB_1203',
    '2025-12-03',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '18:00-21:00'
);

-- 8. 홈케어레슨_1130 (전체 시간대)
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-11-30',
    'https://booking.naver.com',
    '홈케어레슨_1130',
    '2025-11-30',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, NULL
);

-- 9. 홈케어레슨_1201
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-12-01',
    'https://booking.naver.com',
    '홈케어레슨_1201',
    '2025-12-01',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '18:00-19:00'
);

-- 10. 홈케어레슨_1203
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-12-03',
    'https://booking.naver.com',
    '홈케어레슨_1203',
    '2025-12-03',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '18:00-19:00'
);

-- 11. 홈케어레슨_1205
INSERT INTO monitor_targets (
    url, base_url, label, date, times, category, service_type,
    is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
) VALUES (
    'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-12-05',
    'https://booking.naver.com',
    '홈케어레슨_1205',
    '2025-12-05',
    '[]',
    '13',
    'naver',
    1, 1, 1, 1, '18:00-19:00'
);


-- =====================================================
-- business_options 테이블 INSERT
-- (사업자별 옵션 자동 선택 설정)
-- =====================================================

-- 사업자 1269828 (뷰티 서비스)
INSERT INTO business_options (
    business_id, business_name, option_config, auto_fill_config, is_active
) VALUES (
    '1269828',
    '뷰티서비스_1269828',
    '{"options": [0], "items": {"6308953": {"options": [0, 1, 2]}, "6309738": {"options": [0]}, "6309741": {"options": [0]}, "6309731": {"options": [0]}}}',
    '{"fields": []}',
    1
);

-- 사업자 1540627 (코스알엑스)
INSERT INTO business_options (
    business_id, business_name, option_config, auto_fill_config, is_active
) VALUES (
    '1540627',
    '코스알엑스_1540627',
    '{"options": [0]}',
    '{"fields": []}',
    1
);

-- 사업자 142806 (전통주갤러리) - 주석 처리된 항목이지만 참고용으로 추가
-- INSERT INTO business_options (
--     business_id, business_name, option_config, auto_fill_config, is_active
-- ) VALUES (
--     '142806',
--     '전통주갤러리',
--     '{"options": [0]}',
--     '{"fields": [{"name": "성함", "value": "자동입력필요"}, {"name": "연락처", "value": "자동입력필요"}]}',
--     1
-- );


-- =====================================================
-- 기존 데이터베이스에 컬럼 추가 (ALTER TABLE)
-- (데이터베이스가 이미 존재하는 경우에만 실행)
-- =====================================================

-- monitor_targets 테이블에 새 컬럼 추가
-- ALTER TABLE monitor_targets ADD COLUMN auto_booking_enabled BOOLEAN DEFAULT FALSE;
-- ALTER TABLE monitor_targets ADD COLUMN max_bookings INTEGER DEFAULT 1;
-- ALTER TABLE monitor_targets ADD COLUMN booking_count INTEGER DEFAULT 0;
-- ALTER TABLE monitor_targets ADD COLUMN time_range TEXT;
-- ALTER TABLE monitor_targets ADD COLUMN last_booking_time DATETIME;
-- ALTER TABLE monitor_targets ADD COLUMN booking_options TEXT;
