# BigQuery Export Schema 설계

> 작성일: 2026-06-15
> 대상 프로젝트: personal-hub
> 산출물: GCP Free-Tier 로드맵 todo-3 산출물
> 상태: 완료

운영 이벤트를 BigQuery로 export할 수 있도록 개인정보·PII를 포함하지 않는 synthetic schema를 정의한다.

---

## 1. 핵심 스키마 정의 (BigQuery Table: `personal_hub_events`)

### 핵심 5컬럼

| 컬럼명 | BigQuery 타입 | Nullable | 설명 | 원본 매핑 |
|--------|-------------|----------|------|---------|
| `event_time` | `TIMESTAMP` | NOT NULL | 이벤트 발생 시각 | `monitoring_events.timestamp`, `scheduled_task_logs.started_at`, `test_runs.started_at`, `error_logs.created_at` |
| `event_type` | `STRING` | NOT NULL | 이벤트 종류 | 허용값 참조 |
| `module` | `STRING` | NOT NULL | 발생 모듈 | `error_logs.source`, `scheduled_task_logs.task_name` |
| `status` | `STRING` | NOT NULL | 이벤트 결과 상태 | `monitoring_events.status`, `scheduled_task_logs.status`, `test_runs.status` |
| `duration_ms` | `INTEGER` | NULLABLE | 처리 소요 시간 (밀리초) | `scheduled_task_logs.duration_seconds × 1000`, `test_runs.duration_seconds × 1000` |

### 선택 2컬럼

| 컬럼명 | BigQuery 타입 | Nullable | 설명 | 원본 매핑 |
|--------|-------------|----------|------|---------|
| `severity` | `STRING` | NULLABLE | 심각도 (error_log 전용) | `error_logs.severity` |
| `error_type` | `STRING` | NULLABLE | 예외 클래스명 (error_log 전용) | `error_logs.error_type` |

---

## 2. 허용값 열거

### `event_type` 허용값

| 값 | 의미 | 원본 소스 |
|----|------|---------|
| `check` | 예약 가능 여부 체크 | `monitoring_events.event_type` |
| `slot_detected` | 예약 슬롯 감지 | `monitoring_events.event_type` |
| `slot_booked` | 예약 완료 | `monitoring_events.event_type` |
| `task_run` | 스케줄 작업 실행 | `scheduled_task_logs` |
| `test_run` | pytest 실행 | `test_runs` |
| `error` | 시스템 에러 | `error_logs` |
| `worker_state` | Instagram 워커 상태 변경 | `instagram_worker_status.current_state` |

### `module` 허용값

| 값 | 의미 | 원본 소스 |
|----|------|---------|
| `naver_booking` | 네이버 예약 모니터링 | `monitoring_events` |
| `scheduled_task` | 스케줄 작업 실행기 | `scheduled_task_logs` |
| `test_run` | 자동 pytest 실행 | `test_runs` |
| `error_log` | 에러 로그 시스템 | `error_logs.source` |
| `instagram_worker` | Instagram 크롤러 워커 | `instagram_worker_status` |

### `status` 허용값

| 값 | 적용 모듈 |
|----|---------|
| `success` | naver_booking, scheduled_task |
| `available` | naver_booking |
| `no_slots` | naver_booking |
| `error` | naver_booking, error_log |
| `running` | scheduled_task, test_run |
| `completed` | test_run |
| `failed` | scheduled_task, test_run |
| `idle` | instagram_worker |
| `crawling` | instagram_worker |
| `processing` | instagram_worker |
| `critical` | error_log |
| `warning` | error_log |

### `severity` 허용값 (error_log 전용)

`critical`, `error`, `warning`

---

## 3. 소스별 export 매핑

### Group A: 직접 export 후보

#### monitoring_event.py

| 원본 컬럼 | export 대상 | BigQuery 컬럼 | 비고 |
|---------|-----------|-------------|-----|
| `timestamp` | ✅ | `event_time` | |
| `event_type` | ✅ | `event_type` | check, slot_detected, slot_booked, error |
| `status` | ✅ | `status` | success, available, no_slots, error |
| `schedule_id` | ❌ | — | FK, 내부 ID |
| `slots_info` | ❌ | — | JSON 슬롯 상세 (과다 데이터) |
| `error_message` | ❌ | — | 에러 메시지 전문 |
| `proxy_url` | ❌ | — | 프록시 URL (내부 인프라) |
| `graphql_response` | ❌ | — | 원본 응답 전문 (용량 초과) |
| `available_count` | 보류 | — | 집계 통계 가능하나 핵심 5컬럼 우선 |
| `response_time_ms` | 보류 | `duration_ms` | 필요 시 추가 가능 |

