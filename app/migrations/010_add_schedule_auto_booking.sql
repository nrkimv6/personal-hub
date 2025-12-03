-- Migration: 010_add_schedule_auto_booking
-- Description: Move auto_booking_enabled from BizItem to MonitorSchedule level
-- Date: 2025-12-03

-- Add auto_booking_enabled column to monitor_schedules
ALTER TABLE monitor_schedules ADD COLUMN auto_booking_enabled BOOLEAN DEFAULT 0;

-- Migrate existing data: copy auto_booking_enabled from biz_items to schedules
UPDATE monitor_schedules
SET auto_booking_enabled = (
    SELECT bi.auto_booking_enabled
    FROM biz_items bi
    WHERE bi.id = monitor_schedules.biz_item_id
);

-- Note: biz_items.auto_booking_enabled column is kept for backward compatibility
-- but should no longer be used. New code should use monitor_schedules.auto_booking_enabled
