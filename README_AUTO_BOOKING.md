# 네이버 예약 자동 모니터링 + 자동 예약 시스템

## 개요

`auto_booking_monitor.py`는 browser7.py의 모니터링 기능과 auto_book.py의 예약 기능을 통합한 **완전한 기능의 통합 시스템**입니다.

**주요 기능:**
- ✅ 네이버 예약 페이지 실시간 모니터링 (Fetch API 사용)
- ✅ **다중 URL 동시 모니터링 (워커별 탭 풀 관리)**
- ✅ **브라우저/탭 자동 복구 및 재사용 (browser7.py 전체 기능 포함)**
- ✅ 예약 가능 슬롯 자동 감지
- ✅ 예약 가능 시 자동 예약 실행
- ✅ 텔레그램 알림 발송
- ✅ DRY RUN 모드 (테스트용)
- ✅ **탭 생명주기 관리 (사용 횟수 제한, LRU 방식)**

## 파일 구조

```
monitor-page/
├── auto_booking_monitor.py       # 🆕 통합 시스템 (메인 파일)
├── old/
│   ├── browser7.py               # 모니터링 로직 (재사용)
│   ├── auto_book.py              # 예약 로직 (재사용)
│   └── browser_utils.py          # 🆕 공통 유틸리티
├── url_book.py                   # 예약 URL 목록
└── README_AUTO_BOOKING.md        # 🆕 이 문서
```

## 설치 및 실행

### 1. 의존성 설치 (이미 설치되어 있으면 생략)

```bash
pip install playwright
playwright install chromium
```

### 2. 예약 URL 설정

`url_book.py` 파일에 모니터링할 URL을 추가:

```python
booking_urls = [
    {
        "url": "https://booking.naver.com/booking/12/bizes/123/items/456?startDate=2025-12-02",
        "tag": "서울숲 캠핑장",
        "description": "12월 2일 예약",
        "time_range": "10:00-18:00"  # 선택적: 이 시간대만 알림/예약 (생략 가능)
    },
    # ... 추가 URL
]
```

**시간 범위 필터 (선택적):**
- `time_range` 필드를 추가하면 해당 시간대의 슬롯만 알림/예약합니다
- 형식: `"HH:MM-HH:MM"` (예: `"12:00-14:00"`)
- 특수 케이스:
  - `"12:00-12:00"`: 정확히 12:00만 (같은 시간 = 정확한 매칭)
  - `"22:00-06:00"`: 야간 시간대 (22시~다음날 6시)
  - 생략 시: 모든 시간대 알림

### 3. 설정 변경

`auto_booking_monitor.py` 파일 상단의 설정을 확인:

```python
# 자동 예약 설정
ENABLE_AUTO_BOOKING = True   # False로 설정하면 알림만 발송
DRY_RUN_MODE = True          # True면 실제 예약 버튼을 클릭하지 않음 (테스트용)
```

**⚠️ 중요:**
- **처음 실행 시**: `DRY_RUN_MODE = True` (테스트 모드)
- **실제 예약 시**: `DRY_RUN_MODE = False` (실제 클릭)

### 4. 실행

```bash
# Windows (PowerShell)
.venv\Scripts\python.exe auto_booking_monitor.py

# Windows (cmd)
.venv\Scripts\python.exe auto_booking_monitor.py

# Linux/Mac
.venv/bin/python auto_booking_monitor.py
```

## 동작 방식

### 1. 모니터링 단계 (browser7.py 전체 기능 포함)

```
1. 워커별 탭 풀 관리
   - 탭 재사용 (LRU 방식, MAX_USES_PER_TAB=50)
   - 탭 생존 확인 및 자동 교체
   - 오래된 탭 자동 정리 (10분 미사용 시)

2. 첫 페이지 로드 시 SSR 데이터 추출
   - bookingAvailableCode와 bookingAvailableValue 읽기
   - RI03(N시간 후부터 예약 가능) 정책 확인

3. Fetch API로 예약 가능 여부 확인 (5초마다)
   - 첫 요청 시에만 페이지 로드 (쿠키/세션 확보)
   - 이후 요청은 탭 재사용 (빠른 응답)

4. 슬롯 필터링 (다단계) - 화면 표시 로직과 동일
   a. isUnitSaleDay = true 체크 (판매일만)
   b. isUnitBusinessDay = true 체크 (실제 예약 가능 시간대)
   c. unitStock - unitBookingCount > 0 (재고 확인)
   d. 과거 시간 제거 (현재 시간 이전)
   e. RI03 정책 적용 (현재+N시간 이전 제거)
   f. 모호한 상태 라벨링 (완전모호/부분모호)

5. 예약 가능 슬롯 감지
6. 시간 범위 필터링 (설정된 경우)
7. 변경 사항 감지 (해시 비교)
8. 에러 타입별 탭 처리
   - 심각한 에러 (브라우저 연결 끊김): 탭 교체
   - 경미한 에러 (데이터 처리): 탭 유지 (최적화)
```

### 2. 자동 예약 단계 (ENABLE_AUTO_BOOKING = True인 경우)

```
1. 텔레그램 알림 발송 ("예약 가능!")
2. 페이지 로드
3. 날짜 확인
4. 시간 슬롯 확인
5. 인원 확인
6. 예매 버튼 활성화 대기
7. 예매 버튼 클릭 (DRY_RUN_MODE=False인 경우)
8. 결과 알림 발송
```

## 모드별 동작

### 1. 테스트 모드 (권장)

```python
ENABLE_AUTO_BOOKING = True
DRY_RUN_MODE = True
```

