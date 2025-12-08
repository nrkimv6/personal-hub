-- 016: Account에 booking_info 컬럼 추가
-- 예약 시 사용할 개인정보를 JSON으로 저장
-- 예: {"phone_last4": "4216", "visitor_name": "홍길동", "is_member": "네", "has_visited": "네"}

ALTER TABLE accounts ADD COLUMN booking_info TEXT;

-- 기존 데이터에 기본값 설정 (선택사항)
-- UPDATE accounts SET booking_info = '{"phone_last4": "4216", "is_member": "네", "has_visited": "네"}' WHERE booking_info IS NULL;
