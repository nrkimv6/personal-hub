FastAPI를 사용하여 모니터링 시스템의 API 서버 뼈대를 구현하겠습니다.

먼저 필요한 디렉토리 구조를 만들어보겠습니다:

```
app/
├── __init__.py
├── main.py
├── config.py
├── models/
│   ├── __init__.py
│   └── monitor.py
├── schemas/
│   ├── __init__.py
│   └── monitor.py
├── routes/
│   ├── __init__.py
│   └── monitor.py
└── services/
    ├── __init__.py
    └── monitor_service.py
```

각 파일의 기본 구현을 보여드리겠습니다:

1. 먼저 `app/main.py`:

```python:app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import monitor
from app.config import settings

app = FastAPI(
    title="모니터링 시스템 API",
    description="웹 페이지 모니터링 시스템의 API 서버",
    version="1.0.0"
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(monitor.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "모니터링 시스템 API에 오신 것을 환영합니다"}
```

2. `app/config.py`:

```python:app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 기본 설정
    APP_NAME: str = "모니터링 시스템 API"
    DEBUG: bool = True
    
    # 데이터베이스 설정
    DATABASE_URL: str = "sqlite:///./monitor.db"
    
    # 모니터링 설정
    MAX_WORKERS: int = 3
    MAX_TABS_PER_WORKER: int = 5
    TAB_CLEANUP_THRESHOLD: int = 300
    
    class Config:
        env_file = ".env"

settings = Settings()
```

3. `app/models/monitor.py`:

```python:app/models/monitor.py
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class MonitorTarget(Base):
    __tablename__ = "monitor_targets"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True)
    tag = Column(String)
    validate_level = Column(Integer, default=2)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

4. `app/schemas/monitor.py`:

```python:app/schemas/monitor.py
from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional

class MonitorTargetBase(BaseModel):
    url: HttpUrl
    tag: str
    validate_level: Optional[int] = 2

class MonitorTargetCreate(MonitorTargetBase):
    pass

class MonitorTargetUpdate(MonitorTargetBase):
    is_active: Optional[bool] = None

