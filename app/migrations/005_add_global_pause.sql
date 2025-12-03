-- Migration: Add global_pause feature to worker_status table
-- Date: 2025-12-03
-- Description: Adds global monitoring pause/resume functionality

-- Add global_pause column (0 = running, 1 = paused)
ALTER TABLE worker_status ADD COLUMN global_pause INTEGER DEFAULT 0;

-- Add paused_at timestamp to track when pause was activated
ALTER TABLE worker_status ADD COLUMN paused_at TIMESTAMP;
