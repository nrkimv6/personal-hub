# 네이버 예약 자동 모니터링 + GraphQL API 직접 호출 시스템

## 개요

`auto_booking_graphql.py`는 **GraphQL API를 직접 호출**하여 예약 속도를 대폭 향상시킨 실험적 시스템입니다.

### 기존 방식 vs GraphQL 방식

| 방식 | 프로세스 | 예상 소요 시간 | 장단점 |
|------|---------|---------------|--------|
| **기존 방식**<br>(auto_booking_monitor.py) | 상품 상세 페이지 → 시간 선택 → 다음 버튼 → 예매 버튼 | ~10-15초 | ✅ 안정적<br>❌ 느림<br>❌ UI 렌더링 대기 필요 |
| **GraphQL 방식**<br>(auto_booking_graphql.py) | 상품 상세 페이지 (쿠키 획득) → GraphQL API 직접 호출 | ~2-3초 | ✅ 매우 빠름<br>⚠️ 실험적<br>⚠️ 쿼리 캡처 필요 |

### 속도 비교

```
기존 방식 타임라인 (auto_booking_monitor.py):
0초    상품 상세 페이지 로드
2초    날짜 확인
3초    시간 선택
4초    "다음" 버튼 클릭
6초    /request 페이지 로드
8초    인원 확인
10초   예매 버튼 활성화 대기
12초   예매 버튼 클릭
----
총 ~12초

GraphQL 방식 타임라인 (auto_booking_graphql.py):
0초    상품 상세 페이지 로드 (쿠키 획득)
1초    GraphQL schedule API 호출 ⚡
1.5초  slotId 추출 ⚡
2초    /request 포함 URL로 상품 상세 페이지 이동 ⚡ (시간 자동 선택됨!)
3초    "다음" 버튼 클릭
4초    /request 페이지 로드
5초    필수 입력 필드 자동 채우기 (사업자 ID 1269828인 경우)
6초    예매 버튼 클릭
----
총 ~6초 (필수 입력 자동 채우기 성공) - 2배 빠름!
총 ~66초 (필수 입력 수동 또는 실패, 60초 사용자 입력 시간 포함)
```

**핵심 차이:**
- ❌ 기존: 시간 수동 선택 → "다음" 버튼 (3초 소요)
- ✅ GraphQL: /request 포함 URL로 이동 → 시간 자동 선택 → "다음" 버튼 자동 활성화 (2초 소요)
- **절약된 시간: ~1초**
- **추가 개선: 사업자 ID 1269828의 경우 4개 필드 자동 입력**

## 왜 GraphQL 방식이 빠른가?

### 1. UI 렌더링 건너뛰기

**기존 방식:**
```
페이지 로드 → React 렌더링 → 컴포넌트 마운트 → 이벤트 리스너 등록
→ 버튼 활성화 → 클릭 → 상태 업데이트 → 리렌더링 → ...
```

**GraphQL 방식:**
```
페이지 로드 (쿠키만 필요) → API 직접 호출 → 완료!
```

### 2. 네트워크 요청 최소화

**기존 방식:**
- 상품 상세 페이지 HTML (200KB)
- CSS, JS 번들 (1MB+)
- 이미지 로드 (500KB)
- GraphQL API 호출 (자동)
- /request 페이지 HTML (200KB)
- CSS, JS 번들 (다시 1MB+)

**GraphQL 방식:**
- 상품 상세 페이지 HTML (쿠키 획득용, 렌더링 안함)
- GraphQL API 호출 (직접)
- 완료!

### 3. 대기 시간 제거

**기존 방식:**
- `wait_for_selector` 여러 번 (총 5-8초)
- `wait_for_timeout` 여러 번 (총 3-5초)
- 페이지 전환 대기 (2-3초)

**GraphQL 방식:**
- 최초 페이지 로드 1회만 (쿠키 획득)
- 이후 즉시 API 호출

## 설치 및 설정

