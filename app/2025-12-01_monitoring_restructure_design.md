# 모니터링 구조 개편 설계 문서

> 작성일: 2025-12-01
> 상태: Draft

## 1. 개요

### 1.1 배경

현재 시스템은 **tag-url 단위**로 모니터링을 관리합니다. 이 방식은 다음과 같은 문제점이 있습니다:

1. **데이터 중복**: 같은 업체/아이템에 대해 날짜가 다르면 별도 레코드 생성
2. **설정 불일치**: 동일 아이템의 설정(`booking_options`, `time_range` 등)이 레코드마다 중복 저장
3. **관리 복잡성**: URL이 변경되면 모든 관련 레코드 수정 필요
4. **캐싱과의 불일치**: `bizItems` 캐시는 이미 `business_id` 단위인데 데이터 모델은 URL 단위

### 1.2 목표

**business + item 단위**로 데이터를 정규화하고, 날짜/시간을 세부항목으로 분리하여:

- 데이터 중복 제거
- 설정 일관성 확보
- 캐싱 로직과 데이터 모델 정합성
- 확장성 향상 (같은 아이템에 여러 날짜 추가 용이)

---

## 2. 현재 구조 분석

### 2.1 현재 테이블 구조

```sql
-- 현재: 모든 정보가 단일 테이블에 평면적으로 저장
CREATE TABLE monitor_targets (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,                    -- 전체 URL (날짜 포함)
    base_url TEXT NOT NULL,               -- 기본 URL
    label TEXT NOT NULL,                  -- 사용자 라벨
    date TEXT NOT NULL,                   -- 예약 날짜
    times TEXT NOT NULL,                  -- 시간 목록 (JSON)
    category TEXT NOT NULL,               -- 카테고리
    service_type TEXT NOT NULL,           -- NAVER/COUPANG
    is_active BOOLEAN DEFAULT TRUE,       -- 시스템 활성 상태
    is_enabled BOOLEAN DEFAULT TRUE,      -- 사용자 활성 설정
    run_status TEXT DEFAULT 'idle',       -- 실행 상태
    last_error TEXT,                      -- 마지막 에러
    error_count INTEGER DEFAULT 0,        -- 에러 횟수
    interval REAL,                        -- 모니터링 간격
    custom_interval BOOLEAN DEFAULT FALSE,
    auto_booking_enabled BOOLEAN DEFAULT FALSE,
    max_bookings INTEGER DEFAULT 1,
    booking_count INTEGER DEFAULT 0,
    time_range TEXT,                      -- 예약 시간 범위
    last_booking_time TIMESTAMP,
    booking_options TEXT,                 -- 사업자별 옵션 (JSON)
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### 2.2 현재 구조의 문제점 예시

```
# 같은 아이템, 다른 날짜 → 별도 레코드
id=1: url=".../bizes/987654/items/555?startDate=2025-12-15", label="전통주-12/15"
id=2: url=".../bizes/987654/items/555?startDate=2025-12-16", label="전통주-12/16"
id=3: url=".../bizes/987654/items/555?startDate=2025-12-17", label="전통주-12/17"

→ booking_options, time_range 등이 3번 중복 저장
→ 아이템 설정 변경 시 3개 레코드 모두 수정 필요
```

---

## 3. 제안 구조

### 3.1 ERD (Entity Relationship Diagram)

```
┌─────────────────────────────────────────────────────────────────┐
│                         businesses                                │
│  업체 정보 (business_id 단위)                                      │
├─────────────────────────────────────────────────────────────────┤
│  id (PK)                                                         │
│  business_id (UNIQUE) ─────────────┐                             │
│  business_type_id                   │                             │
│  name                               │                             │
│  service_type (NAVER/COUPANG)       │                             │
│  category                           │                             │
│  booking_options (JSON)             │  1:N                        │
│  created_at                         │                             │
│  updated_at                         │                             │
└─────────────────────────────────────┼─────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                          biz_items                                │
│  아이템 정보 (biz_item_id 단위)                                    │
├─────────────────────────────────────────────────────────────────┤
│  id (PK)                                                         │
│  business_id (FK) ──────────────────┘                             │
│  biz_item_id (UNIQUE with business_id)  ─────┐                   │
│  name                                         │                   │
│  time_range                                   │                   │
│  auto_booking_enabled                         │  1:N              │
│  max_bookings_per_schedule                    │                   │
│  booking_options_override (JSON)              │                   │
│  created_at                                   │                   │
│  updated_at                                   │                   │
└───────────────────────────────────────────────┼───────────────────┘
                                                │
                                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      monitor_schedules                           │
