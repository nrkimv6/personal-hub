-- 009_add_shutdown_notification.sql
-- 서버 종료 알림 설정 추가
-- 날짜: 2025-12-03

-- 기존 notify_states에 "shutdown" 추가
-- JSON 배열에 "shutdown"이 없으면 추가
UPDATE notification_settings
SET notify_states = json_insert(
    notify_states,
    '$[#]',
    'shutdown'
)
WHERE id = 1
  AND notify_states IS NOT NULL
  AND notify_states NOT LIKE '%shutdown%';
