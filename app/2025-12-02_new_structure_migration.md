# 새 계층 구조 전환 계획

> 작성일: 2025-12-02
> 목표: 기존 monitor_targets 제거, 새 계층 구조(businesses → biz_items → monitor_schedules)만 사용

## 1. 개요

### 1.1 목표
- 기존 `monitor_targets` 테이블 및 관련 코드 완전 제거
- 새 계층 구조만 사용하도록 전환
- 사용자가 모니터링 대상을 **직접 등록하지 않음** (URL 입력 방식 제거)
- Business + Item 단위로 조회/등록, 날짜/시간 일정 관리

### 1.2 UI 메뉴 구성 제안

```
┌─────────────────────────────────────────────────────────────────┐
│  모니터링 시스템                                                  │
├─────────────────────────────────────────────────────────────────┤
│  [업체 관리]  [일정 현황]  [예약 설정]  [시스템]                   │
└─────────────────────────────────────────────────────────────────┘

1. 업체 관리 (/businesses)
   - 업체 목록 (트리 구조)
   - 업체 추가/수정/삭제
   - 아이템 추가/수정/삭제
   - 아이템별 일정 관리

2. 일정 현황 (/schedules) - 메인 대시보드
   - 전체 일정 캘린더/리스트 뷰
   - 날짜별 필터링
   - 활성/비활성 토글
   - 실행 상태 확인

3. 예약 설정 (/booking)
   - 자동 예약 ON/OFF
   - 시간 범위 설정
   - 사업자별 옵션

4. 시스템 (/system)
   - 워커 상태
   - 로그 뷰어
   - 설정
```

### 1.3 데이터 흐름

```
[업체 관리 페이지]
     │
     ├── 업체 추가 (business_id, name 입력)
     │      └── 아이템 추가 (biz_item_id, name 입력)
     │             └── 일정 추가 (날짜 선택, 시간 범위)
     │
     └── 기존 업체에서 아이템/일정 관리

[일정 현황 페이지]
     │
     ├── 전체 일정 조회 (is_enabled 필터)
     ├── 일정 활성화/비활성화
     └── 일정 상세 보기/수정
```

---

## 2. 체크리스트

### Phase 1: 데이터베이스 정리
- [ ] `monitor_targets` 테이블 DROP SQL 작성
- [ ] `database.py`에서 monitor_targets 관련 코드 제거
- [ ] 새 테이블만 생성하도록 `init_db()` 수정

### Phase 2: 기존 모델/스키마 제거
- [ ] `app/models/monitor_target.py` 제거 (ServiceType enum은 유지)
- [ ] `app/models/__init__.py` 수정
- [ ] `app/schemas/monitor.py` 제거 또는 정리
- [ ] `app/schemas/__init__.py` 수정

### Phase 3: 기존 라우트 제거
- [ ] `app/routes/monitor.py` 제거
- [ ] `app/routes/bulk.py` 제거
- [ ] `app/main.py`에서 기존 라우터 제거

### Phase 4: 기존 서비스 제거/수정
- [ ] `app/services/monitoring_system_manager.py` 수정 (새 구조 사용)
- [ ] `app/services/schedule_adapter.py` 제거 (더 이상 필요 없음)
- [ ] 기타 monitor_targets 참조 코드 제거

### Phase 5: 워커 로직 수정
- [ ] `app/worker/monitor_worker.py` - 새 구조 직접 사용하도록 수정
- [ ] `_load_active_targets()` → `_load_active_schedules()` 변경
- [ ] `_check_for_new_targets()` → `_check_for_new_schedules()` 변경
- [ ] `_check_for_disabled_targets()` → `_check_for_disabled_schedules()` 변경

### Phase 6: API 라우트 정리/보강
- [ ] `app/routes/business.py` - 업체+아이템 통합 관리 API
- [ ] `app/routes/schedule.py` - 일정 관리 API 보강
- [ ] `app/routes/biz_item.py` - 아이템 API 정리

### Phase 7: 프론트엔드 페이지 구조
- [ ] `/businesses` - 업체 관리 페이지 (트리 구조)
- [ ] `/schedules` - 일정 현황 페이지 (메인 대시보드)
- [ ] `/booking` - 예약 설정 페이지
- [ ] `/system` - 시스템 관리 페이지
- [ ] 기존 `/targets` 페이지 제거

### Phase 8: 테스트 및 검증
- [ ] API 테스트 (Swagger UI)
- [ ] 워커 동작 테스트
- [ ] 프론트엔드 연동 테스트

---

## 3. 상세 작업 내용