│  모니터링 일정 (날짜 단위)                                         │
├─────────────────────────────────────────────────────────────────┤
│  id (PK)                                                         │
│  biz_item_id (FK) ────────────────────────────┘                  │
│  date (UNIQUE with biz_item_id)                                  │
│  times (JSON) - 선택적 시간 목록                                  │
│  is_enabled (사용자 설정)                                         │
│  is_active (시스템 상태)                                          │
│  run_status                                                      │
│  last_error                                                      │
│  error_count                                                     │
│  interval                                                        │
│  custom_interval                                                 │
│  booking_count                                                   │
│  last_booking_time                                               │
│  created_at                                                      │
│  updated_at                                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 테이블 정의

#### 3.2.1 businesses (업체)

```sql
CREATE TABLE businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 식별자
    business_id TEXT NOT NULL UNIQUE,       -- 네이버 business_id (예: "987654")
    business_type_id INTEGER,                -- 네이버 business_type_id

    -- 기본 정보
    name TEXT NOT NULL,                      -- 업체명 (예: "전통주갤러리")
    service_type TEXT NOT NULL DEFAULT 'naver',  -- 서비스 타입 (naver/coupang)
    category TEXT,                           -- 카테고리

    -- 업체 레벨 설정
    booking_options TEXT,                    -- JSON: 사업자별 예약 옵션 설정

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_businesses_business_id ON businesses(business_id);
CREATE INDEX idx_businesses_service_type ON businesses(service_type);
```

#### 3.2.2 biz_items (아이템)

```sql
CREATE TABLE biz_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 관계
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    -- 식별자
    biz_item_id TEXT NOT NULL,               -- 네이버 biz_item_id (예: "555")

    -- 기본 정보
    name TEXT NOT NULL,                      -- 아이템명 (예: "프리미엄 시음 코스")
    base_url TEXT,                           -- 기본 URL (날짜 제외)

    -- 아이템 레벨 설정
    time_range TEXT,                         -- 예약 시간 범위 (예: "10:00-21:00")
    auto_booking_enabled BOOLEAN DEFAULT FALSE,
    max_bookings_per_schedule INTEGER DEFAULT 1,  -- 일정당 최대 예약 횟수
    booking_options_override TEXT,           -- JSON: 업체 설정 오버라이드

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(business_id, biz_item_id)
);

CREATE INDEX idx_biz_items_business_id ON biz_items(business_id);
CREATE INDEX idx_biz_items_biz_item_id ON biz_items(biz_item_id);
```

#### 3.2.3 monitor_schedules (모니터링 일정)

```sql
CREATE TABLE monitor_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 관계
    biz_item_id INTEGER NOT NULL REFERENCES biz_items(id) ON DELETE CASCADE,

    -- 일정 정보
    date TEXT NOT NULL,                      -- 예약 날짜 (예: "2025-12-15")
    times TEXT,                              -- JSON: 선택적 시간 목록 (비어있으면 전체)

    -- 상태 (REQ-MON-004)
    is_enabled BOOLEAN DEFAULT TRUE,         -- 사용자 설정: 모니터링 원함
    is_active BOOLEAN DEFAULT FALSE,         -- 시스템 상태: 실제 모니터링 중
    run_status TEXT DEFAULT 'idle',          -- idle/pending/queued/running/paused/stopped/error

    -- 에러 추적
    last_error TEXT,
    error_count INTEGER DEFAULT 0,

    -- 스케줄링
    interval REAL,                           -- 모니터링 간격 (초)
    custom_interval BOOLEAN DEFAULT FALSE,   -- 사용자 정의 간격 여부

    -- 예약 추적
    booking_count INTEGER DEFAULT 0,         -- 이 일정의 예약 성공 횟수
    last_booking_time TIMESTAMP,

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(biz_item_id, date)
);

CREATE INDEX idx_monitor_schedules_biz_item_id ON monitor_schedules(biz_item_id);
CREATE INDEX idx_monitor_schedules_date ON monitor_schedules(date);
CREATE INDEX idx_monitor_schedules_is_enabled ON monitor_schedules(is_enabled);
CREATE INDEX idx_monitor_schedules_run_status ON monitor_schedules(run_status);
```

### 3.3 기존 테이블과의 호환성

마이그레이션 기간 동안 `monitor_targets` 테이블을 유지하고, 새 테이블과 동기화합니다.