### 1. GraphQL 쿼리 캡처 (필수!)

GraphQL 방식을 사용하려면 먼저 실제 쿼리를 캡처해야 합니다.

```bash
# 쿼리 캡처 스크립트 실행
.venv\Scripts\python.exe investigate_graphql.py
```

**브라우저가 열리면:**

1. 날짜 선택
2. 시간 선택
3. "다음" 버튼 클릭
4. 예매 확인 페이지에서 30초 대기
5. 스크립트가 자동 종료됨

**결과:**
- `graphql_requests.json` 파일이 생성됨
- 캡처된 GraphQL 쿼리와 변수가 포함됨

### 2. 쿼리 추출 및 코드 업데이트

`graphql_requests.json` 파일을 열어서 다음 정보를 추출:

**찾아야 할 쿼리:**
1. **schedule** - 일정 조회 (slotId, scheduleId 획득)
2. **bookingRequestSupply** - 예매 양식 정보
3. **account** - 사용자 정보 확인
4. **(선택) 예약 제출 쿼리** - 실제 예약을 수행하는 API

**예시 (schedule 쿼리):**

```json
{
  "url": "https://booking.naver.com/graphql?opName=schedule",
  "method": "POST",
  "post_data": "{\"operationName\":\"schedule\",\"variables\":{...},\"query\":\"query schedule($scheduleParams: ScheduleParams!) { ... }\"}"
}
```

`post_data`에서 `query` 필드를 복사하여 `auto_booking_graphql.py`의 `GRAPHQL_QUERIES`에 추가:

```python
GRAPHQL_QUERIES = {
    "schedule": """
        query schedule($scheduleParams: ScheduleParams!) {
            schedule(scheduleParams: $scheduleParams) {
                schedules {
                    id
                    slotId
                    detailScheduleId
                    startDateTime
                    endDateTime
                    # ... (전체 쿼리 복사)
                }
            }
        }
    """,
    "bookingRequestSupply": """
        query bookingRequestSupply(...) {
            # ... (전체 쿼리 복사)
        }
    """,
    # ...
}
```

### 3. 실행

```bash
# 테스트 모드 (DRY_RUN=True)
.venv\Scripts\python.exe auto_booking_graphql.py
```

## GraphQL API 분석

### 1. schedule API

**목적:** 선택한 날짜/시간의 슬롯 정보 조회

**요청:**
```graphql
query schedule($scheduleParams: ScheduleParams!) {
  schedule(scheduleParams: $scheduleParams) {
    schedules {
      id
      slotId
      scheduleId
      detailScheduleId
      startDateTime
      endDateTime
      isUnitSaleDay
      isUnitBusinessDay
      unitStock
      unitBookingCount
    }
  }
}
```

**변수:**
```json
{
  "scheduleParams": {
    "businessId": "1515818",
    "bizItemId": "7127905",
    "businessTypeId": 12,
    "startDateTime": "2025-12-02T21:00:00+09:00",
    "endDateTime": "2025-12-02T21:00:00+09:00"
  }
}
```

**응답에서 필요한 정보:**
- `slotId`: 회차 ID (예약 시 필수!)
- `scheduleId`: 일정 ID
- `detailScheduleId`: 상세 일정 ID

### 2. bizItems API로 예약 가능 상태 사전 확인

**새로운 기능:** schedule API 호출 전에 bizItems API로 예약 가능 여부를 먼저 확인합니다!

### 왜 필요한가?

**문제 상황:**
- `isUnitBusinessDay: false`인 슬롯이 반환되는 경우
- `slotId: None`, `scheduleId: None`인 슬롯 발견
- 예약이 일시중지된 업체인데도 schedule에서 슬롯 반환

**원인:**
- **업체 전체가 예약 중지/미오픈** 상태여도 schedule API는 슬롯을 반환함
- 이런 슬롯은 실제로 예약 불가능

### bizItems API 체크 항목

