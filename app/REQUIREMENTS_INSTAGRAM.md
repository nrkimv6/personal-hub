# Instagram 크롤러 기술 명세

> **관련 문서**: [REQUIREMENTS.md](./REQUIREMENTS.md) (요약) | [REQUIREMENTS_DETAILS.md](./REQUIREMENTS_DETAILS.md) (네이버 예약)

---

## 1. 데이터베이스 스키마

### 1.1 게시물 (instagram_posts)

```sql
CREATE TABLE instagram_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    account TEXT,
    content TEXT,
    images TEXT,                    -- JSON: 이미지 URL 목록
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    is_ad INTEGER DEFAULT 0,
    posted_at TEXT,
    crawl_run_id INTEGER REFERENCES instagram_crawl_run(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_instagram_posts_post_id ON instagram_posts(post_id);
CREATE INDEX idx_instagram_posts_account ON instagram_posts(account);
```

### 1.2 수집 실행 기록 (instagram_crawl_run)

```sql
CREATE TABLE instagram_crawl_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT DEFAULT 'running',     -- running/completed/failed
    post_count INTEGER DEFAULT 0,
    new_post_count INTEGER DEFAULT 0,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    error_message TEXT,
    -- 상세 로그 필드 (REQ-INSTA-011)
    stop_reason TEXT,                   -- 중단 사유
    duplicate_count INTEGER DEFAULT 0,
    scroll_performed INTEGER DEFAULT 0,
    refresh_count INTEGER DEFAULT 0,
    config_snapshot TEXT                -- 수집 시점 설정 JSON
);
```

### 1.3 스케줄 설정 (instagram_schedule_config)

```sql
CREATE TABLE instagram_schedule_config (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id),
    is_enabled INTEGER DEFAULT 1,
    schedule_times TEXT DEFAULT '["09:00", "14:00", "20:00"]',
    max_posts INTEGER DEFAULT 20,
    scroll_count INTEGER DEFAULT 50,
    duplicate_stop_count INTEGER DEFAULT 5,
    min_interval_hours INTEGER DEFAULT 2,
    max_retries INTEGER DEFAULT 3,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 1.4 태그 (instagram_post_tag)

```sql
CREATE TABLE instagram_post_tag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    color TEXT DEFAULT '#6B7280',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. 크롤러 옵션 (CrawlOptions)

```python
@dataclass
class CrawlOptions:
    max_posts: int = 20                    # 최대 수집 개수
    scroll_count: int = 50                 # 스크롤 횟수
    duplicate_stop_count: int = 5          # 연속 중복 N개 시 새로고침
    max_refresh_count: int = 3             # 최대 새로고침 횟수
    no_new_posts_refresh_threshold: int = 3
    wait_after_scroll: float = 2.0
    wait_after_more: float = 1.0
    scroll_behavior: str = "human"         # human/fast
    min_scroll_delay: float = 1.5
    max_scroll_delay: float = 3.5
    read_pause_probability: float = 0.3
```

---

## 3. 핵심 동작

### 3.1 중복 감지 새로고침 (REQ-INSTA-004)

연속 중복 N개 감지 시 **페이지 새로고침** (중단 아님):

```python
async def crawl_feed(self, options: CrawlOptions):
    consecutive_duplicates = 0
    refresh_count = 0

    for post in extracted_posts:
        if self._is_db_duplicate(post):
            consecutive_duplicates += 1

            if consecutive_duplicates >= options.duplicate_stop_count:
                if refresh_count < options.max_refresh_count:
                    refresh_count += 1
                    consecutive_duplicates = 0
                    await self._refresh_feed()
                else:
                    break  # 최대 새로고침 도달 시에만 중단
        else:
            consecutive_duplicates = 0
            results.append(post)
```

### 3.2 봇 감지 회피 (REQ-INSTA-010)

```python
async def _scroll_page_human_like(self):
    viewport_height = await self.page.evaluate("window.innerHeight")
    scroll_distance = viewport_height * random.uniform(0.8, 1.5)

    await self.page.evaluate(f"window.scrollTo({{top: {scroll_distance}, behavior: 'smooth'}})")
    await asyncio.sleep(random.uniform(1.5, 3.5))

    if random.random() < 0.3:  # 읽는 척 멈춤
        await asyncio.sleep(random.uniform(2.0, 5.0))

    if random.random() < 0.2:  # 약간 위로 스크롤
        await self.page.evaluate("window.scrollBy({top: -100, behavior: 'smooth'})")
```