```sql
-- 호환성을 위한 뷰 (기존 코드 지원)
CREATE VIEW monitor_targets_compat AS
SELECT
    ms.id,
    -- URL 동적 생성
    'https://booking.naver.com/booking/' || b.business_type_id ||
    '/bizes/' || b.business_id || '/items/' || bi.biz_item_id ||
    '?startDate=' || ms.date AS url,
    bi.base_url,
    bi.name || ' - ' || ms.date AS label,
    ms.date,
    ms.times,
    b.category,
    b.service_type,
    ms.is_active,
    ms.is_enabled,
    ms.run_status,
    ms.last_error,
    ms.error_count,
    ms.interval,
    ms.custom_interval,
    bi.auto_booking_enabled,
    bi.max_bookings_per_schedule AS max_bookings,
    ms.booking_count,
    bi.time_range,
    ms.last_booking_time,
    COALESCE(bi.booking_options_override, b.booking_options) AS booking_options,
    ms.created_at,
    ms.updated_at,
    -- 추가 필드 (새 구조용)
    b.id AS business_pk,
    b.business_id,
    b.business_type_id,
    b.name AS business_name,
    bi.id AS biz_item_pk,
    bi.biz_item_id,
    bi.name AS item_name
FROM monitor_schedules ms
JOIN biz_items bi ON ms.biz_item_id = bi.id
JOIN businesses b ON bi.business_id = b.id;
```

---

## 4. SQLAlchemy 모델

### 4.1 Business 모델

```python
# app/models/business.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base
from .monitor_target import ServiceType

class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 식별자
    business_id = Column(String, nullable=False, unique=True)
    business_type_id = Column(Integer, nullable=True)

    # 기본 정보
    name = Column(String, nullable=False)
    service_type = Column(Enum(ServiceType), nullable=False, default=ServiceType.NAVER)
    category = Column(String, nullable=True)

    # 업체 레벨 설정
    booking_options = Column(Text, nullable=True)  # JSON

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    items = relationship("BizItem", back_populates="business", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Business(id={self.id}, business_id={self.business_id}, name={self.name})>"
```

### 4.2 BizItem 모델

```python
# app/models/biz_item.py
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

class BizItem(Base):
    __tablename__ = "biz_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 관계
    business_id = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)

    # 식별자
    biz_item_id = Column(String, nullable=False)

    # 기본 정보
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=True)

    # 아이템 레벨 설정
    time_range = Column(String, nullable=True)
    auto_booking_enabled = Column(Boolean, default=False)
    max_bookings_per_schedule = Column(Integer, default=1)
    booking_options_override = Column(Text, nullable=True)  # JSON

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    business = relationship("Business", back_populates="items")
    schedules = relationship("MonitorSchedule", back_populates="biz_item", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<BizItem(id={self.id}, biz_item_id={self.biz_item_id}, name={self.name})>"
```

### 4.3 MonitorSchedule 모델

```python
# app/models/monitor_schedule.py
from sqlalchemy import Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

class MonitorSchedule(Base):
    __tablename__ = "monitor_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 관계
    biz_item_id = Column(Integer, ForeignKey("biz_items.id", ondelete="CASCADE"), nullable=False)

    # 일정 정보
    date = Column(String, nullable=False)
    times = Column(Text, nullable=True)  # JSON

    # 상태 (REQ-MON-004)
    is_enabled = Column(Boolean, default=True)
    is_active = Column(Boolean, default=False)
    run_status = Column(String, default='idle')

    # 에러 추적
    last_error = Column(String, nullable=True)
    error_count = Column(Integer, default=0)

    # 스케줄링
    interval = Column(Float, nullable=True)
    custom_interval = Column(Boolean, default=False)

    # 예약 추적
    booking_count = Column(Integer, default=0)
    last_booking_time = Column(DateTime, nullable=True)

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    biz_item = relationship("BizItem", back_populates="schedules")

    def __repr__(self):
        return f"<MonitorSchedule(id={self.id}, date={self.date}, is_enabled={self.is_enabled})>"
```

---

## 5. API 스키마 (Pydantic)

### 5.1 Business 스키마

```python
# app/schemas/business.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class BusinessBase(BaseModel):
    business_id: str
    business_type_id: Optional[int] = None
    name: str
    service_type: str = "naver"
    category: Optional[str] = None
    booking_options: Optional[dict] = None

class BusinessCreate(BusinessBase):
    pass

class BusinessUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    booking_options: Optional[dict] = None

class Business(BusinessBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class BusinessWithItems(Business):
    items: List["BizItem"] = []
```

### 5.2 BizItem 스키마

