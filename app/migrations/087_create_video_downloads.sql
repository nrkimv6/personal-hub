-- 비디오 다운로드 테이블 생성
-- YouTube/Vimeo 등 비디오 다운로드 요청 관리

CREATE TABLE IF NOT EXISTS video_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 요청 정보
    url TEXT NOT NULL,
    download_type VARCHAR(20) NOT NULL,  -- youtube, youtube_stream, vimeo

    -- 상태
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, picked, processing, completed, failed, cancelled

    -- 옵션
    quality VARCHAR(20) DEFAULT 'best',
    embedding_url TEXT,              -- Vimeo 도메인 제한 우회용
    output_filename VARCHAR(255),    -- 사용자 지정 파일명

    -- 진행 상태
    progress INTEGER DEFAULT 0,      -- 0-100
    output_path TEXT,                -- 완료된 파일 경로
    file_size INTEGER,               -- 파일 크기 (bytes)
    title VARCHAR(500),              -- 비디오 제목

    -- 처리 정보
    picked_at DATETIME,
    processed_at DATETIME,
    worker_id VARCHAR(100),

    -- 에러
    error_message TEXT,

    -- 메타
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS ix_video_downloads_status ON video_downloads(status);
CREATE INDEX IF NOT EXISTS ix_video_downloads_download_type ON video_downloads(download_type);
CREATE INDEX IF NOT EXISTS ix_video_downloads_created_at ON video_downloads(created_at);
CREATE INDEX IF NOT EXISTS ix_video_downloads_status_created ON video_downloads(status, created_at);
