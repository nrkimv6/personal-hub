-- Migration 107: file_search_ignore_pattern 테이블 생성 + 기본 패턴 seed
-- 파일 검색 시 노이즈 디렉토리/파일을 제외하기 위한 무시 패턴 관리 테이블

CREATE TABLE IF NOT EXISTS file_search_ignore_pattern (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    pattern TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 기본 seed 패턴
INSERT INTO file_search_ignore_pattern (label, pattern, enabled, sort_order) VALUES
    ('Gradle 빌드', '.gradle', 1, 1),
    ('Node 모듈', 'node_modules', 1, 2),
    ('Python 캐시', '__pycache__', 1, 3),
    ('Git 저장소', '.git', 1, 4),
    ('Python 가상환경', '.venv', 1, 5),
    ('배포 산출물', 'dist', 1, 6),
    ('빌드 산출물', 'build', 1, 7),
    ('SvelteKit 빌드', '.svelte-kit', 1, 8),
    ('Next.js 빌드', '.next', 1, 9),
    ('Python 컴파일', '*.pyc', 1, 10),
    ('Python 패키지 정보', '*.egg-info', 1, 11),
    ('Java 클래스', '*.class', 1, 12),
    ('IntelliJ 설정', '.idea', 1, 13),
    ('Visual Studio 설정', '.vs', 1, 14),
    ('.NET 바이너리', 'bin', 1, 15),
    ('.NET 중간 산출물', 'obj', 1, 16);