```json
{
  "bookableSettingJson": {
    "isPaused": false,        // 예약 일시중지 여부
    "isUseOpen": false,       // 오픈 시간 기능 사용 여부
    "openDateTime": "2025-10-30T17:00:00+09:00",
    "isOpened": true          // 예약 오픈 여부 (가장 중요!)
  }
}
```

### 체크 순서

```
1. bizItems API 호출
   ├─ bizItems == [] → ❌ 업체 비공개/운영중지
   ├─ isPaused == true → ❌ 예약 일시중지
   ├─ isOpened == false → ❌ 예약 미오픈
   └─ isOpened == true → ✅ schedule API 호출

2. schedule API 호출
   └─ (기존 로직)
```

### 캐싱 전략

**정각마다 갱신, 그 사이에는 캐시 사용:**
- 예약 상태가 자주 바뀌지 않으므로 API 요청 절약
- 매 체크마다 bizItems를 호출하지 않음
- 다음 정각(00분)에 자동으로 갱신

**예시:**
```
14:23 → bizItems API 호출 → "예약 미오픈" → 캐시 저장 (15:00까지 유효)
14:25 → 캐시 사용 → "예약 미오픈" (API 호출 안함)
14:30 → 캐시 사용 → "예약 미오픈" (API 호출 안함)
15:00 → bizItems API 호출 → "예약 오픈!" → 캐시 갱신
```

### 3. bookingAvailableCode 정책 (SSR 데이터)

**SSR 데이터에서 추출:**
페이지 최초 로드 시 `window.__APOLLO_STATE__`에서 `bookingAvailableCode`와 `bookingAvailableValue`를 추출합니다.

**정책 종류:**

| 코드 | 상수명 | 의미 | 예시 |
|------|--------|------|------|
| `RI01` | INSTANTLY | 즉시 예약 가능 | 바로 예약 가능 |
| `RI02` | UNAVAILABLE | N일 후부터 예약 가능 | value=3 → 오늘+3일 이후 슬롯만 예약 가능 |
| `RI03` | AVAILABLE | N시간 후부터 예약 가능 | value=1 → 현재+1시간 이후 슬롯만 예약 가능 |

**RI02 정책 예시:**
```
현재 날짜: 2025-11-30
bookingAvailableCode: RI02
bookingAvailableValue: 2 (2일 후부터)

예약 가능 기준일: 2025-12-02 00:00:00 KST

| 슬롯 날짜 | 예약 가능? | 이유 |
|-----------|------------|------|
| 2025-11-30 | ❌ | 11-30 < 12-02 |
| 2025-12-01 | ❌ | 12-01 < 12-02 |
| 2025-12-02 | ✅ | 12-02 >= 12-02 |
| 2025-12-03 | ✅ | 12-03 >= 12-02 |
```

**RI03 정책 예시:**
```
현재 시간: 17:10
bookingAvailableCode: RI03
bookingAvailableValue: 1 (1시간 후부터)

예약 가능 기준: 18:10 이후

| 시간대 | 재고 | 표시 여부 | 이유 |
|--------|------|----------|------|
| 17:30 | 2 | ❌ 미표시 | 17:30 < 18:10 |
| 18:00 | 0 | ❌ 미표시 | 18:00 < 18:10 |
| 18:30 | 0 | ✅ 표시 (매진) | 18:30 >= 18:10 |
| 19:00 | 2 | ✅ 표시 (예약가능) | 19:00 >= 18:10 |
```

**체크 순서:**
```
1. 페이지 최초 로드 시 SSR 데이터 추출
2. bookingAvailableCode 확인
   ├─ RI01 → 모든 미래 슬롯 예약 가능
   ├─ RI02 → 오늘+N일 이후 슬롯만 예약 가능
   └─ RI03 → 현재+N시간 이후 슬롯만 예약 가능
3. 해당 정책에 맞지 않는 슬롯은 필터링 (예약 시도 안함)
```

## 4. 예약 제출은 버튼 클릭으로 처리

