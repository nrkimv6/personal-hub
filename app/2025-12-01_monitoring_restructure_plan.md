# 모니터링 구조 개편 구현 계획

> 작성일: 2025-12-01
> 관련 문서: `2025-12-01_monitoring_restructure_design.md`

## 개요

이 문서는 모니터링 시스템을 **tag-url 단위**에서 **business+item+schedule 단위**로 개편하기 위한 구현 계획입니다.

---

## Phase 1: 데이터베이스 스키마 추가

### 목표
- 새 테이블 생성 (기존 테이블 유지)
- 호환성 뷰 생성
- 마이그레이션 스크립트 준비

### 작업 목록

#### 1.1 새 테이블 생성 스크립트

**파일**: `app/migrations/001_add_hierarchical_tables.sql`

```sql
-- 1. businesses 테이블
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL UNIQUE,
    business_type_id INTEGER,
    name TEXT NOT NULL,
    service_type TEXT NOT NULL DEFAULT 'naver',
    category TEXT,
    booking_options TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. biz_items 테이블
CREATE TABLE IF NOT EXISTS biz_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    biz_item_id TEXT NOT NULL,
    name TEXT NOT NULL,
    base_url TEXT,
    time_range TEXT,
    auto_booking_enabled BOOLEAN DEFAULT FALSE,
    max_bookings_per_schedule INTEGER DEFAULT 1,
    booking_options_override TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(business_id, biz_item_id)
);

-- 3. monitor_schedules 테이블
CREATE TABLE IF NOT EXISTS monitor_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    biz_item_id INTEGER NOT NULL REFERENCES biz_items(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    times TEXT,
    is_enabled BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT FALSE,
    run_status TEXT DEFAULT 'idle',
    last_error TEXT,
    error_count INTEGER DEFAULT 0,
    interval REAL,
    custom_interval BOOLEAN DEFAULT FALSE,
    booking_count INTEGER DEFAULT 0,
    last_booking_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(biz_item_id, date)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_businesses_business_id ON businesses(business_id);
CREATE INDEX IF NOT EXISTS idx_biz_items_business_id ON biz_items(business_id);
CREATE INDEX IF NOT EXISTS idx_biz_items_biz_item_id ON biz_items(biz_item_id);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_biz_item_id ON monitor_schedules(biz_item_id);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_date ON monitor_schedules(date);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_is_enabled ON monitor_schedules(is_enabled);
```

#### 1.2 database.py 수정

**파일**: `app/database.py`

`init_extra_tables()` 함수에 새 테이블 생성 로직 추가

#### 1.3 데이터 마이그레이션 스크립트

**파일**: `app/migrations/002_migrate_targets_to_hierarchical.py`

```python
"""
기존 monitor_targets 데이터를 새 계층 구조로 마이그레이션
"""
import re
from sqlalchemy.orm import Session

def migrate_targets(db: Session):
    """monitor_targets → businesses + biz_items + monitor_schedules"""

    # 1. 기존 targets 조회
    targets = db.execute(text("SELECT * FROM monitor_targets")).fetchall()

    for target in targets:
        url = target['url']

        # 2. URL 파싱
        url_match = re.search(r'booking/(\d+)/bizes/(\d+)/items/(\d+)', url)
        if not url_match:
            continue

        business_type_id = int(url_match.group(1))
        business_id = url_match.group(2)
        biz_item_id = url_match.group(3)

        # 3. Business 생성/조회
        existing_business = db.execute(
            text("SELECT id FROM businesses WHERE business_id = :bid"),
            {"bid": business_id}
        ).fetchone()

        if existing_business:
            business_pk = existing_business['id']
        else:
            db.execute(text("""
                INSERT INTO businesses (business_id, business_type_id, name, service_type, category, booking_options)
                VALUES (:business_id, :business_type_id, :name, :service_type, :category, :booking_options)
            """), {
                "business_id": business_id,
                "business_type_id": business_type_id,
                "name": target['label'].split('-')[0].strip(),  # 라벨에서 추출
                "service_type": target['service_type'],
                "category": target['category'],
                "booking_options": target['booking_options']
            })
            business_pk = db.execute(text("SELECT last_insert_rowid()")).scalar()

        # 4. BizItem 생성/조회
        existing_item = db.execute(
            text("SELECT id FROM biz_items WHERE business_id = :bpk AND biz_item_id = :iid"),
            {"bpk": business_pk, "iid": biz_item_id}
        ).fetchone()

        if existing_item:
            item_pk = existing_item['id']
        else:
            db.execute(text("""
                INSERT INTO biz_items (business_id, biz_item_id, name, base_url, time_range, auto_booking_enabled, max_bookings_per_schedule)
                VALUES (:business_id, :biz_item_id, :name, :base_url, :time_range, :auto_booking_enabled, :max_bookings)
            """), {
                "business_id": business_pk,
                "biz_item_id": biz_item_id,
                "name": target['label'],
                "base_url": target['base_url'],
                "time_range": target['time_range'],
                "auto_booking_enabled": target['auto_booking_enabled'],
                "max_bookings": target['max_bookings']
            })
            item_pk = db.execute(text("SELECT last_insert_rowid()")).scalar()

        # 5. MonitorSchedule 생성
        db.execute(text("""
            INSERT OR IGNORE INTO monitor_schedules
            (biz_item_id, date, times, is_enabled, is_active, run_status, last_error, error_count, interval, custom_interval, booking_count, last_booking_time)
            VALUES (:biz_item_id, :date, :times, :is_enabled, :is_active, :run_status, :last_error, :error_count, :interval, :custom_interval, :booking_count, :last_booking_time)
        """), {
            "biz_item_id": item_pk,
            "date": target['date'],
            "times": target['times'],
            "is_enabled": target['is_enabled'],
            "is_active": target['is_active'],
            "run_status": target['run_status'],
            "last_error": target['last_error'],
            "error_count": target['error_count'],
            "interval": target['interval'],
            "custom_interval": target['custom_interval'],
            "booking_count": target['booking_count'],
            "last_booking_time": target['last_booking_time']
        })

    db.commit()
```