**동작:**
- ✅ 모니터링 실행
- ✅ 예약 가능 시 알림 발송
- ✅ 예약 프로세스 시뮬레이션
- ❌ 실제 예약 버튼 클릭 안함

**용도:** 시스템 테스트, 로직 검증

### 2. 알림 전용 모드

```python
ENABLE_AUTO_BOOKING = False
DRY_RUN_MODE = True  # (무관)
```

**동작:**
- ✅ 모니터링 실행
- ✅ 예약 가능 시 알림 발송
- ❌ 자동 예약 안함

**용도:** 기존 browser7.py와 동일

### 3. 실제 자동 예약 모드 ⚠️

```python
ENABLE_AUTO_BOOKING = True
DRY_RUN_MODE = False
```

**동작:**
- ✅ 모니터링 실행
- ✅ 예약 가능 시 알림 발송
- ✅ **실제 예약 버튼 클릭** 🚨

**⚠️ 주의:**
- 실제 예약이 진행됩니다!
- 충분히 테스트한 후 사용하세요!
- 네이버 로그인이 되어 있어야 합니다!

## 로그 예시

### 모니터링 중

```
[WORKER 1] [서울숲] 확인 #42 - 14:32:15
[DEBUG][서울숲] Using fetch API for faster monitoring
[DEBUG][서울숲] Fetch found 0 available slots (notifiable: 0)
```

### 예약 가능 감지

```
[WORKER 1] [서울숲] ✅ 예약 가능 감지!
[WORKER 1] [서울숲] 슬롯: ['2025-12-02 10:00:00 (2매)', '2025-12-02 14:00:00 (1매)']
[WORKER 1] [서울숲] 🤖 자동 예약 시작...
```

### 자동 예약 진행

```
[BOOKING] 서울숲 예약 시작
[STEP 1] 페이지 로딩 중...
[STEP 2] 선택된 날짜: 2
[STEP 3] 시간 슬롯 확인 중...
[CHECK] 선택 가능한 시간: 오전 10:00, 오후 2:00
[STEP 6] 예매 버튼 활성화 대기 중...
[WAIT] 예매 버튼이 활성화되었습니다!
[STEP 7] 예매 버튼 클릭 준비...
⚠️  [DRY RUN MODE] 실제 예매를 진행하지 않습니다 (테스트 모드)
[SUCCESS] 예약 프로세스 완료!
[WORKER 1] ✅ [서울숲] 자동 예약 시뮬레이션 완료!
```

## 종료

```bash
# Ctrl + C 를 눌러 종료
# 또는 브라우저 창을 닫으면 자동 종료
```

## 주의사항

1. **네이버 로그인 필수**
   - 브라우저 프로필에 네이버 로그인이 저장되어 있어야 합니다
   - 첫 실행 시 수동으로 로그인하세요

2. **DRY_RUN_MODE 확인**
   - 실제 예약 전에 반드시 `DRY_RUN_MODE = True`로 테스트하세요
   - 테스트 완료 후 `DRY_RUN_MODE = False`로 변경

3. **텔레그램 설정**
   - `old/telegram_message.py`에 봇 토큰과 채팅 ID 설정 필요
   - browser7.py에서 이미 설정했다면 그대로 사용 가능

4. **동시 실행 주의**
   - browser7.py와 동시에 실행하지 마세요 (브라우저 프로필 충돌)
   - 하나만 선택해서 실행하세요

5. **브라우저 자동 복구**
   - 탭/브라우저가 죽으면 자동으로 재시작됩니다
   - 복구 중에는 잠시 모니터링이 중단될 수 있습니다

6. **시간 필터링 자동 적용 (화면과 동일한 로직)**
   - **`isUnitBusinessDay=true` 필수 체크** ← 화면 표시 시간대만 추출
   - `isUnitSaleDay=true` 슬롯만 처리 (판매일 필터링)
   - 재고가 있는 슬롯만 처리 (`unitStock > unitBookingCount`)
   - 현재 시간 이전 슬롯은 자동으로 제거됩니다
   - **네이버 예약 정책(RI03) 자동 적용**:
     - 첫 페이지 로드 시 SSR 데이터에서 `bookingAvailableCode`와 `bookingAvailableValue` 추출
     - 예: `RI03` + `1시간` 설정인 경우 → 현재시간 + 1시간 이후 슬롯만 표시
     - 이후 Fetch API 요청에서도 동일한 정책 유지

## 문제 해결

### 브라우저가 열리지 않음
```bash
playwright install chromium
```

### 예약 버튼이 활성화되지 않음
- 수동으로 페이지 확인
- 날짜/시간/인원이 올바르게 선택되었는지 확인

### 알림이 오지 않음
- `telegram_message.py` 설정 확인
- 텔레그램 봇이 활성화되어 있는지 확인

## 기존 시스템과 비교

| 기능 | browser7.py | auto_book.py | auto_booking_monitor.py |
|------|-------------|--------------|-------------------------|
| 모니터링 | ✅ | ❌ | ✅ |
| 알림 | ✅ | ❌ | ✅ |
| 자동 예약 | ❌ | ✅ (수동 실행) | ✅ (자동 실행) |
| Fetch API | ✅ | ❌ | ✅ |
| 테스트 모드 | ❌ | ✅ | ✅ |
| 탭 풀 관리 | ✅ | ❌ | ✅ (완전 동일) |
| 다중 URL | ✅ | ❌ | ✅ |
| 탭 자동 복구 | ✅ | ❌ | ✅ (완전 동일) |

## 개발 정보

- **버전:** 1.0.0
- **개발일:** 2025-11-29
- **기반 코드:** browser7.py + auto_book.py
- **공통 유틸리티:** old/browser_utils.py

## 라이선스

기존 browser7.py, auto_book.py와 동일