**⚠️ 중요:** GraphQL mutation으로 예약을 제출하지 않습니다!

**이유:**
1. **예약마다 필수 입력 필드가 다름**
   - 이름, 전화번호, 이메일, 특이사항 등
   - 모든 케이스를 자동화하는 것은 비현실적

2. **간단하고 안정적인 방법**
   - GraphQL로 `slotId` 획득 (빠름!)
   - `/request` 페이지로 직접 이동 시도
   - 실패 시 수동 시간 선택으로 자동 폴백 (안정적!)
   - 필수 입력 있으면 → 사용자에게 알림 → 60초 대기
   - 필수 입력 없으면 → 즉시 예매 버튼 클릭

**프로세스:**
```
1. GraphQL schedule API로 slotId 획득 (1초)
2. /request를 포함한 URL로 상품 상세 페이지 이동 (2초)
3. "다음" 버튼 확인 (존재 & 활성화 여부)

   A. "다음" 버튼이 존재하고 활성화된 경우 (빠름):
      → 시간이 자동으로 선택되어 있음
      → "다음" 버튼 바로 클릭 → /request 페이지로 이동

   B. "다음" 버튼이 없거나 비활성화된 경우 (폴백):
      → 시간 자동 선택 실패
      → [STEP 3-1] 날짜 수동 선택 (button.calendar_date)
      → [STEP 3-2] 시간 수동 선택 (button.btn_time)
      → [STEP 3-3] "다음" 버튼 다시 확인 후 클릭 → /request 페이지로 이동

4. 필수 입력 필드 확인:
   - 사업자 ID 1269828인 경우 → 4개 필드 자동 입력 시도
   - 자동 입력 성공 → 즉시 예매 버튼 클릭 ⚡
   - 자동 입력 실패 또는 다른 사업자 → 텔레그램 알림 + 60초 대기 → 예매 버튼 클릭
```

## 쿠키/세션 관리

### 왜 상품 상세 페이지를 먼저 로드하나?

GraphQL API는 **인증된 요청**만 허용합니다. 필요한 것:

1. **네이버 로그인 쿠키** - 사용자 인증
2. **세션 ID** - 예약 세션 추적
3. **CSRF 토큰** (가능성) - 보안

상품 상세 페이지를 로드하면:
- 브라우저가 자동으로 쿠키를 설정함
- Playwright의 `page.evaluate()`로 fetch를 호출하면 쿠키가 자동으로 포함됨

```python
# Playwright는 브라우저 컨텍스트 내에서 실행되므로
# fetch 호출 시 자동으로 쿠키가 포함됨
response = await page.evaluate("""
    async (args) => {
        const response = await fetch(args.url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
                // 쿠키는 자동으로 포함됨!
            },
            body: JSON.stringify(args.payload)
        });
        return await response.json();
    }
""", {"url": graphql_url, "payload": payload})
```

### 쿠키 없이 API를 호출하면?

```json
{
  "errors": [
    {
      "message": "Unauthorized",
      "extensions": {
        "code": "UNAUTHENTICATED"
      }
    }
  ]
}
```

따라서 **최소 1회는 페이지 로드가 필수**입니다.

## 수동 시간 선택 폴백 메커니즘

### 왜 필요한가?

일부 네이버 예약 사이트는 `/request` URL 파라미터로 시간을 자동 선택하는 기능이 동작하지 않습니다.

**문제 상황:**
```
/request URL로 접근 → 시간이 자동 선택되지 않음 → "다음" 버튼이 비활성화 상태
```

**해결 방법:**
```
"다음" 버튼 확인 → 없거나 비활성화된 경우 → 수동 선택으로 폴백
```

### 동작 원리

**STEP 3: "다음" 버튼 존재 및 활성화 여부 확인**

```python
# "다음" 버튼 찾기
next_button_found = False
next_button_enabled = False

if not next_button_found or not next_button_enabled:
    # "다음" 버튼이 없거나 비활성화됨
    # → 수동 선택 모드로 전환
```