class MonitorTarget(MonitorTargetBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

5. `app/routes/monitor.py`:

```python:app/routes/monitor.py
from fastapi import APIRouter, HTTPException, Depends
from typing import List

from app.schemas.monitor import MonitorTarget, MonitorTargetCreate, MonitorTargetUpdate
from app.services.monitor_service import MonitorService

router = APIRouter(
    prefix="/monitor",
    tags=["monitor"]
)

@router.get("/targets", response_model=List[MonitorTarget])
async def get_monitor_targets():
    """모니터링 대상 목록을 조회합니다."""
    return []

@router.post("/targets", response_model=MonitorTarget)
async def create_monitor_target(target: MonitorTargetCreate):
    """새로운 모니터링 대상을 추가합니다."""
    return {}

@router.get("/targets/{target_id}", response_model=MonitorTarget)
async def get_monitor_target(target_id: int):
    """특정 모니터링 대상의 상세 정보를 조회합니다."""
    return {}

@router.put("/targets/{target_id}", response_model=MonitorTarget)
async def update_monitor_target(target_id: int, target: MonitorTargetUpdate):
    """모니터링 대상의 정보를 수정합니다."""
    return {}

@router.delete("/targets/{target_id}")
async def delete_monitor_target(target_id: int):
    """모니터링 대상을 삭제합니다."""
    return {"status": "success"}
```

6. `app/services/monitor_service.py`:

```python:app/services/monitor_service.py
from typing import List, Optional
from datetime import datetime

from app.models.monitor import MonitorTarget
from app.schemas.monitor import MonitorTargetCreate, MonitorTargetUpdate

class MonitorService:
    @staticmethod
    async def get_targets() -> List[MonitorTarget]:
        """모든 모니터링 대상을 조회합니다."""
        pass

    @staticmethod
    async def create_target(target: MonitorTargetCreate) -> MonitorTarget:
        """새로운 모니터링 대상을 생성합니다."""
        pass

    @staticmethod
    async def get_target(target_id: int) -> Optional[MonitorTarget]:
        """특정 모니터링 대상을 조회합니다."""
        pass

    @staticmethod
    async def update_target(target_id: int, target: MonitorTargetUpdate) -> Optional[MonitorTarget]:
        """모니터링 대상을 수정합니다."""
        pass

    @staticmethod
    async def delete_target(target_id: int) -> bool:
        """모니터링 대상을 삭제합니다."""
        pass
```

이제 서버를 실행하려면 다음 패키지들을 설치해야 합니다:

```bash
pip install fastapi uvicorn sqlalchemy pydantic pydantic-settings
```

서버 실행 명령:

```bash
uvicorn app.main:app --reload
```

이 구조는 다음과 같은 기능을 제공합니다:

1. 모니터링 대상 CRUD 작업
2. 설정 관리
3. 데이터베이스 모델
4. API 스키마 검증
5. 서비스 레이어 분리

추가로 구현이 필요한 사항:

1. 데이터베이스 연결 설정  -> 완료
2. 실제 모니터링 로직 통합  -> 완료
3. 백그라운드 작업 처리
4. 에러 처리
5. 로깅 시스템
6. 인증/인가 시스템

----

4/9

1. **기본 구조**:
   - FastAPI를 사용한 REST API 서버 구현
   - CORS 미들웨어 설정 완료
   - 기본적인 라우팅 구조 설정

2. **설정 관리**:
   - `config.py`에서 환경 설정 관리
   - Supabase 연동 설정
   - 모니터링 관련 설정 (워커 수, 탭 수 등)

3. **API 엔드포인트**:
   - `/api/v1/monitor/targets` (GET, POST)
   - `/api/v1/monitor/targets/{target_id}` (GET, PUT, DELETE)
   - `/api/v1/monitor/targets/{target_id}/start`
   - `/api/v1/monitor/targets/{target_id}/stop`

4. **서비스 구조**:
   - `MonitorService`: 모니터링 대상 관리
   - `BrowserService`: 브라우저 제어 및 모니터링 실행

5. **데이터 모델**:
   - `MonitorTarget`
   - `MonitorTargetCreate`
   - `MonitorTargetUpdate`

아직 구현이 필요한 부분:

1. **서비스 구현**:  -> 완료
   - `MonitorService`와 `BrowserService`의 실제 구현 코드 확인 필요
   - `browser7.py`와 `run_playwright.py`의 통합 작업 필요

2. **데이터베이스 연동**: --> 임시 sqlite
   - Supabase 연동 구현 필요
   - 모델 정의 및 마이그레이션 필요

3. **에러 처리**:
   - 상세한 에러 처리 및 로깅 구현 필요
   - 예외 처리 강화 필요

4. **보안**:
   - 인증/인가 구현 필요
   - API 키 관리 구현 필요

5. **모니터링 기능**:
   - `browser7.py`와 `run_playwright.py`의 기능을 서비스로 통합
   - 백그라운드 작업 관리 구현

다음 단계로 진행하기 위해서는:

1. `services` 디렉토리의 구현 상태 확인
2. `schemas` 디렉토리의 데이터 모델 정의 확인
3. `models` 디렉토리의 데이터베이스 모델 확인
4. `browser7.py`와 `run_playwright.py`의 통합 방안 구체화



---
3. **웹 인터페이스 구현**:
   - Bootstrap 5를 사용한 반응형 디자인
   - 모니터링 대상 CRUD 기능
   - 실시간 통계 표시
   - 모니터링 상태 관리

다음 단계로 진행할 수 있는 작업들:

1. **수정 기능 구현**: --> TOD 2
   - 대상 수정 모달 구현
   - 수정 API 연동

2. **변경 이력 관리**: --> TODO 3
   - 변경 이력 저장 기능
   - 이력 조회 기능

3. **필터링 및 검색**: --> TODO 1
   - 카테고리별 필터링
   - 검색 기능

4. **실시간 업데이트**:
   - WebSocket을 사용한 실시간 통계 업데이트
   - 실시간 상태 변경 알림


   ---


4/15
## 1. 날짜 기반 스케줄링 시스템 - DONE
- @old에서는 URL의 날짜 파라미터를 기반으로 모니터링 간격을 자동 계산하는 기능이 있음
- `extract_date_from_url()` 및 `calculate_interval()` 함수로 구현
- @app에는 이 날짜 기반 우선순위 스케줄링 기능이 구현되어 있지 않음
- 현재 @app의 설정은 고정된 `CHECK_INTERVAL` 값만 존재

## 2. 콘텐츠 유효성 검사 시스템 - DONE
- @old는 `valid_check.py`에서 다양한 레벨의 콘텐츠 유효성 검사 기능 제공
- `is_content_valid()`, `is_page_availabe()`, `is_full_reservation()` 등의 함수로 구현
- @app에는 이런 세부적인 콘텐츠 유효성 검사 기능이 구현되어 있지 않음

## 3. 시간 및 매수 정보 파싱 - DONE
- @old는 `parse_time_and_stock()` 함수를 통해 버튼 텍스트에서 시간과 매수 정보 추출
- 추출된 정보를 알림 메시지에 포함시키는 기능
- @app의 `notify_change()` 함수에는 이러한 정보 파싱 기능이 없음


## 4. 중복 메시지 필터링 - DONE
- @old는 최근 메시지 리스트를 유지하고 중복 메시지를 필터링하는 기능이 있음
- @app에는 이 중복 메시지 필터링 기능이 구현되어 있지 않음

## 5. 에러 페이지 감지 및 처리 - DONE
- @old는 에러 페이지 감지 및 처리 기능(URL 패턴 확인, 에러 타입 분류 등) 제공
- @app에는 이러한 에러 페이지 감지 및 특별 처리 로직이 없음

## 6. 모니터링 경과 시간 기록 - DONE
- @old는 마지막 확인 시간부터 현재까지의 경과 시간을 계산하고 알림에 포함
- @app에는 이 경과 시간 계산 및 표시 기능이 없음

## 7. 브라우저 탭 관리 최적화 - DONE
- @old는 탭 풀 관리, 오래된 탭 자동 정리 등의 최적화 기능이 있음
- @app에도 비슷한 기능이 구현되어 있지만, 효율성 측면에서 개선 여지가 있음

## 8. URL 목록 관리 방식   -> X
- @old는 `urls.py`에서 JSON 형식으로 URL 목록과 태그 등의 메타데이터 관리
- @app은 데이터베이스를 통해 관리하는 방식으로 변경됨

## 9. 다양한 알림 메시지 형식 - DONE
- @old는 변경 유형에 따라 다양한 알림 메시지 형식 지원
- @app의 알림 메시지는 비교적 단순한 형태로 구현됨

## 10. 브라우저 자동화 감지 방지 설정 - DONE
- @old는 브라우저 자동화 감지 방지를 위한 세부 설정이 있음
- @app에도 일부 구현되어 있지만, 일부 설정이 누락되었을 수 있음


1. **브라우저 자동화 감지 방지 설정**
   - old 버전에서는 더 많은 자동화 감지 방지 설정이 있었지만, app 버전의 `_bypass_automation_detection` 메서드에는 일부만 구현되어 있습니다.
   - `window.navigator` 속성과 관련된 추가 설정이 필요합니다. -> 모순 (차이점 참고)

### 차이점 분석

1. **자바스크립트 우회 설정의 차이**:
   - **app 버전**:
     ```javascript
     // navigator.webdriver 제거
     if (navigator.webdriver === true) {
         Object.defineProperty(navigator, 'webdriver', {
             get: () => false
         });
     }
     
     // plugins 속성 수정
     if (navigator.plugins.length === 0) {
         Object.defineProperty(navigator, 'plugins', {
             get: () => [1, 2, 3, 4, 5]
         });
     }
     
     // 자동화 감지에 사용되는 다른 속성 속이기
     Object.defineProperty(navigator, 'maxTouchPoints', {
         get: () => 1
     });
     ```
   - **old 버전**: 이 부분의 직접 우회 코드가 없으며, 명령줄 인수에 의존하고 있습니다.

2. **브라우저 실행 인수의 차이**:
   - **app 버전**:
     ```
     '--disable-blink-features=AutomationControlled',
     '--disable-features=IsolateOrigins,site-per-process',
     '--disable-site-isolation-trials',
     '--no-sandbox',
     '--disable-setuid-sandbox',
     '--disable-dev-shm-usage',
     '--disable-accelerated-2d-canvas',
     '--disable-gpu',
     '--window-size=1920,1080',
     ```
   - **old 버전**:
     ```
     '--disable-blink-features=AutomationControlled',
     '--disable-extensions',
     '--no-sandbox',
     '--disable-setuid-sandbox',
     '--disable-dev-shm-usage',
     ```

3. **User-Agent와 헤더 설정**:
   - **app 버전**:
     - 브라우저 컨텍스트 생성 시 user_agent를 명시적으로 지정
     - 각 탭 생성 시 'Accept-Language' 헤더도 추가
   - **old 버전**:
     - User-Agent를 명시적으로 설정하지 않음

### 영향 분석

1. **탐지 회피 효과성**:
   - **app 버전**은 더 세밀한 설정으로 더 강력한 탐지 회피가 가능합니다. 특히 JavaScript 기반 탐지에 대해 더 효과적입니다.
   - **old 버전**은 기본적인 명령줄 인수만 사용하여 단순한 탐지는 피할 수 있지만, 정교한 JavaScript 기반 탐지에는 취약할 수 있습니다.

2. **안정성 및 호환성**:
   - **app 버전**의 더 많은 설정은 다양한 사이트와의 호환성을 높일 수 있지만, 일부 설정(특히 `--disable-site-isolation-trials`)은 브라우저 보안에 영향을 줄 수 있습니다.
   - **old 버전**은 더 간단한 접근 방식으로 일부 최신 사이트에서 자동화 탐지될 확률이 높습니다.

3. **실제 사용자 시뮬레이션**:
   - **app 버전**은 User-Agent 지정, 언어 설정 등으로 실제 사용자를 더 잘 시뮬레이션합니다.
   - **old 버전**은 기본 브라우저 특성을 사용하므로 봇으로 식별될 가능성이 높습니다.

### 실질적인 영향

1. **모니터링 대상 웹사이트에서의 차단 가능성**:
   - 웹사이트가 고급 봇 탐지 기술을 사용할 경우, **old 버전**은 차단될 확률이 더 높습니다.
   - 특히 `navigator.webdriver` 속성을 확인하거나 다른 자동화 지표를 확인하는 사이트에서는 차이가 두드러집니다.

2. **Captcha 및 추가 검증**:
   - **old 버전**은 봇으로 의심받아 Captcha나 추가 검증이 필요한 상황이 더 자주 발생할 수 있습니다.
   - **app 버전**은 이러한 상황을 더 잘 회피할 수 있습니다.

3. **장기적 안정성**:
   - 웹사이트의 봇 탐지 기술이 발전함에 따라 **old 버전**은 더 빨리 효과성이 떨어질 수 있습니다.
   - **app 버전**은 더 견고한 접근 방식으로 더 오래 효과적일 가능성이 높습니다.




---
2. **탭 및 브라우저 리소스 관리** -- DONE
   - 현재 app 버전에도 탭 관리 기능이 구현되어 있지만, 오래된 탭 정리 및 리소스 관리에 대한 추가 최적화가 필요합니다.
   - 브라우저 컨텍스트의 메모리 사용량 모니터링 및 주기적 리소스 정리 기능이 부족합니다.

3. **알림 메시지 형식 차이** -- DONE
   - 현재 app 버전에는 `_get_notification_emoji`, `_get_notification_title` 등의 메서드를 통해 다양한 변경 유형에 따른 알림 메시지 형식이 구현되어 있지만, 일부 정보 포맷팅에 차이가 있습니다.
   - 시간 및 매수 정보를 더 상세하게 표시하는 기능이 누락되었습니다.


특히, 신 버전에서는 구조화된 코드와 데이터베이스 저장, FastAPI 서버, 대시보드 등의 기능이 추가되었고, coupang_api와 zigzag_api 관련 코드가 제거되었습니다. 이는 더 일관되고 관리하기 쉬운 코드베이스를 만들기 위한 변경으로 보입니다.




메시지
```
@app 의 누락사항을 찾아서 수정하고 있어,
@old 의 코드를 조사해서 아래 기능을 구현해줘 : 




TODO
1. old에 정의된 기능 추가
2. 구현 및 오류 점검
3. 추가된 기능이 기존 기능에 잘 연결되었는지 확인 (죽은코드가 아니라 참조가 되어야 함.)
4. @server_prd.md  업데이트

```



1. **개별 알림 타입에 따른 메시지 포맷팅**
   - app 버전에서 일부 구현되어 있지만, 메시지 포맷의 세부 사항이 다름
   - old 버전의 다양한 케이스별 알림 메시지 형식이 일부 단순화됨

**old 버전**:
- 다양한 상태 변화에 대해 세분화된 메시지 형식 제공
- 변경 유형에 따라 구체적인 이모티콘과 포맷 사용
- 버튼 텍스트에서 시간과 매수 정보를 직접 파싱하여 알림에 포함
- 메시지 구성이 더 간결하고 핵심 정보 위주

**app 버전**:
- `_get_notification_emoji`와 `_get_notification_title` 메서드를 통해 상태 변화 표현
- 더 풍부한 정보 제공 (날짜 남은 일수, 경과 시간, 페이지 제목 등)
- JSON 형태의 구조화된 데이터로 시간 및 매수 정보 처리
- HTML 포맷팅을 사용하여 텔레그램 메시지에 스타일 적용

**어느 쪽이 더 나은가?**:
- **app 버전이 더 낫습니다.** 이유는:
  1. 더 많은 정보 제공 (남은 일수, 경과 시간 등)
  2. HTML 포맷팅을 통한 가독성 향상
  3. 구조화된 데이터 처리로 확장성 및 유지보수성 개선
  4. 메시지 중복 필터링 기능 강화
  5. 시간별 알림 로그 관리로 불필요한 반복 알림 방지



2. **task_queue 기반 모니터링 작업 관리**
   - old 버전의 개선된 작업 스케줄러가 app 버전에서는 다른 방식으로 구현됨
   - 힙 큐 기반 우선순위 스케줄링이 일부 변경됨


**old 버전**:
- `improved_task_scheduler` 함수에서 힙 큐(heapq)를 사용한 우선순위 스케줄링
- URL의 날짜 정보에 따라 자동으로 다음 실행 시간 계산
- 더 동적인 스케줄링 (날짜 기반 자동 간격 조정)
- 단일 스케줄러에서 모든 URL을 관리하는 중앙집중식 방식
- 코드:
```python
async def improved_task_scheduler(urls, task_queue):
    next_run_times = []
    for index, item in enumerate(urls, start=1):
        date = extract_date_from_url(item["url"])
        interval = calculate_interval(date)  # 날짜 기반 간격 계산
        next_run = time.time() + interval
        heapq.heappush(next_run_times, (next_run, index - 1))

    while True:
        now = time.time()
        if next_run_times and next_run_times[0][0] <= now:
            next_run, url_index = heapq.heappop(next_run_times)
            # 작업 추가...
            date = extract_date_from_url(item["url"])
            interval = calculate_interval(date)  # 다시 계산
            next_run = now + interval
            heapq.heappush(next_run_times, (next_run, url_index))
```

**app 버전**:
- 각 모니터링 대상마다 독립적인 비동기 작업으로 실행
- 데이터베이스에 저장된 간격 값 사용
- 설정 파일에서 날짜 기반 스케줄링 활성화 여부 제어 가능
- 더 고도화된 에러 처리 및 복구 메커니즘
- 코드:
```python
async def monitor_url(self, target_id: int, url: str, label: str):
    # ... 생략 ...
    # 간격 설정 가져오기
    target = await self.monitor_service.get_target(target_id)
    interval = target.interval if target else settings.CHECK_INTERVAL
    
    while True:
        try:
            # ... 모니터링 작업 수행 ...
            await asyncio.sleep(interval)  # 고정된 간격으로 대기
        except Exception as e:
            # 에러 처리
```

**변경된 주요 점**:
1. 힙 큐 기반 우선순위 스케줄링 → 독립적인 작업 루프로 변경
2. 동적 간격 계산 → 데이터베이스에 저장된 간격 사용
3. 중앙집중식 → 분산 처리 방식으로 변경
4. 복잡한 상호작용 → 단순화된 독립 작업

**추천**:
- **하이브리드 접근법을 추천합니다.** app 버전의 구조에 old 버전의 동적 간격 조정 기능을 통합하는 것이 최선입니다.
- old 버전의 날짜 기반 우선순위 스케줄링은 리소스 효율성과 지능적인 모니터링에 유리합니다.
- app 버전의 구조화된 코드와 에러 처리는 안정성과 유지보수성에 유리합니다.
- app 버전에 날짜 기반 스케줄링이 실제로 `monitor_service.py`에 구현되어 있지만, 작업 스케줄러와의 연동 방식이 다릅니다.

app 버전에서 날짜 기반 우선순위 스케줄링을 더 효과적으로 활용하려면, 각 작업의 독립성은 유지하되 다음 실행 시간을 동적으로 계산하여 더 지능적인 스케줄링을 구현하는 것이 좋을 것입니다.



---
4/16


- 메시지에 url 추가
- fastapi 서버 가동
- 대시보드 기능, CRUD
- urls.py -> db 저장 기능 (sqlite)
- 코드 구조화
- 메모리 및 리소스 관리 기능
- zigzag, coupang 제거
- 브라우저 실행 인수 중 일부가 변경됨 ('--disable-extensions' 등)
- 힙 큐 기반 우선순위 스케줄링을 독립적 작업으로 개선


누락 또는 개선이 필요한 부분:

1. **콘텐츠 유효성 검사 활용**:
   - app/services/browser_service.py의 `handle_change` 함수에서 utils/validators.py의 다양한 유효성 검사 기능(특히 `is_full_reservation`)을 더 적극적으로 활용할 필요가 있습니다.

2. **시간/매수 정보 파싱**:
   - notification_service.py에서 `parse_time_and_stock` 함수의 결과를 알림 메시지에 통합하는 부분이 충분히 활용되지 않고 있습니다.

3. **브라우저 세션 관리 효율화**:
   - 브라우저 컨텍스트 재사용 정책을 더 명확히 해야 합니다.
   - 오류 발생 시 탭 복구 전략이 개선되어야 합니다.

4. **설정 파라미터 최적화**:
   - 일부 설정 값들의 최적화가 필요합니다(TAB_CLEANUP_THRESHOLD가 300에서 3000으로 변경된 것 등).

5. **로깅 시스템 개선**:
   - 로깅 메시지 형식의 일관성이 더 필요합니다.
   - 모니터링 정보 로그가 더 체계적으로 관리되어야 합니다.

6. **경과 시간 표시 개선**:
   - notification_service.py에서 마지막 확인 시간부터 현재까지의 경과 시간을 더 가독성 있게 표시해야 합니다.

다음은 특별히 주의해야 할 특정 기능들입니다:

1. **날짜 기반 간격 계산**:
   - config.py에 DATE_BASED_SCHEDULING 설정이 추가되었지만, 실제 monitor_service.py에서 extract_date_from_url과 calculate_interval 함수가 스케줄링에 제대로 활용되는지 확인이 필요합니다.

2. **에러 페이지 감지 및 처리**:
   - config.py에 ERROR_PAGE_DETECTION과 ERROR_PATTERNS가 정의되었지만, 브라우저 서비스에서 이를 적극적으로 활용하는지 확인해야 합니다.

3. **중복 메시지 필터링**:
   - notification_service.py의 중복 메시지 필터링 기능이 구현되었지만, 시간 기반 필터링과 URL 상태 변경 추적 간의 통합이 개선되어야 합니다.

전반적으로 @app에는 대부분의 기능이 구현되어 있지만, 일부 세부 사항이 완전히 통합되지 않았거나 최적화가 필요합니다. 특히 브라우저 자동화 감지 방지 기능은 app 버전이 더 강화되었으므로 문제 없어 보입니다.

개선 사항들에 대한 검토 및 수정이 완료되었습니다. 다음은 각 개선 사항에 대한 변경 요약입니다:

1. **콘텐츠 유효성 검사 활용**:
   - `browser_service.py`의 `handle_change` 함수를 수정하여 `is_content_valid`, `is_full_reservation`, `is_page_available`를 적극적으로 활용합니다.
   - 콘텐츠 유효성 검사 결과에 따라 세분화된 상태 로깅을 추가했습니다.
   - 예약 마감 및 페이지 접근 불가 상태에 대한 특별 처리 로직을 추가했습니다.
   - 검사 결과를 `notify_change` 함수에 전달하여 알림 메시지에 반영합니다.

2. **시간/매수 정보 파싱**:
   - `notification_service.py`의 `notify_change` 함수를 확장하여 `parse_time_and_stock` 함수의 결과를 알림 메시지에 더 효과적으로 통합했습니다.
   - 버튼 텍스트에서 시간과 매수 정보를 추출하여 추가 시간 정보를 생성합니다.
   - 기존 정보가 없는 경우 추가 파싱 정보를 대체로 사용하도록 개선했습니다.
   - 시간 및 매수 정보를 분류하고 중요한 정보를 강조 표시합니다.

3. **브라우저 세션 관리 효율화**:
   - 탭 관리 로직을 최적화하여 설정 파일에서 매개변수를 가져오도록 수정했습니다.
   - 탭 사용 상태 추적 시스템을 강화하여 사용 중인 탭의 관리를 개선했습니다.
   - 오류 발생 시 탭 반환 메커니즘을 강화하여 누수를 방지했습니다.
   - 비활성 컨텍스트 감지 및 자동 정리 로직을 개선했습니다.

4. **설정 파라미터 최적화**:
   - `config.py`에 메모리 관리 및 탭 관리를 위한 새로운 설정을 추가했습니다.
   - 하드코딩된 값을 설정 파일에서 가져오도록 수정하여 유지보수성을 향상시켰습니다.
   - 브라우저 리소스 관리에 필요한 임계값을 설정 파일에서 제어할 수 있도록 했습니다.

5. **로깅 시스템 개선**:
   - `config.py`에 구조화된 로깅 시스템 설정을 추가했습니다.
   - 파일 및 콘솔 로깅을 모두 지원하는 로거 인스턴스를 생성했습니다.
   - 기존 `print` 문을 `logger` 호출로 대체하여 일관성 있는 로깅을 구현했습니다.
   - 로그 레벨에 따라 적절한 메시지 기록(info, debug, warning, error)을 수행합니다.

6. **경과 시간 표시 개선**:
   - 경과 시간 계산 및 표시 로직을 개선하여 가독성을 향상시켰습니다.
   - 시/분/초 단위로 구분하여 더 직관적인 시간 표시 방식을 적용했습니다.
   - 1시간 이상의 경과 시간에 대한 처리를 추가했습니다.