```python
# app/schemas/biz_item.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class BizItemBase(BaseModel):
    biz_item_id: str
    name: str
    base_url: Optional[str] = None
    time_range: Optional[str] = None
    auto_booking_enabled: bool = False
    max_bookings_per_schedule: int = 1
    booking_options_override: Optional[dict] = None

class BizItemCreate(BizItemBase):
    business_id: int  # FK

class BizItemUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    time_range: Optional[str] = None
    auto_booking_enabled: Optional[bool] = None
    max_bookings_per_schedule: Optional[int] = None
    booking_options_override: Optional[dict] = None

class BizItem(BizItemBase):
    id: int
    business_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class BizItemWithSchedules(BizItem):
    schedules: List["MonitorSchedule"] = []
```

### 5.3 MonitorSchedule 스키마

```python
# app/schemas/monitor_schedule.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class MonitorScheduleBase(BaseModel):
    date: str
    times: Optional[List[str]] = None
    is_enabled: bool = True
    interval: Optional[float] = None
    custom_interval: bool = False

class MonitorScheduleCreate(MonitorScheduleBase):
    biz_item_id: int  # FK

class MonitorScheduleUpdate(BaseModel):
    date: Optional[str] = None
    times: Optional[List[str]] = None
    is_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    run_status: Optional[str] = None
    last_error: Optional[str] = None
    error_count: Optional[int] = None
    interval: Optional[float] = None
    custom_interval: Optional[bool] = None

class MonitorSchedule(MonitorScheduleBase):
    id: int
    biz_item_id: int
    is_active: bool = False
    run_status: str = "idle"
    last_error: Optional[str] = None
    error_count: int = 0
    booking_count: int = 0
    last_booking_time: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# 복합 응답용
class ScheduleWithContext(MonitorSchedule):
    """일정 + 상위 컨텍스트 정보"""
    business_id: str
    business_name: str
    biz_item_id: str
    item_name: str
    time_range: Optional[str] = None
    auto_booking_enabled: bool = False
```

### 5.4 일괄 생성 스키마

```python
# app/schemas/bulk.py
from pydantic import BaseModel
from typing import List, Optional

class BulkScheduleCreate(BaseModel):
    """하나의 아이템에 여러 날짜 일정 추가"""
    biz_item_id: int
    dates: List[str]  # ["2025-12-15", "2025-12-16", "2025-12-17"]
    times: Optional[List[str]] = None
    is_enabled: bool = True

class BulkItemWithSchedules(BaseModel):
    """업체에 아이템과 일정을 한 번에 추가"""
    business_id: int
    biz_item_id: str
    item_name: str
    base_url: Optional[str] = None
    time_range: Optional[str] = None
    auto_booking_enabled: bool = False
    schedules: List[dict]  # [{"date": "2025-12-15", "times": [...]}]
```

---

## 6. API 엔드포인트 설계

### 6.1 Business API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/businesses` | 업체 목록 조회 |
| POST | `/api/v1/businesses` | 업체 추가 |
| GET | `/api/v1/businesses/{id}` | 업체 상세 (아이템 포함) |
| PUT | `/api/v1/businesses/{id}` | 업체 수정 |
| DELETE | `/api/v1/businesses/{id}` | 업체 삭제 (하위 모두 삭제) |

### 6.2 BizItem API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/businesses/{business_id}/items` | 업체의 아이템 목록 |
| POST | `/api/v1/businesses/{business_id}/items` | 아이템 추가 |
| GET | `/api/v1/items/{id}` | 아이템 상세 (일정 포함) |
| PUT | `/api/v1/items/{id}` | 아이템 수정 |
| DELETE | `/api/v1/items/{id}` | 아이템 삭제 (일정 모두 삭제) |

### 6.3 MonitorSchedule API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/items/{item_id}/schedules` | 아이템의 일정 목록 |
| POST | `/api/v1/items/{item_id}/schedules` | 일정 추가 |
| POST | `/api/v1/items/{item_id}/schedules/bulk` | 일정 일괄 추가 |
| GET | `/api/v1/schedules/{id}` | 일정 상세 |
| PUT | `/api/v1/schedules/{id}` | 일정 수정 |
| DELETE | `/api/v1/schedules/{id}` | 일정 삭제 |
| POST | `/api/v1/schedules/{id}/enable` | 일정 활성화 |
| POST | `/api/v1/schedules/{id}/disable` | 일정 비활성화 |

