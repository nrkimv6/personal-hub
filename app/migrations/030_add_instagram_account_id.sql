-- Instagram 스케줄 설정에 account_id 추가
-- 크롤링에 사용할 계정(브라우저 프로필)을 지정

ALTER TABLE instagram_schedule_config ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL;

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_instagram_schedule_config_account_id ON instagram_schedule_config(account_id);
