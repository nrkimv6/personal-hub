-- 047: 기존 LLM 분석 데이터를 Event/Popup/Uncategorized로 마이그레이션
-- 날짜: 2024-12-24
-- 주의: 046_event_popup_separation.sql 실행 후 적용
-- 참고: 이 스크립트는 한 번만 실행해야 함

-- 1. 이벤트 → Event 테이블 (llm_tag = '이벤트')
INSERT INTO events (
    title,
    thumbnail_url,
    event_type,
    event_start,
    event_end,
    announcement_date,
    organizer,
    summary,
    prizes,
    winner_count,
    purchase_required,
    event_url,
    additional_urls,
    source_type,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    created_at
)
SELECT
    COALESCE(
        CASE
            WHEN llm_organizer IS NOT NULL AND llm_summary IS NOT NULL
            THEN llm_organizer || ' ' || SUBSTR(llm_summary, 1, 50)
            ELSE COALESCE(llm_summary, SUBSTR(caption, 1, 100))
        END,
        '제목 없음'
    ),
    CASE
        WHEN images IS NOT NULL AND json_array_length(images) > 0
        THEN json_extract(images, '$[0].src')
        ELSE NULL
    END,
    'event',
    llm_event_start,
    llm_event_end,
    llm_announcement_date,
    llm_organizer,
    llm_summary,
    llm_prizes,
    llm_winner_count,
    llm_purchase_required,
    CASE
        WHEN llm_urls IS NOT NULL AND json_array_length(llm_urls) > 0
        THEN json_extract(llm_urls, '$[0]')
        ELSE NULL
    END,
    llm_urls,
    'instagram',
    id,
    url,
    account,
    collected_at
FROM instagram_posts
WHERE llm_status = 'completed' AND llm_tag = '이벤트';

-- 2. 팝업 → Popup 테이블 (llm_tag = '팝업')
INSERT INTO popups (
    title,
    thumbnail_url,
    start_date,
    end_date,
    venue_name,
    address,
    organizer,
    summary,
    official_url,
    additional_urls,
    source_type,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    created_at
)
SELECT
    COALESCE(
        CASE
            WHEN llm_organizer IS NOT NULL
            THEN llm_organizer || ' 팝업'
            ELSE COALESCE(llm_summary, SUBSTR(caption, 1, 100))
        END,
        '제목 없음'
    ),
    CASE
        WHEN images IS NOT NULL AND json_array_length(images) > 0
        THEN json_extract(images, '$[0].src')
        ELSE NULL
    END,
    llm_event_start,
    llm_event_end,
    json_extract(llm_location, '$.venue_name'),
    json_extract(llm_location, '$.address'),
    llm_organizer,
    llm_summary,
    CASE
        WHEN llm_urls IS NOT NULL AND json_array_length(llm_urls) > 0
        THEN json_extract(llm_urls, '$[0]')
        ELSE NULL
    END,
    llm_urls,
    'instagram',
    id,
    url,
    account,
    collected_at
FROM instagram_posts
WHERE llm_status = 'completed' AND llm_tag = '팝업';

-- 3. 홍보대사/기타 → Uncategorized 테이블
INSERT INTO uncategorized_posts (
    original_tag,
    title,
    thumbnail_url,
    summary,
    organizer,
    start_date,
    end_date,
    urls,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    created_at
)
SELECT
    llm_tag,
    COALESCE(llm_summary, SUBSTR(caption, 1, 100), '제목 없음'),
    CASE
        WHEN images IS NOT NULL AND json_array_length(images) > 0
        THEN json_extract(images, '$[0].src')
        ELSE NULL
    END,
    llm_summary,
    llm_organizer,
    llm_event_start,
    llm_event_end,
    llm_urls,
    id,
    url,
    account,
    collected_at
FROM instagram_posts
WHERE llm_status = 'completed' AND llm_tag IN ('홍보대사', '기타');

-- 4. InstagramPost.classified_type/id 업데이트 (이벤트)
UPDATE instagram_posts
SET
    classified_type = 'event',
    classified_id = (
        SELECT e.id FROM events e
        WHERE e.source_instagram_post_id = instagram_posts.id
        LIMIT 1
    )
WHERE llm_status = 'completed' AND llm_tag = '이벤트';

-- 5. InstagramPost.classified_type/id 업데이트 (팝업)
UPDATE instagram_posts
SET
    classified_type = 'popup',
    classified_id = (
        SELECT p.id FROM popups p
        WHERE p.source_instagram_post_id = instagram_posts.id
        LIMIT 1
    )
WHERE llm_status = 'completed' AND llm_tag = '팝업';

-- 6. InstagramPost.classified_type/id 업데이트 (미분류)
UPDATE instagram_posts
SET
    classified_type = 'uncategorized',
    classified_id = (
        SELECT u.id FROM uncategorized_posts u
        WHERE u.source_instagram_post_id = instagram_posts.id
        LIMIT 1
    )
WHERE llm_status = 'completed' AND llm_tag IN ('홍보대사', '기타');

-- 7. 기존 Event 테이블의 event_type='popup' 데이터를 Popup으로 이동
-- (수동 입력된 팝업이 있는 경우)
INSERT INTO popups (
    title,
    thumbnail_url,
    start_date,
    end_date,
    venue_name,
    address,
    organizer,
    summary,
    official_url,
    additional_urls,
    source_type,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    is_bookmarked,
    user_note,
    status,
    created_at,
    updated_at
)
SELECT
    title,
    thumbnail_url,
    event_start,
    event_end,
    location_venue,
    location_address,
    organizer,
    summary,
    event_url,
    additional_urls,
    source_type,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    is_bookmarked,
    user_note,
    status,
    created_at,
    updated_at
FROM events
WHERE event_type = 'popup';

-- 8. 기존 Event 테이블의 event_type='ambassador'/'other' 데이터를 Uncategorized로 이동
INSERT INTO uncategorized_posts (
    original_tag,
    title,
    thumbnail_url,
    summary,
    organizer,
    start_date,
    end_date,
    urls,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    created_at
)
SELECT
    event_type,
    title,
    thumbnail_url,
    summary,
    organizer,
    event_start,
    event_end,
    additional_urls,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    created_at
FROM events
WHERE event_type IN ('ambassador', 'other');

-- 9. Event 테이블에서 popup/ambassador/other 삭제
DELETE FROM events WHERE event_type IN ('popup', 'ambassador', 'other');

-- 마이그레이션 완료 확인용 쿼리 (주석 처리)
-- SELECT 'events' as table_name, COUNT(*) as count FROM events
-- UNION ALL
-- SELECT 'popups', COUNT(*) FROM popups
-- UNION ALL
-- SELECT 'uncategorized_posts', COUNT(*) FROM uncategorized_posts
-- UNION ALL
-- SELECT 'instagram_posts_classified', COUNT(*) FROM instagram_posts WHERE classified_type IS NOT NULL;