---

## 4. 워커 프로세스

```
Instagram Worker (subprocess)
├── 30초마다 pending 요청 체크
├── 스케줄 기반 자동 크롤링
├── heartbeat 업데이트 (60초 이내)
└── logs/instagram_worker_*.log
```

---

## 5. stop_reason 값

| 값 | 설명 |
|----|------|
| `max_posts_reached` | 최대 수집 개수 도달 |
| `duplicate_refresh_exhausted` | 연속 중복 + 최대 새로고침 도달 |
| `scroll_exhausted` | 스크롤 횟수 소진 |
| `no_new_posts` | 새 게시물 없음 + 최대 새로고침 |
| `error` | 에러 발생 |
| `manual` | 수동 중단 |

---

## 6. API 엔드포인트

| 경로 | 메서드 | 기능 |
|------|--------|------|
| `/api/v1/instagram/posts` | GET | 게시물 목록 조회 |
| `/api/v1/instagram/posts/{id}` | GET/DELETE | 게시물 상세/삭제 |
| `/api/v1/instagram/crawl/manual` | POST | 수동 크롤링 실행 |
| `/api/v1/instagram/crawl/runs` | GET | 수집 기록 목록 |
| `/api/v1/instagram/schedule` | GET/PUT | 스케줄 설정 |
| `/api/v1/instagram/tags` | GET/POST | 태그 관리 |
| `/api/v1/instagram/worker/status` | GET | 워커 상태 |
| `/api/v1/instagram/llm/requests` | GET/POST | LLM 분류 요청 목록/생성 |
| `/api/v1/instagram/llm/requests/{id}` | GET | LLM 요청 상세 |
| `/api/v1/instagram/llm/requests/{id}/retry` | POST | LLM 요청 재시도 |
| `/api/v1/instagram/llm/worker/status` | GET | Claude 워커 상태 |
| `/api/v1/instagram/llm/stats` | GET | LLM 분류 통계 |

---

## 7. LLM 분류 시스템 (REQ-INSTA-012)

### 7.1 데이터베이스 스키마

```sql
-- LLM 분류 요청
CREATE TABLE instagram_llm_classification_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES instagram_posts(id),
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    requested_by TEXT DEFAULT 'auto',      -- auto/manual
    trigger_tag TEXT,                       -- 트리거된 태그 (event 등)
    status TEXT DEFAULT 'pending',          -- pending/processing/completed/failed
    processed_at DATETIME,
    llm_result TEXT,                        -- JSON 결과
    confidence_score REAL,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    prompt_used TEXT,
    raw_response TEXT
);

-- Claude 워커 상태
CREATE TABLE instagram_llm_worker_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT UNIQUE NOT NULL,
    pid INTEGER,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat DATETIME,
    current_state TEXT DEFAULT 'idle',
    current_request_id INTEGER,
    is_alive INTEGER DEFAULT 1,
    processed_count INTEGER DEFAULT 0
);
```

### 7.2 추출 필드

```json
{
    "is_event": true,
    "organizer": "주최사/브랜드명",
    "event_url": "이벤트 URL",
    "event_date": "YYYY-MM-DD",
    "event_time": "HH:MM",
    "details": "상세 내용 요약",
    "confidence": 0.9
}
```

### 7.3 동작 흐름

```
[키워드 분류] → "event" 태그 매칭 → [LLM 분류 큐] → [Claude Worker] → [결과 저장]
```

1. ClassifierService에서 게시물 태그 매칭
2. `LLM_TRIGGER_TAGS = ["event"]` 포함 시 분류 요청 생성
3. Claude Worker가 10초 간격으로 pending 요청 확인
4. Claude CLI subprocess 실행: `claude -p "프롬프트"`
5. JSON 응답 파싱 후 결과 저장

### 7.4 워커 프로세스

```
Claude Worker (subprocess)
├── 10초마다 pending 요청 체크
├── Claude CLI로 LLM 분류 실행
├── heartbeat 업데이트 (30초 이내)
├── Watchdog 자동 재시작
└── logs/claude_worker_*.log
```