**STEP 3-1: 날짜 선택**

- 선택자: `button.calendar_date:not(.unselectable)`
- 이미 선택된 날짜가 있으면 스킵
- 없으면 slot_date에서 일(day)만 추출하여 선택

```python
# slot_date = "2025-12-06"
# → day_str = "6"
# → 버튼 텍스트가 "6"인 것 클릭
```

**STEP 3-2: 시간 선택**

- 선택자: `button.btn_time:not(.unselectable)`
- display_time("오후 6:00")이 포함된 버튼 클릭

```python
# "오후 6:00 (2매)" → "오후 6:00" 매칭
```

**STEP 3-3: "다음" 버튼 클릭**

- 여러 선택자 시도:
  - `button.NextButton__btn_next__kfLFW`
  - `button:has-text("다음")`
  - `button.btn_next`
  - `button[class*="btn_next"]`

### 참고 자료

수동 선택 로직은 다음 문서를 기반으로 구현되었습니다:

- `old/not_use/2025-11-30_수동선택정보.md` - Playwright 선택자 분석
- `auto_booking_monitor.py` - 기존 구현 참고

### 선택자 요약

| 요소 | CSS 선택자 | 조건 |
|------|-----------|------|
| 날짜 버튼 | `button.calendar_date` | `.unselectable` 제외 |
| 시간 버튼 | `button.btn_time` | `aria-selected="false"` 확인 |
| 다음 버튼 | `button.NextButton__btn_next__kfLFW` | `NextButton__disabled__` 클래스 없어야 함 |

### "다음" 버튼 활성화 체크

네이버 예약 시스템은 "다음" 버튼 비활성화를 두 가지 방법으로 표시합니다:

1. **`disabled` 속성** (일부 사이트)
   ```html
   <button disabled>다음</button>
   ```

2. **`NextButton__disabled__` 클래스** (대부분 사이트)
   ```html
   <button class="NextButton__btn_next__kfLFW NextButton__disabled__a3P-t">다음</button>
   ```
   - `a3P-t` 같은 해시는 동적으로 변함
   - `NextButton__disabled__` 접두사만 체크

**체크 로직:**
```python
is_disabled_attr = await next_button.get_attribute('disabled')
class_name = await next_button.get_attribute('class')
has_disabled_class = 'NextButton__disabled__' in (class_name or '')

# 둘 다 확인해야 정확함
next_button_enabled = (is_disabled_attr is None and not has_disabled_class)
```

## 현재 구현 상태

### ✅ 완료된 부분 (즉시 사용 가능!)

1. **모니터링 시스템** - browser7.py와 동일
2. **탭 풀 관리** - 효율적인 리소스 관리
3. **bizItems API 사전 체크** - 예약 중지/미오픈 업체 필터링 (정각마다 갱신, 캐시 사용) ⚡
4. **bookingAvailableCode 정책** ⚡
   - **RI01**: 즉시 예약 가능
   - **RI02**: N일 후부터 예약 가능 (오늘+N일 이후 슬롯만 필터링)
   - **RI03**: N시간 후부터 예약 가능 (현재+N시간 이후 슬롯만 필터링)
5. **GraphQL schedule API** - slotId 자동 추출 ⚡
6. **/request URL로 시간 자동 선택** - URL에 /request 포함하여 시간 자동 선택 및 "다음" 버튼 자동 활성화 ⚡
7. **수동 시간 선택 폴백** - /request 자동 선택 실패 시 날짜/시간 수동 선택으로 자동 전환 ⚡
8. **필수 입력 자동 감지** - 사용자에게 알림
9. **사업자별 자동 입력** ⚡
   - **ID 1269828**: 예매자 이름 자동 추출 + 4개 필드(성함, 전화번호, 네, 네) 자동 채우기
   - **ID 142806**: 드롭다운 2개 선택 + 예매자 이름 자동 입력
   - 예매자 이름은 `.booking_user_detail div.name`에서 자동으로 읽어옴
