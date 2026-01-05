-- 087: Activity Tables
-- 문화/체육센터 강좌 수집 시스템

-- 센터 테이블
CREATE TABLE IF NOT EXISTS activity_centers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL,
    center_type VARCHAR(50) NOT NULL,
    operator VARCHAR(200),
    region_sido VARCHAR(20),
    region_sigungu VARCHAR(30),
    address VARCHAR(500),
    latitude REAL,
    longitude REAL,
    phone VARCHAR(50),
    website VARCHAR(500),
    crawl_url VARCHAR(500),
    crawl_method VARCHAR(20) DEFAULT 'static',
    crawl_config TEXT DEFAULT '{}',
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_crawled_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_activity_centers_name ON activity_centers(name);
CREATE INDEX IF NOT EXISTS idx_activity_centers_type ON activity_centers(center_type);
CREATE INDEX IF NOT EXISTS idx_activity_centers_region ON activity_centers(region_sido, region_sigungu);
CREATE INDEX IF NOT EXISTS idx_activity_centers_active ON activity_centers(is_active);

-- 강좌 테이블
CREATE TABLE IF NOT EXISTS activity_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_id INTEGER NOT NULL,
    source_id VARCHAR(100),
    source_url VARCHAR(500),
    name VARCHAR(300) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    subcategory VARCHAR(100),
    target_age VARCHAR(50),
    level VARCHAR(20),
    capacity INTEGER,
    fee INTEGER,
    material_fee INTEGER,
    fee_note VARCHAR(200),
    registration_start DATETIME,
    registration_end DATETIME,
    course_start DATE,
    course_end DATE,
    day_of_week VARCHAR(50),
    time_start VARCHAR(10),
    time_end VARCHAR(10),
    total_sessions INTEGER,
    instructor_name VARCHAR(100),
    instructor_bio TEXT,
    status VARCHAR(20) DEFAULT 'active',
    current_enrollment INTEGER,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source_updated_at DATETIME,
    FOREIGN KEY (center_id) REFERENCES activity_centers(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_courses_source ON activity_courses(center_id, source_id);
CREATE INDEX IF NOT EXISTS idx_activity_courses_center ON activity_courses(center_id);
CREATE INDEX IF NOT EXISTS idx_activity_courses_name ON activity_courses(name);
CREATE INDEX IF NOT EXISTS idx_activity_courses_category ON activity_courses(category);
CREATE INDEX IF NOT EXISTS idx_activity_courses_target ON activity_courses(target_age);
CREATE INDEX IF NOT EXISTS idx_activity_courses_status ON activity_courses(status);
CREATE INDEX IF NOT EXISTS idx_activity_courses_reg_start ON activity_courses(registration_start);
CREATE INDEX IF NOT EXISTS idx_activity_courses_reg_end ON activity_courses(registration_end);
CREATE INDEX IF NOT EXISTS idx_activity_courses_course_start ON activity_courses(course_start);
CREATE INDEX IF NOT EXISTS idx_activity_courses_collected ON activity_courses(collected_at);

-- 크롤링 실행 기록 테이블
CREATE TABLE IF NOT EXISTS activity_crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_id INTEGER,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status VARCHAR(20) DEFAULT 'running',
    courses_found INTEGER DEFAULT 0,
    courses_new INTEGER DEFAULT 0,
    courses_updated INTEGER DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (center_id) REFERENCES activity_centers(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_crawl_runs_center ON activity_crawl_runs(center_id);
CREATE INDEX IF NOT EXISTS idx_activity_crawl_runs_status ON activity_crawl_runs(status);
CREATE INDEX IF NOT EXISTS idx_activity_crawl_runs_started ON activity_crawl_runs(started_at);
