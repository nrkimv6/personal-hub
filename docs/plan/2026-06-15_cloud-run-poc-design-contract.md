# Cloud Run PoC 설계 계약서

> 출처: `2026-06-08_public_gcp_free_tier_roadmap_todo-2.md`
> 작성일: 2026-06-15
> 상태: 확정 (todo-2 구현완료 2026-06-15, todo-17 구현중)

## 범위 계약

### Full App Migration 금지

Cloud Run PoC는 전체 앱 이전이 아니라 **read-only / health endpoint만 선택적으로 노출**하는 데모 목적이다.

| 허용 | 금지 |
|------|------|
| `GET /` (unconditional health) | PostgreSQL/Redis 의존 route 전체 |
| `GET /healthz` (신규 slim endpoint) | `app/lifespan.py` 전체 초기화 |
| 무상태 read-only route (신규 작성) | full app 마이그레이션(DB, Worker, Redis) |
| `TESTING=1` slim entrypoint | `app/main_admin.py` 그대로 Cloud Run 배포 |

### 발견된 차단 사항

1. **`router_registry.py` 누락**: `app/main_admin.py` line 88 `from app.router_registry import register_routers` — 이 파일이 personal-hub에 없음(monitor-page에만 존재). 현재 `app/main_admin.py`는 import 오류로 기동 불가.
2. **lifespan 의존**: `app/lifespan.py`는 startup 시 PostgreSQL(`ensure_bootstrap_schema_ready`, `init_extra_tables`, `check_schema_drift`, `sync_serial_sequences`)과 Redis(zombie connection cleanup)에 연결. DB/Redis 없이는 `api_ready = False`.

---

## 무의존 Route 후보 표

| Route | Method | 파일 | DB 의존 | Redis 의존 | Cloud Run PoC |
|-------|---------|------|---------|------------|---------------|
| `/` | GET | `app/main_admin.py` line 96 | ❌ 없음 | ❌ 없음 | ✅ 1순위 |
| `/api/v1/ready` | GET | `app/main_admin.py` line 101 | ⚠️ `api_ready` (lifespan 후 True) | ❌ 없음 | ⚠️ TESTING=1 시 False |
| `/health/status` | GET | `app/routes/health.py` line 50 | ⚠️ health_monitor 초기화 후 | ❌ 없음 | ⚠️ 조건부 |
| `/health/alerts` | GET | `app/routes/health.py` line 124 | ⚠️ health_monitor 초기화 후 | ❌ 없음 | ⚠️ 조건부 |

**결론**: 현재 코드베이스에서 진정한 무의존 route는 `GET /` 1개뿐.

---

## PoC 대상 Route 집합 (Phase 1 분석 결과 고정)

### Option A: Slim Entrypoint (권장)

신규 `app/main_cloudrun.py` 작성 — lifespan 없음, `router_registry` 없음:

```python
# app/main_cloudrun.py (신규 — 별도 todo에서 구현)
from fastapi import FastAPI

app = FastAPI(title="personal-hub Cloud Run PoC")

@app.get("/")
async def root():
    return {"status": "ok", "version": "poc"}

@app.get("/healthz")
async def healthz():
    return {"healthy": True}
```

- **Cloud Run route 집합**: `GET /`, `GET /healthz`
- **의존 없음**: PostgreSQL, Redis, browser, lifespan 완전 제거

### Option B: TESTING=1 우회 (차선)

기존 `app/main_admin.py`에 `TESTING=1` 환경변수 + `router_registry.py` 복사:
- `api_ready = False` 유지 (DB 미연결) → `/api/v1/ready` 응답은 `{"ready": false}`
- `GET /` 만 정상 200
- **단점**: `router_registry.py` 미포함 import 오류 별도 수정 필요, lifespan 불필요 dependency 잔존

---

## Cloud Run 결정 항목

| 항목 | 결정값 | 근거 |
|------|--------|------|
| cold start timeout | 60초 | 기본값, slim entrypoint는 < 1초 예상 |
| max concurrency | 80 | Cloud Run default, PoC 충분 |
| min instances | 0 | free-tier (0이면 idle 과금 없음) |
| unauthenticated access | ✅ 허용 | `GET /`, `GET /healthz`는 public health endpoint |
| DB 연결 | ❌ PoC에서 제외 | Option A는 DB 없음; 실 운영은 Cloud SQL 필요 |
| Redis 연결 | ❌ PoC에서 제외 | Option A는 Redis 없음 |

---

## 환경변수 분류

### Cloud Run PoC 필요 (Option A)

| 변수 | 기본값 사용 가능 | 비고 |
|------|--------------|------|
| `APP_MODE` | `"public"` | slim entrypoint에서 명시 불필요 |
| `PORT` | Cloud Run 주입 | `$PORT` 환경변수 사용 |

### Cloud Run 실 운영 시 추가 필요

| 변수 | 비고 |
|------|------|
| `DATABASE_URL` | Cloud SQL Proxy 또는 Supabase |
| `REDIS_ENABLED` | `"False"` (PoC) 또는 Cloud Memorystore |
| `JWT_SECRET` | Secret Manager에서 주입 |
| `GOOGLE_CLIENT_ID/SECRET` | OAuth 사용 시 |
| `API_BASE_URL`, `FRONTEND_URL` | Cloud Run URL |

### Local-Only (Cloud Run 절대 불필요)

| 변수 | 이유 |
|------|------|
| `CHROME_PATH`, `DRIVER_PATH` | 로컬 브라우저 자동화 |
| `BROWSER_HEADLESS`, `USER_DATA_DIR` | 로컬 전용 |
| `MEGABEAUTY_KAKAO_ALERT_CLI_PATH` | 로컬 CLI 도구 |
| `GIT_REPOS_ALLOWED_PATHS` | 로컬 git 경로 |
| `TELEGRAM_BOT_TOKEN`, `EMAIL_*` | PoC 불필요 |

---

## 검증 기준 (RIGHT-BICEP 매핑)

| 기준 | 내용 |
|------|------|
| **R**ight | `GET /`가 PostgreSQL/Redis 없이 200 반환 |
| **B**oundary | cold start < 60초, concurrency 80, min-instances 0 명시 |
| **I**nverse | DB/Redis 필요 route(`/api/v1/schedule`, `/proxy` 등) PoC 범위 제외 확인 |
| **C**ross-check | 무의존 후보 표 ∩ lifespan 의존 route = ∅ 검증 |
| **E**rror | DB 미연결 상태에서 DB 필요 route 호출 시 503 또는 import error(미노출) |
| **P**erformance | 월 200만 요청 free-tier 내 (PoC는 traffic 미미) |