#### scheduled_task_log.py

| 원본 컬럼 | export 대상 | BigQuery 컬럼 | 비고 |
|---------|-----------|-------------|-----|
| `task_name` | ✅ | `module` | |
| `started_at` | ✅ | `event_time` | |
| `status` | ✅ | `status` | running, success, failed |
| `duration_seconds` | ✅ | `duration_ms` | ×1000 변환 |
| `error_message` | ❌ | — | 에러 메시지 전문 |
| `details` | ❌ | — | JSON 추가 정보 |

#### test_run.py

| 원본 컬럼 | export 대상 | BigQuery 컬럼 | 비고 |
|---------|-----------|-------------|-----|
| `started_at` | ✅ | `event_time` | |
| `status` | ✅ | `status` | running, completed, failed |
| `duration_seconds` | ✅ | `duration_ms` | ×1000 변환 |
| `log_file_path` | ❌ | — | 내부 파일 경로 |
| `xml_file_path` | ❌ | — | 내부 파일 경로 |

### Group B: synthetic 대체 후보

#### error_log.py

| 원본 컬럼 | export 대상 | BigQuery 컬럼 | 비고 |
|---------|-----------|-------------|-----|
| `source` | ✅ | `module` | api, worker, naver, instagram, writing |
| `severity` | ✅ | `severity` | critical, error, warning |
| `error_type` | ✅ | `error_type` | 예외 클래스명 |
| `message` | ❌ | — | 에러 메시지 전문 (PII 가능성) |
| `traceback` | ❌ | — | 스택 트레이스 전문 |
| `context` | ❌ | — | JSON (account_id·url 포함 PII) |

#### instagram_worker_status.py

| 원본 컬럼 | export 대상 | BigQuery 컬럼 | 비고 |
|---------|-----------|-------------|-----|
| `current_state` | ✅ | `status` | idle, crawling, processing |
| `worker_id` | ❌ | — | UUID (개인 식별 가능) |
| `current_account` | ❌ | — | 계정명 (PII) |

#### proxy_usage.py

| 원본 컬럼 | export 대상 | BigQuery 컬럼 | 비고 |
|---------|-----------|-------------|-----|
| — | — | — | 핵심 스키마 대상 아님 — proxy_url, target_url 금지 |

#### request_log.py

| 원본 컬럼 | export 대상 | BigQuery 컬럼 | 비고 |
|---------|-----------|-------------|-----|
| — | — | — | URL·label 전체 금지 — export 불가 |

---

## 4. 금지 필드 목록

BigQuery export 시 포함 절대 금지:

| 필드 | 금지 사유 | 원본 위치 |
|------|---------|---------|
| `message` | 에러 메시지 전문 — PII 포함 가능 | `error_logs.message` |
| `traceback` | 스택 트레이스 전문 | `error_logs.traceback`, `test_results.traceback` |
| `context` | JSON (account_id, url 등 PII) | `error_logs.context` |
| `account_id` | 개인 식별 정보 | `error_logs.context` 내 포함 |
| `url_token` | URL 파라미터 토큰 | `request_logs.url`, `error_logs.context` 내 포함 |
| `slots_info` | JSON 슬롯 상세 (과다 데이터) | `monitoring_events.slots_info` |
| `error_message` | 에러 메시지 전문 | `monitoring_events.error_message`, `scheduled_task_logs.error_message` |
| `details` | JSON 추가 정보 | `scheduled_task_logs.details` |
| `worker_id` | UUID (워커 식별) | `instagram_worker_status.worker_id` |
| `proxy_url` | 프록시 URL (내부 인프라 정보) | `monitoring_events.proxy_url`, `proxy_usage_logs.proxy_url` |
| `target_url` | 크롤링 대상 URL | `proxy_usage_logs.target_url` |
| `graphql_response` | GraphQL 원본 응답 전문 | `monitoring_events.graphql_response` |

---

## 5. 교차 확인: 허용 ∩ 금지 = ∅

### 허용 필드 집합 (export 가능)

```
{ event_time, event_type, module, status, duration_ms, severity, error_type }
```

### 금지 필드 집합

```
{ message, traceback, context, account_id, url_token, slots_info,
  error_message, details, worker_id, proxy_url, target_url, graphql_response }
```

### 교차 확인 결과