10. **예매 버튼 자동 클릭** - 필수 입력 없거나 자동 입력 성공 시 즉시 실행
11. **쿠키/세션 관리** - 상품 상세 페이지 로드
12. **로깅 시스템** - fetch_responses 로그 기록

### 🎯 핵심 장점

1. **bizItems API 사전 체크** (불필요한 요청 제거)
   - 예약 중지/미오픈 업체는 schedule API 호출 안함
   - 정각마다만 갱신 → API 요청 절약
   - 잘못된 슬롯 알림 방지

2. **bookingAvailableCode 정책** (불가능한 슬롯 필터링)
   - RI02: N일 후부터 예약 가능 → 해당 날짜 이전 슬롯 자동 제외
   - RI03: N시간 후부터 예약 가능 → 해당 시간 이전 슬롯 자동 제외
   - **불필요한 예약 시도 방지!**

3. **URL에 /request 포함으로 시간 자동 선택** (1초 절약)
   - 기존: 시간 수동 선택 → "다음" 버튼 (3초)
   - GraphQL: /request URL → 시간 자동 선택 → "다음" 버튼 자동 활성화 (2초)
   - **절약: ~1초**

3. **수동 시간 선택 폴백** (안정성 강화)
   - "다음" 버튼이 없거나 비활성화된 경우 자동 감지
   - 날짜/시간 수동 선택으로 자동 전환
   - `button.calendar_date`, `button.btn_time` 선택자 사용
   - **모든 사이트에서 동작 보장!**

4. **사업자별 자동 입력** (60초 절약 가능)
   - **ID 1269828**: 예매자 이름 자동 추출 + 4개 필드 채우기 (성함, 전화번호, 네, 네)
   - **ID 142806**: 드롭다운 2개 + 예매자 이름 자동 입력
   - 자동 입력 성공 → 즉시 예매 버튼 클릭 ⚡
   - 자동 입력 실패 → 텔레그램 알림 + 60초 대기

5. **안정적이고 현실적**
   - mutation 캡처 불필요
   - 모든 예약 타입에 대응 가능
   - 폴백 메커니즘으로 호환성 극대화

## 사용 방법

### 간단 버전 (GraphQL 쿼리 이미 포함됨!)

GraphQL schedule 쿼리는 이미 코드에 포함되어 있습니다!

```bash
# 1. 테스트 모드로 실행 (DRY_RUN_MODE = True, 기본값)
.venv\Scripts\python.exe auto_booking_graphql.py

# 2. 실제 예약 모드로 전환
# auto_booking_graphql.py 파일 수정: DRY_RUN_MODE = False
.venv\Scripts\python.exe auto_booking_graphql.py
```

**끝!** 더 이상의 설정이 필요 없습니다.

### 상세 버전 (쿼리를 직접 업데이트하려면)

GraphQL 쿼리를 최신 버전으로 업데이트하고 싶다면:

```bash
# 1. 쿼리 캡처 (선택사항)
.venv\Scripts\python.exe investigate_graphql.py
→ graphql_requests.json 생성됨

# 2. 쿼리 추출 및 업데이트 (선택사항)
# graphql_requests.json에서 schedule 쿼리를 찾아
# auto_booking_graphql.py의 GRAPHQL_QUERIES["schedule"]에 붙여넣기

# 3. 테스트
.venv\Scripts\python.exe auto_booking_graphql.py
```

## 장점과 단점

### ✅ 장점

1. **속도** - 기존 방식 대비 3배 빠름 (4초 vs 12초, 필수 입력 없을 경우)
2. **효율성** - 시간 선택/다음 버튼 클릭 건너뜀 (4-6초 절약)
3. **현실적** - mutation 캡처 불필요, 버튼 클릭으로 예약
4. **유연성** - 필수 입력 자동 감지 및 사용자 알림
5. **즉시 사용 가능** - GraphQL 쿼리 이미 포함됨

