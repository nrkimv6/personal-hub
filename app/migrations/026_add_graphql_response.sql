-- Migration: Add graphql_response column to monitoring_events
-- Date: 2025-12-16
-- Description: GraphQL API 원본 응답 저장을 위한 컬럼 추가

-- SQLite에서는 IF NOT EXISTS가 지원되지 않으므로 조건부 실행은 제외
-- 컬럼이 이미 존재하면 에러가 발생하므로 스크립트에서 처리 필요

ALTER TABLE monitoring_events ADD COLUMN graphql_response TEXT;

-- 참고: graphql_response는 JSON 문자열로 저장됩니다.
-- 구조: {"schedule": {"bizItemSchedule": {"hourly": [...]}}}