### 6.4 통합 조회 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/schedules` | 전체 일정 목록 (필터링/페이징) |
| GET | `/api/v1/schedules/active` | 활성 일정만 조회 |
| GET | `/api/v1/monitor/dashboard` | 대시보드용 통합 데이터 |

### 6.5 호환성 API (마이그레이션 기간)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/monitor/targets` | 기존 형식으로 조회 (뷰 사용) |
| POST | `/api/v1/monitor/targets` | 기존 형식으로 추가 (내부 변환) |

---

## 7. 워커 로직 변경

### 7.1 URL 생성 유틸리티

```python
# app/utils/url_builder.py
def build_naver_booking_url(
    business_type_id: int,
    business_id: str,
    biz_item_id: str,
    date: str
) -> str:
    """네이버 예약 URL 생성"""
    return (
        f"https://booking.naver.com/booking/{business_type_id}"
        f"/bizes/{business_id}/items/{biz_item_id}"
        f"?startDate={date}"
    )
```

### 7.2 모니터링 매니저 수정

```python
# 현재: target.url에서 파라미터 추출
url_pattern = r'booking/(\d+)/bizes/(\d+)/items/(\d+)'
match = re.search(url_pattern, target.url)

# 변경 후: 이미 분리된 데이터 사용
schedule = get_schedule_with_context(schedule_id)
business_id = schedule.business_id
biz_item_id = schedule.biz_item_id
date = schedule.date
url = build_naver_booking_url(
    schedule.business_type_id,
    business_id,
    biz_item_id,
    date
)
```

### 7.3 캐싱 로직 (변경 없음)

현재 `bizItems` 캐시가 이미 `business_id` 단위이므로 로직 변경 불필요:

```python
# 현재 코드 유지
if business_id in self._biz_items_cache:
    cached = self._biz_items_cache[business_id]
    ...
```

---

## 8. 프론트엔드 UI 변경

### 8.1 현재 UI 구조

```
모니터링 목록
├── 전통주갤러리-12/15  [ON/OFF] [삭제]
├── 전통주갤러리-12/16  [ON/OFF] [삭제]
└── 전통주갤러리-12/17  [ON/OFF] [삭제]
```

### 8.2 제안 UI 구조

```
업체 목록
└── 전통주갤러리 (business_id: 987654)  [설정] [삭제]
    └── 아이템 목록
        └── 프리미엄 시음 코스 (item_id: 555)  [설정] [삭제]
            └── 일정
                ├── 2025-12-15  [ON/OFF] [삭제]
                ├── 2025-12-16  [ON/OFF] [삭제]
                └── [+ 날짜 추가]
```

### 8.3 일괄 추가 UI

```
날짜 일괄 추가
┌────────────────────────────────────┐
│ 시작 날짜: [2025-12-15]            │
│ 종료 날짜: [2025-12-31]            │
│ 제외 요일: [토] [일]                │
│                                    │
│ [미리보기] [추가]                   │
└────────────────────────────────────┘

미리보기: 12개 날짜가 추가됩니다
- 2025-12-15 (월)
- 2025-12-16 (화)
- ...
```

---

## 9. 설정 필드 상속 규칙

### 9.1 상속 계층

```
Business.booking_options (기본값)
    ↓ 오버라이드
BizItem.booking_options_override (아이템별 설정)
    ↓ 적용
MonitorSchedule (실행 시 사용)
```

### 9.2 설정 병합 로직

```python
def get_effective_booking_options(schedule: MonitorSchedule) -> dict:
    """실제 사용할 예약 옵션 계산"""
    biz_item = schedule.biz_item
    business = biz_item.business

    # 기본값
    options = json.loads(business.booking_options or '{}')

    # 아이템 레벨 오버라이드
    if biz_item.booking_options_override:
        item_options = json.loads(biz_item.booking_options_override)
        options.update(item_options)

    return options
```

---

## 10. 참고: 쿠팡 확장 고려

현재 설계는 네이버 예약 중심이지만, 쿠팡 등 다른 서비스도 지원 가능합니다:

| 필드 | 네이버 | 쿠팡 |
|------|--------|------|
| `business_id` | 네이버 business_id | 쿠팡 seller_id |
| `biz_item_id` | 네이버 item_id | 쿠팡 product_id |
| `service_type` | "naver" | "coupang" |

URL 생성 로직만 서비스별로 분리하면 됩니다:

```python
def build_monitoring_url(schedule: ScheduleWithContext) -> str:
    if schedule.service_type == "naver":
        return build_naver_booking_url(...)
    elif schedule.service_type == "coupang":
        return build_coupang_url(...)
```