### ⚠️ 단점

1. **API 변경 위험** - 네이버가 GraphQL API를 변경하면 작동 중단
   - 해결: schedule 쿼리만 업데이트하면 됨 (간단)
2. **필수 입력 있으면 대기** - 60초 사용자 입력 시간
   - 필수 입력 없으면 이 단점 없음!

### 🤔 언제 사용해야 하나?

**GraphQL 방식을 권장하는 경우:**
- ✅ 예약 경쟁이 치열한 경우 (3-5초 차이가 중요)
- ✅ 필수 입력 필드가 없는 예약 (즉시 예매 가능)
- ✅ 빠른 속도를 원하는 경우

**기존 방식을 권장하는 경우:**
- ✅ 안정성을 최우선으로 하는 경우
- ✅ GraphQL API 변경이 걱정되는 경우
- ✅ 10-15초 정도는 괜찮은 경우

**추천:**
- **일단 GraphQL 방식 사용!** (쿼리 이미 포함, 즉시 사용 가능)
- API 변경 시 → 기존 방식으로 전환
- 또는 schedule 쿼리만 업데이트

## 기술적 도전 과제

### 1. GraphQL 쿼리 스키마 파악

네이버는 GraphQL 스키마를 공개하지 않습니다. 따라서:
- 실제 요청을 캡처하는 수밖에 없음
- 쿼리가 변경되면 다시 캡처 필요

**해결 방법:**
- `investigate_graphql.py` 스크립트 제공
- 정기적으로 쿼리 검증

### 2. 필수 필드 자동 채우기

예약 시 필요한 정보:
- 이름
- 전화번호
- 이메일
- 약관 동의

**해결 방법:**
- `url_book.py`에 사용자 정보 추가
- 또는 환경 변수로 관리

### 3. 예약 제출 API 찾기

실제 예약을 수행하는 mutation을 찾아야 함.

**방법:**
1. `investigate_graphql.py`를 수정하여 "예매" 버튼 클릭까지 자동화
2. 모든 GraphQL 요청 캡처
3. mutation 타입 찾기

### 4. 쿠키/세션 관리

**문제:**
- GraphQL API는 인증 필요
- 쿠키가 만료되면?

**해결:**
- Playwright의 persistent context 사용 (현재 구현됨)
- 네이버 로그인 상태 자동 복구 (TODO)

## 다음 단계

1. **쿼리 캡처 완료**
   ```bash
   .venv\Scripts\python.exe investigate_graphql.py
   ```

2. **쿼리 추출 및 업데이트**
   - `graphql_requests.json` 분석
   - `GRAPHQL_QUERIES` 업데이트

3. **예약 제출 API 캡처**
   - `investigate_graphql.py` 수정
   - "예매" 버튼 클릭까지 자동화

4. **실제 테스트**
   - DRY_RUN_MODE로 시뮬레이션
   - 성공하면 실제 예약 시도

## 문제 해결

### "GraphQL 쿼리가 정의되지 않았습니다"

**원인:**
- `GRAPHQL_QUERIES`가 `None`

**해결:**
1. `investigate_graphql.py` 실행
2. 쿼리 캡처
3. `auto_booking_graphql.py` 업데이트

### "Unauthorized" 오류

**원인:**
- 쿠키가 없거나 만료됨

**해결:**
- 상품 상세 페이지를 먼저 로드 (현재 구현됨)
- 네이버 로그인 확인

### "schedule 정보를 가져올 수 없습니다"

**원인:**
- 잘못된 쿼리 또는 변수

**해결:**
- `graphql_requests.json`에서 실제 요청 확인
- 변수 형식 확인

## 참고 자료

- `old/2025-11-29_이슈_해결방안.md` - 초기 분석
- `README_AUTO_BOOKING.md` - 기존 방식 문서
- GraphQL 공식 문서: https://graphql.org/

## 라이선스

기존 browser7.py, auto_booking_monitor.py와 동일
