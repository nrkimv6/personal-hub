-- 크롤링 데이터 마이그레이션
-- 작성일: 2025-12-29
-- 목적: 기존 Instagram/Universal 테이블 데이터를 새 통합 테이블로 이전

-- 1. instagram_schedule_config → crawl_schedules
-- 각 service_account_id별로 스케줄 생성
INSERT INTO crawl_schedules (
    name,
    display_name,
    target_type,
    target_config,
    schedule_type,
    schedule_value,
    enabled,
    last_run_at,
    created_at,
    updated_at
)
SELECT
    'instagram_feed_account_' || COALESCE(service_account_id, 0) as name,
    'Instagram 피드 (계정 ' || COALESCE(service_account_id, 0) || ')' as display_name,
    'instagram_feed' as target_type,
    json_object(
        'account_id', service_account_id,
        'max_posts', max_posts,
        'scroll_count', scroll_count,
        'min_interval_hours', min_interval_hours,
        'duplicate_stop_count', duplicate_stop_count,
        'max_retries', max_retries,
        'retry_interval_minutes', retry_interval_minutes
    ) as target_config,
    'time_window' as schedule_type,
    json_object('times', time_windows, 'daily_runs', daily_runs) as schedule_value,
    enabled,
    NULL as last_run_at,
    CURRENT_TIMESTAMP as created_at,
    updated_at
FROM instagram_schedule_config
WHERE 1=1;

-- 2. instagram_crawl_runs → crawl_schedule_runs
-- 먼저 service_account_id 기준으로 schedule_id를 찾아서 매핑
INSERT INTO crawl_schedule_runs (
    schedule_id,
    started_at,
    finished_at,
    status,
    collected_count,
    saved_count,
    stop_reason,
    error_message,
    config_snapshot,
    worker_id,
    retry_count,
    retry_of_run_id
)
SELECT
    cs.id as schedule_id,
    icr.started_at,
    icr.finished_at,
    CASE
        WHEN icr.success = 1 THEN 'completed'
        WHEN icr.error_message IS NOT NULL THEN 'failed'
        ELSE 'running'
    END as status,
    icr.total_collected as collected_count,
    icr.new_saved as saved_count,
    icr.stop_reason,
    icr.error_message,
    icr.config_snapshot,
    NULL as worker_id,
    icr.retry_count,
    NULL as retry_of_run_id  -- 재시도 관계는 별도 업데이트 필요
FROM instagram_crawl_runs icr
LEFT JOIN crawl_schedules cs
    ON cs.name = 'instagram_feed_account_' || icr.service_account_id;

-- 3. instagram_posts.crawl_run_id → schedule_run_id 매핑
-- 기존 crawl_run_id와 새 schedule_run_id 매핑
UPDATE instagram_posts
SET schedule_run_id = (
    SELECT csr.id
    FROM crawl_schedule_runs csr
    INNER JOIN instagram_crawl_runs icr ON icr.started_at = csr.started_at
    WHERE icr.id = instagram_posts.crawl_run_id
    LIMIT 1
)
WHERE crawl_run_id IS NOT NULL;

-- 4. instagram_crawl_requests (single_post, single_post_url) → crawl_requests
INSERT INTO crawl_requests (
    url,
    url_type,
    status,
    requested_by,
    requested_at,
    processed_at,
    error_message,
    result_type,
    result_id
)
SELECT
    COALESCE(target_url, 'https://instagram.com/p/' || target_post_id) as url,
    'instagram' as url_type,
    status,
    requested_by,
    requested_at,
    processed_at,
    error_message,
    'instagram_post' as result_type,
    target_post_id as result_id
FROM instagram_crawl_requests
WHERE request_type IN ('single_post', 'single_post_url');

-- 5. universal_crawl_requests → crawl_requests
INSERT INTO crawl_requests (
    url,
    url_type,
    status,
    requested_by,
    requested_at,
    picked_at,
    processed_at,
    error_message,
    retry_count,
    result_type,
    result_id
)
SELECT
    url,
    url_type,
    status,
    requested_by,
    requested_at,
    started_at as picked_at,
    completed_at as processed_at,
    error_message,
    retry_count,
    'crawled_page' as result_type,
    crawled_page_id as result_id
FROM universal_crawl_requests;