### 체크리스트

- [x] `migrations/001_add_hierarchical_tables.sql` 작성
- [x] `database.py`에 테이블 생성 로직 추가
- [x] `migrations/002_migrate_targets_to_hierarchical.py` 작성
- [ ] 마이그레이션 테스트 (빈 DB)
- [ ] 마이그레이션 테스트 (기존 데이터 포함)

---

## Phase 2: 모델 및 스키마 추가

### 목표
- SQLAlchemy 모델 클래스 생성
- Pydantic 스키마 생성
- 기존 모델과 공존

### 작업 목록

#### 2.1 모델 파일 생성

**파일**: `app/models/business.py`
- `Business` 모델 클래스

**파일**: `app/models/biz_item.py`
- `BizItem` 모델 클래스

**파일**: `app/models/monitor_schedule.py`
- `MonitorSchedule` 모델 클래스

**파일**: `app/models/__init__.py` 수정
- 새 모델 export

#### 2.2 스키마 파일 생성

**파일**: `app/schemas/business.py`
- `BusinessCreate`, `BusinessUpdate`, `Business`, `BusinessWithItems`

**파일**: `app/schemas/biz_item.py`
- `BizItemCreate`, `BizItemUpdate`, `BizItem`, `BizItemWithSchedules`

**파일**: `app/schemas/monitor_schedule.py`
- `MonitorScheduleCreate`, `MonitorScheduleUpdate`, `MonitorSchedule`, `ScheduleWithContext`

**파일**: `app/schemas/bulk.py`
- `BulkScheduleCreate`, `BulkItemWithSchedules`

### 체크리스트

- [x] `models/business.py` 작성
- [x] `models/biz_item.py` 작성
- [x] `models/monitor_schedule.py` 작성
- [x] `models/__init__.py` 수정
- [x] `schemas/business.py` 작성
- [x] `schemas/biz_item.py` 작성
- [x] `schemas/monitor_schedule.py` 작성
- [x] `schemas/__init__.py` 수정

---

## Phase 3: 서비스 레이어 추가

### 목표
- 새 CRUD 서비스 생성
- URL 빌더 유틸리티 생성
- 기존 서비스와 공존

### 작업 목록

#### 3.1 서비스 파일 생성

**파일**: `app/services/business_service.py`

```python
class BusinessService:
    async def get_all(self, db: Session) -> List[Business]: ...
    async def get_by_id(self, db: Session, id: int) -> Optional[Business]: ...
    async def get_by_business_id(self, db: Session, business_id: str) -> Optional[Business]: ...
    async def create(self, db: Session, data: BusinessCreate) -> Business: ...
    async def update(self, db: Session, id: int, data: BusinessUpdate) -> Business: ...
    async def delete(self, db: Session, id: int) -> bool: ...
```

**파일**: `app/services/biz_item_service.py`

```python
class BizItemService:
    async def get_by_business(self, db: Session, business_id: int) -> List[BizItem]: ...
    async def get_by_id(self, db: Session, id: int) -> Optional[BizItem]: ...
    async def create(self, db: Session, data: BizItemCreate) -> BizItem: ...
    async def update(self, db: Session, id: int, data: BizItemUpdate) -> BizItem: ...
    async def delete(self, db: Session, id: int) -> bool: ...
```

**파일**: `app/services/schedule_service.py`