| 허용 필드 | 금지 집합 내 존재? | 결과 |
|---------|---------------|-----|
| `event_time` | ❌ | ✅ 허용 |
| `event_type` | ❌ | ✅ 허용 |
| `module` | ❌ | ✅ 허용 |
| `status` | ❌ | ✅ 허용 |
| `duration_ms` | ❌ | ✅ 허용 |
| `severity` | ❌ | ✅ 허용 |
| `error_type` | ❌ | ✅ 허용 |

**교집합 = ∅** (검증 통과)

---

## 6. 금지 필드 유입 차단 — Allowlist 검증 게이트

export 함수에서 금지 필드 유입을 방어하는 allowlist 검증 조건:

```python
BIGQUERY_EXPORT_ALLOWLIST = {
    "event_time", "event_type", "module", "status",
    "duration_ms", "severity", "error_type"
}

def validate_export_row(row: dict) -> dict:
    """export 전 allowlist 검증 게이트."""
    forbidden = set(row.keys()) - BIGQUERY_EXPORT_ALLOWLIST
    if forbidden:
        raise ValueError(f"BigQuery export: 금지 필드 유입 차단 — {forbidden}")
    return {k: v for k, v in row.items() if k in BIGQUERY_EXPORT_ALLOWLIST}
```

- allowlist = 허용 5~7컬럼만
- 금지 필드가 row에 포함되면 ValueError 발생
- export 함수 호출 전 필수 통과

---

## 7. Free-Tier Guard (BigQuery Always Free)

### 비용 상한

| 항목 | 무료 한도 | 비고 |
|------|---------|-----|
| 월 저장량 | 10 GB | 처음 10GB 무료 |
| 월 쿼리량 | 1 TB | 월 1TB 무료 |

### 예상 row 볼륨

- 추정 row 크기: ~200 bytes (7컬럼 × 평균 29 bytes)
- 10 GB / 200 bytes = **50M rows 상한**
- 일 1,000 이벤트 기준: 연 365K rows = **한도 내 안전**
- 일 10,000 이벤트 기준: 연 3.65M rows = **여전히 한도 내 안전**

### 과금 방지 Guard

```sql
-- ❌ 금지: SELECT * (전체 컬럼 스캔으로 쿼리 비용 급증)
SELECT * FROM `project.dataset.personal_hub_events`
WHERE DATE(event_time) = '2026-06-15'

-- ✅ 허용: 컬럼 지정 + 파티션 필터 필수
SELECT event_time, event_type, module, status, duration_ms
FROM `project.dataset.personal_hub_events`
WHERE DATE(event_time) = '2026-06-15'
  AND module = 'naver_booking'
```

| Guard 항목 | 규칙 |
|-----------|-----|
| `SELECT *` 금지 | 반드시 컬럼 명시 선택 |
| 파티셔닝 기준 | `event_time` — DATE 파티션 (`PARTITION BY DATE(event_time)`) |
| 파티션 필터 필수 | 쿼리에 `WHERE DATE(event_time) = ...` 조건 필수 |
| 클러스터링 | `module`, `event_type` 순서로 클러스터링 권장 |

### BigQuery DDL

```sql
CREATE TABLE IF NOT EXISTS `project.dataset.personal_hub_events` (
  event_time    TIMESTAMP NOT NULL,
  event_type    STRING    NOT NULL,
  module        STRING    NOT NULL,
  status        STRING    NOT NULL,
  duration_ms   INT64,
  severity      STRING,
  error_type    STRING
)
PARTITION BY DATE(event_time)
CLUSTER BY module, event_type
OPTIONS (
  partition_expiration_days = 730,  -- 2년 보존
  require_partition_filter  = TRUE  -- 파티션 필터 없는 전체 스캔 금지
);
```

---

## 8. 검증 기준 (RIGHT-BICEP)

| 기준 | 내용 | 충족 |
|------|------|------|
| **R**ight | 5컬럼(`event_time`, `event_type`, `module`, `status`, `duration_ms`)이 정확한 BigQuery 타입으로 정의 | ✅ |
| **B**oundary | 월 저장(10GB)/쿼리(1TB/월) + 50M rows 상한 명시 | ✅ |
| **I**nverse | 금지 필드(`message`, `traceback`, `context`, `account_id`, `url_token`, `slots_info`)가 허용 집합에 0건 | ✅ (교집합 = ∅) |
| **C**ross-check | export 가능 필드 ∩ 금지 필드 = ∅ 결과표 기록 | ✅ (섹션 5) |
| **E**rror | 금지 필드 유입 시 allowlist 검증 게이트 차단 | ✅ (섹션 6) |
| **P**erformance | SELECT * 금지 + `event_time` 파티셔닝 + `require_partition_filter = TRUE` | ✅ (섹션 7) |