### 3.1 삭제 대상 파일

```
app/models/monitor_target.py      → 제거 (ServiceType만 별도 파일로)
app/schemas/monitor.py            → 제거
app/routes/monitor.py             → 제거
app/routes/bulk.py                → 제거
app/services/schedule_adapter.py  → 제거
```

### 3.2 수정 대상 파일

```
app/database.py                   → 새 테이블만 생성
app/models/__init__.py            → 새 모델만 export
app/schemas/__init__.py           → 새 스키마만 export
app/main.py                       → 새 라우터만 등록
app/worker/monitor_worker.py      → 새 구조 사용
app/services/monitoring_system_manager.py → 새 구조 사용
app/services/browser_service.py   → 필요시 수정
app/services/naver_site_monitor.py → 필요시 수정
app/services/booking_service.py   → 필요시 수정
```

### 3.3 새 API 구조

#### Business API (`/api/v1/businesses`)
| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 업체 목록 (아이템 포함) |
| POST | `/` | 업체 추가 |
| GET | `/{id}` | 업체 상세 (아이템+일정 포함) |
| PUT | `/{id}` | 업체 수정 |
| DELETE | `/{id}` | 업체 삭제 |

#### Item API (`/api/v1/items`)
| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/businesses/{bid}/items` | 아이템 추가 |
| GET | `/{id}` | 아이템 상세 (일정 포함) |
| PUT | `/{id}` | 아이템 수정 |
| DELETE | `/{id}` | 아이템 삭제 |

#### Schedule API (`/api/v1/schedules`)
| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 전체 일정 (필터: is_enabled, date_from, date_to) |
| GET | `/active` | 워커용 활성 일정 |
| POST | `/items/{iid}/schedules` | 일정 추가 |
| POST | `/items/{iid}/schedules/bulk` | 일정 일괄 추가 |
| GET | `/{id}` | 일정 상세 |
| PUT | `/{id}` | 일정 수정 |
| DELETE | `/{id}` | 일정 삭제 |
| POST | `/{id}/enable` | 활성화 |
| POST | `/{id}/disable` | 비활성화 |

### 3.4 프론트엔드 컴포넌트 구조

```
frontend/src/routes/
├── +page.svelte              → 일정 현황 (메인 대시보드)
├── businesses/
│   └── +page.svelte          → 업체 관리
├── booking/
│   └── +page.svelte          → 예약 설정
├── system/
│   └── +page.svelte          → 시스템 관리
└── (기존 targets 제거)

frontend/src/lib/
├── components/
│   ├── BusinessTree.svelte    → 업체+아이템 트리
│   ├── ScheduleList.svelte    → 일정 목록
│   ├── ScheduleCalendar.svelte → 일정 캘린더
│   ├── ItemCard.svelte        → 아이템 카드
│   └── DateRangePicker.svelte → 날짜 범위 선택
└── api.ts                     → API 클라이언트 수정
```

---

## 4. 데이터 입력 방식

### 4.1 업체 등록
사용자가 입력:
- `business_id`: 네이버 business_id (URL에서 확인)
- `business_type_id`: 네이버 business_type_id (옵션)
- `name`: 업체명
- `category`: 카테고리 (옵션)

### 4.2 아이템 등록
사용자가 입력:
- `biz_item_id`: 네이버 item_id (URL에서 확인)
- `name`: 아이템명
- `time_range`: 예약 시간 범위 (예: "10:00-21:00")
- `auto_booking_enabled`: 자동 예약 여부
- `max_bookings_per_schedule`: 일정당 최대 예약 수

### 4.3 일정 등록
사용자가 입력:
- `dates`: 모니터링할 날짜 목록 (캘린더에서 선택)
- `is_enabled`: 활성화 여부

URL은 시스템이 자동 생성:
```
https://booking.naver.com/booking/{business_type_id}/bizes/{business_id}/items/{biz_item_id}?startDate={date}
```

---

## 5. 실행 순서

1. **Phase 1-4**: 백엔드 정리 (기존 코드 제거, 새 구조로 통일)
2. **Phase 5**: 워커 수정
3. **Phase 6**: API 정리/보강
4. **Phase 7**: 프론트엔드 (별도 진행 가능)
5. **Phase 8**: 테스트

---

## 6. 롤백 계획

- 기존 DB 백업: `cp monitor.db monitor.db.backup.20251202`
- Git 커밋 후 작업 시작
- 문제 발생 시 `git revert` 및 DB 복원

---

## 7. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2025-12-02 | 초기 계획 작성 |