```python
class ScheduleService:
    async def get_by_item(self, db: Session, biz_item_id: int) -> List[MonitorSchedule]: ...
    async def get_all_active(self, db: Session) -> List[ScheduleWithContext]: ...
    async def get_by_id(self, db: Session, id: int) -> Optional[MonitorSchedule]: ...
    async def create(self, db: Session, data: MonitorScheduleCreate) -> MonitorSchedule: ...
    async def create_bulk(self, db: Session, data: BulkScheduleCreate) -> List[MonitorSchedule]: ...
    async def update(self, db: Session, id: int, data: MonitorScheduleUpdate) -> MonitorSchedule: ...
    async def delete(self, db: Session, id: int) -> bool: ...
    async def enable(self, db: Session, id: int) -> MonitorSchedule: ...
    async def disable(self, db: Session, id: int) -> MonitorSchedule: ...
```

#### 3.2 유틸리티 파일 생성

**파일**: `app/utils/url_builder.py`

```python
def build_naver_booking_url(
    business_type_id: int,
    business_id: str,
    biz_item_id: str,
    date: str
) -> str: ...

def build_coupang_url(
    seller_id: str,
    product_id: str,
    date: str
) -> str: ...

def build_monitoring_url(schedule: ScheduleWithContext) -> str:
    """서비스 타입에 따라 적절한 URL 생성"""
    ...
```

### 체크리스트

- [x] `services/business_service.py` 작성
- [x] `services/biz_item_service.py` 작성
- [x] `services/schedule_service.py` 작성
- [x] `services/schedule_adapter.py` 작성 (워커 호환 어댑터)
- [x] `utils/url_builder.py` 작성
- [ ] 단위 테스트 작성

---

## Phase 4: 라우트 추가

### 목표
- 새 API 엔드포인트 추가
- 기존 API 유지 (호환성)
- API 버전 관리

### 작업 목록

#### 4.1 라우트 파일 생성

**파일**: `app/routes/business.py`

```python
router = APIRouter(prefix="/api/v1/businesses", tags=["businesses"])

@router.get("/")
@router.post("/")
@router.get("/{id}")
@router.put("/{id}")
@router.delete("/{id}")
@router.get("/{id}/items")
```

**파일**: `app/routes/biz_item.py`

```python
router = APIRouter(prefix="/api/v1/items", tags=["items"])

@router.get("/{id}")
@router.put("/{id}")
@router.delete("/{id}")
@router.get("/{id}/schedules")
@router.post("/{id}/schedules")
@router.post("/{id}/schedules/bulk")
```

**파일**: `app/routes/schedule.py`

```python
router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

@router.get("/")
@router.get("/active")
@router.get("/{id}")
@router.put("/{id}")
@router.delete("/{id}")
@router.post("/{id}/enable")
@router.post("/{id}/disable")
```

#### 4.2 main.py 수정

새 라우터 등록

### 체크리스트

- [x] `routes/business.py` 작성
- [x] `routes/biz_item.py` 작성
- [x] `routes/schedule.py` 작성
- [x] `main.py`에 라우터 등록
- [ ] API 통합 테스트 작성
- [ ] OpenAPI 문서 확인

---

## Phase 5: 워커 로직 수정

### 목표
- 워커가 새 테이블 구조 사용
- URL 동적 생성
- 기존 로직과 호환

### 작업 목록

#### 5.1 모니터링 시스템 매니저 수정

**파일**: `app/services/monitoring_system_manager.py`

```python
# 변경점
# 1. get_active_targets() → get_active_schedules()
# 2. target.url 사용 → build_monitoring_url(schedule) 사용
# 3. schedule.biz_item.time_range 사용
```

#### 5.2 네이버 사이트 모니터 수정

**파일**: `app/services/naver_site_monitor.py`

```python
# 변경점
# 1. URL 파싱 제거 (이미 분리된 데이터 사용)
# 2. schedule.business_id, schedule.biz_item_id 직접 사용
# 3. 캐싱 로직 (변경 없음)
```

#### 5.3 예약 서비스 수정

**파일**: `app/services/booking_service.py`

```python
# 변경점
# 1. target.booking_count → schedule.booking_count
# 2. target.max_bookings → item.max_bookings_per_schedule
# 3. booking_options 병합 로직 추가
```

#### 5.4 워커 프로세스 수정

**파일**: `app/worker/monitor_worker.py`

```python
# 변경점
# 1. target 대신 schedule 사용
# 2. 상태 업데이트 로직 수정
```

### 체크리스트

- [ ] `monitoring_system_manager.py` 수정
- [ ] `naver_site_monitor.py` 수정
- [ ] `booking_service.py` 수정
- [ ] `monitor_worker.py` 수정
- [ ] 워커 통합 테스트

