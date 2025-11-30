-- url_book.py 데이터를 monitor_targets 테이블에 INSERT

  -- 코스알엑스_1130
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1540627/items/7208177?startDateTime=2025-11-30T00%3A00%3A00
  %2B09%3A00&tab=book',
      'https://booking.naver.com/booking/13/bizes/1540627/items/7208177',
      '코스알엑스_1130',
      '2025-11-30',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '10:00-21:00'
  );

  -- 풀메이크업
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6308953?startDate=2025-12-06',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6308953',
      '풀메이크업',
      '2025-12-06',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '10:00-21:00'
  );

  -- 에스테덤_1130
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309738?startDateTime=2025-11-30T16%3A00%3A00
  %2B09%3A00',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309738',
      '에스테덤_1130',
      '2025-11-30',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '10:00-21:00'
  );

  -- 에스테덤_1201
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309738?startDateTime=2025-12-01T16%3A00%3A00
  %2B09%3A00',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309738',
      '에스테덤_1201',
      '2025-12-01',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '18:00-21:00'
  );

  -- 에스테덤_1203
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309738?startDateTime=2025-12-03T16%3A00%3A00
  %2B09%3A00',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309738',
      '에스테덤_1203',
      '2025-12-03',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '18:00-21:00'
  );

  -- LBB_1201
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309741?startDateTime=2025-12-01T16%3A00%3A00
  %2B09%3A00',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309741',
      'LBB_1201',
      '2025-12-01',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '18:00-21:00'
  );

  -- LBB_1203
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309741?startDateTime=2025-12-03T16%3A00%3A00
  %2B09%3A00',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309741',
      'LBB_1203',
      '2025-12-03',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '18:00-21:00'
  );

  -- 홈케어레슨_1130
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-11-30',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731',
      '홈케어레슨_1130',
      '2025-11-30',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      NULL
  );

  -- 홈케어레슨_1201
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-12-01',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731',
      '홈케어레슨_1201',
      '2025-12-01',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '18:00-19:00'
  );

  -- 홈케어레슨_1203
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-12-03',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731',
      '홈케어레슨_1203',
      '2025-12-03',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '18:00-19:00'
  );

  -- 홈케어레슨_1205
  INSERT INTO monitor_targets (
      url, base_url, label, date, times, category, service_type,
      is_active, is_enabled, auto_booking_enabled, max_bookings, time_range
  ) VALUES (
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731?startDate=2025-12-05',
      'https://booking.naver.com/booking/13/bizes/1269828/items/6309731',
      '홈케어레슨_1205',
      '2025-12-05',
      '[]',
      '13',
      'naver',
      1, 1, 1, 1,
      '18:00-19:00'
  );

  -- 사업자별 옵션 설정 (business_options 테이블)
  INSERT INTO business_options (business_id, business_name, option_config, auto_fill_config) VALUES
  (
      '1269828',
      '올리브영N성수',
      '{"options": [0], "items": {"6308953": {"options": [0, 1]}}}',
      '{"fields": [{"selector": "input[placeholder=\"내용을 입력해주세요.\"]", "values": ["자동추출", "4216",
   "네", "네"]}]}'
  ),
  (
      '142806',
      '전통주갤러리',
      '{}',
      '{"dropdowns": [1, 1], "name_field": "textarea#extra2"}'
  );