---

## Phase 6: 프론트엔드 수정

### 목표
- 계층 구조 UI 구현
- 일괄 추가 기능
- 기존 기능 유지

### 작업 목록

#### 6.1 새 컴포넌트 생성

**파일**: `frontend/src/components/BusinessList.svelte`
- 업체 목록 표시
- 아이템 토글

**파일**: `frontend/src/components/BizItemCard.svelte`
- 아이템 정보 표시
- 일정 목록

**파일**: `frontend/src/components/ScheduleRow.svelte`
- 일정 행
- ON/OFF 토글

**파일**: `frontend/src/components/BulkScheduleModal.svelte`
- 날짜 범위 선택
- 일괄 추가

#### 6.2 API 클라이언트 수정

**파일**: `frontend/src/lib/api.ts`

```typescript
// 새 API 함수 추가
export async function getBusinesses(): Promise<Business[]> { ... }
export async function getBizItems(businessId: number): Promise<BizItem[]> { ... }
export async function getSchedules(itemId: number): Promise<Schedule[]> { ... }
export async function createBulkSchedules(itemId: number, data: BulkScheduleCreate): Promise<Schedule[]> { ... }
```

#### 6.3 페이지 수정

**파일**: `frontend/src/routes/+page.svelte` (또는 해당 페이지)

- 계층 구조 UI 적용
- 기존 리스트 뷰 옵션 유지 (토글)

### 체크리스트

- [ ] `BusinessList.svelte` 작성
- [ ] `BizItemCard.svelte` 작성
- [ ] `ScheduleRow.svelte` 작성
- [ ] `BulkScheduleModal.svelte` 작성
- [ ] `api.ts` 수정
- [ ] 페이지 UI 수정
- [ ] E2E 테스트

---

## Phase 7: 마이그레이션 및 정리

### 목표
- 기존 데이터 마이그레이션
- 레거시 코드 제거
- 문서 업데이트

### 작업 목록

#### 7.1 데이터 마이그레이션 실행

```bash
# 1. 백업
cp monitor.db monitor.db.backup

# 2. 마이그레이션 실행
python -m app.migrations.002_migrate_targets_to_hierarchical

# 3. 검증
python -m app.migrations.verify_migration
```

#### 7.2 레거시 코드 제거

- [ ] `monitor_targets` 테이블 DROP (또는 보관)
- [ ] 기존 `MonitorTarget` 모델 제거
- [ ] 기존 `/api/v1/monitor/targets` 라우트 제거 (또는 deprecation 표시)
- [ ] 사용하지 않는 스키마 제거

#### 7.3 문서 업데이트

- [ ] `REQUIREMENTS.md` 업데이트
- [ ] API 문서 업데이트
- [ ] README 업데이트

### 체크리스트

- [ ] 데이터 백업
- [ ] 마이그레이션 실행
- [ ] 마이그레이션 검증
- [ ] 레거시 코드 제거
- [ ] 문서 업데이트
- [ ] 최종 테스트

---

## 롤백 계획

### 데이터베이스 롤백

```bash
# 백업에서 복원
cp monitor.db.backup monitor.db
```

### 코드 롤백

```bash
# Git 커밋 되돌리기
git revert <commit-hash>
```

---

## 리스크 및 완화 방안

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| 마이그레이션 실패 | 데이터 손실 | 백업 필수, 검증 스크립트 |
| API 호환성 깨짐 | 프론트엔드 오류 | 호환성 API 유지, 점진적 전환 |
| 워커 오류 | 모니터링 중단 | 기존 로직 유지, 피처 플래그 |
| 성능 저하 | 응답 지연 | 인덱스 추가, 쿼리 최적화 |

---

## 예상 작업량

| Phase | 예상 작업 내용 |
|-------|---------------|
| Phase 1 | DB 스키마, 마이그레이션 스크립트 |
| Phase 2 | 모델 3개, 스키마 4개 |
| Phase 3 | 서비스 3개, 유틸리티 1개 |
| Phase 4 | 라우트 3개, 테스트 |
| Phase 5 | 워커 로직 수정 4개 파일 |
| Phase 6 | 프론트엔드 컴포넌트 4개, 페이지 수정 |
| Phase 7 | 마이그레이션 실행, 정리 |

---

## 의존성

```
Phase 1 (DB) → Phase 2 (모델) → Phase 3 (서비스) → Phase 4 (라우트)
                                     ↓
                              Phase 5 (워커)
                                     ↓
                              Phase 6 (프론트엔드)
                                     ↓
                              Phase 7 (정리)
```

Phase 4와 Phase 5는 병렬 진행 가능
Phase 6은 Phase 4 완료 후 진행
