# 비동기 IO 분리 구현 계획

**작성일**: 2025-12-01
**목적**: DB 쓰기 및 로그 쓰기를 별도 스레드/큐로 분리하여 모니터링 성능 최적화

---

## 배경

현재 worker는 탭 풀을 통해 브라우저 리소스를 효율적으로 관리하고 있으나, DB 쓰기와 로그 쓰기는 동기적으로 처리되어 이벤트 루프를 블로킹할 가능성이 있음.

**향후 확장 계획 (1초 선착순 예약 시스템)을 고려하면 밀리초 단위 최적화가 필수.**

---

## 구현 체크리스트

### Phase 1: 비동기 DB 쓰기 시스템

- [x] **1.1** `app/utils/async_db_writer.py` 생성
  - [x] `AsyncDBWriter` 클래스 구현
  - [x] `asyncio.Queue` 기반 쓰기 대기열
  - [x] `asyncio.to_thread()`로 실제 DB 작업 실행
  - [x] 배치 쓰기 지원 (여러 작업을 묶어서 처리)
  - [x] 안전한 종료 (shutdown) 메서드

- [x] **1.2** Worker 통합
  - [x] `monitor_worker.py`에서 `AsyncDBWriter` 사용
  - [x] `_update_worker_status()` → 큐에 추가 방식으로 변경
  - [x] 하트비트 업데이트 비동기화

- [ ] **1.3** 모니터링 서비스 통합 (선택적 - 필요시 확장)
  - [ ] `monitoring_system_manager.py` 업데이트
  - [ ] 상태 업데이트 작업 비동기화

### Phase 2: 비동기 로그 쓰기 시스템

- [x] **2.1** `app/utils/async_logger.py` 생성
  - [x] `logging.handlers.QueueHandler` 기반 구현
  - [x] `QueueListener`로 별도 스레드에서 파일 쓰기
  - [x] 기존 로거와 동일한 인터페이스 제공

- [x] **2.2** 로깅 설정 업데이트
  - [ ] `config.py`의 `setup_logging()` 수정 (선택적)
  - [x] `setup_worker_logger()` 수정 → `AsyncLoggerManager.setup_worker_logger()` 사용
  - [x] 비동기 로거 옵션 추가

- [x] **2.3** 안전한 종료 처리
  - [x] 프로세스 종료 시 남은 로그 flush (atexit 등록)
  - [x] QueueListener 정리 (`AsyncLoggerManager.shutdown()`)

### Phase 3: 통합 및 테스트

- [x] **3.1** 통합 테스트
  - [x] DB 쓰기 지연 없이 동작 확인 ✅
  - [x] 로그 누락 없이 기록 확인 ✅
  - [x] 종료 시 모든 데이터 저장 확인 ✅

- [ ] **3.2** 성능 측정 (선착순 예약 시스템 개발 시 진행)
  - [ ] 기존 방식 vs 새 방식 응답 시간 비교
  - [ ] 이벤트 루프 블로킹 시간 측정

---

## 구현 상세

### 1. AsyncDBWriter 클래스 설계

```python
# app/utils/async_db_writer.py

class AsyncDBWriter:
    """비동기 DB 쓰기를 위한 큐 기반 Writer"""

    def __init__(self, batch_size: int = 10, flush_interval: float = 1.0):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Writer 시작"""
        self._running = True
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self):
        """안전한 종료 - 남은 작업 모두 처리"""
        self._running = False
        await self._flush_remaining()
        if self._task:
            self._task.cancel()

    async def write(self, operation: Callable, *args, **kwargs):
        """쓰기 작업을 큐에 추가 (non-blocking)"""
        await self.queue.put((operation, args, kwargs))

    def write_nowait(self, operation: Callable, *args, **kwargs):
        """쓰기 작업을 큐에 추가 (동기 호출용)"""
        self.queue.put_nowait((operation, args, kwargs))

    async def _process_loop(self):
        """백그라운드에서 큐 처리"""
        while self._running:
            batch = []
            try:
                # 배치 수집 (타임아웃 또는 배치 크기까지)
                while len(batch) < self.batch_size:
                    try:
                        item = await asyncio.wait_for(
                            self.queue.get(),
                            timeout=self.flush_interval
                        )
                        batch.append(item)
                    except asyncio.TimeoutError:
                        break

                # 배치 실행 (별도 스레드)
                if batch:
                    await asyncio.to_thread(self._execute_batch, batch)
            except Exception as e:
                logger.error(f"DB Writer 오류: {e}")

    def _execute_batch(self, batch: List[Tuple]):
        """실제 DB 작업 실행 (스레드 풀에서)"""
        for operation, args, kwargs in batch:
            try:
                operation(*args, **kwargs)
            except Exception as e:
                logger.error(f"DB 작업 실패: {e}")
```

### 2. 비동기 로거 설계

```python
# app/utils/async_logger.py

import logging
import logging.handlers
import queue
import atexit

class AsyncLoggerSetup:
    """QueueHandler 기반 비동기 로깅 설정"""

    _listeners: List[logging.handlers.QueueListener] = []

    @classmethod
    def setup(cls, logger_name: str, log_file: Path, level: int = logging.DEBUG):
        """비동기 로거 설정"""
        log_queue = queue.Queue(-1)  # 무제한 큐

        # QueueHandler (메인 스레드에서 사용)
        queue_handler = logging.handlers.QueueHandler(log_queue)

        # 실제 파일 핸들러 (별도 스레드에서 실행)
        file_handler = logging.FileHandler(str(log_file), encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))

        # QueueListener (별도 스레드에서 파일에 쓰기)
        listener = logging.handlers.QueueListener(
            log_queue,
            file_handler,
            respect_handler_level=True
        )
        listener.start()
        cls._listeners.append(listener)

        # 로거 설정
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.addHandler(queue_handler)

        return logger

    @classmethod
    def shutdown(cls):
        """모든 리스너 종료"""
        for listener in cls._listeners:
            listener.stop()
        cls._listeners.clear()

# 프로세스 종료 시 자동 정리
atexit.register(AsyncLoggerSetup.shutdown)
```

### 3. Worker 통합 예시

```python
# monitor_worker.py 수정

class MonitorWorker:
    def __init__(self):
        self.db_writer = AsyncDBWriter()
        # ...

    async def initialize(self):
        await self.db_writer.start()
        # ...

    async def _update_worker_status(self):
        # 기존: 직접 DB 호출 (블로킹)
        # 변경: 큐에 추가 (논블로킹)
        self.db_writer.write_nowait(
            self._sync_update_status,
            self.pid, self.status, datetime.now()
        )

    def _sync_update_status(self, pid, status, timestamp):
        """실제 DB 업데이트 (스레드에서 실행)"""
        db = SessionLocal()
        try:
            db.execute(text("UPDATE worker_status SET ..."))
            db.commit()
        finally:
            db.close()

    async def shutdown(self):
        await self.db_writer.stop()  # 남은 작업 완료 대기
        # ...
```

---

## 예상 효과

| 지표 | 현재 | 개선 후 |
|------|------|--------|
| DB 쓰기 블로킹 | 1-10ms | 0ms (큐 추가만) |
| 로그 쓰기 블로킹 | 0.1-1ms | 0ms (큐 추가만) |
| 이벤트 루프 지연 | 가변적 | 최소화 |
| 선착순 예약 대응 | 불가 | **가능** |

---

## 위험 요소 및 대응

1. **종료 시 데이터 손실**
   - 대응: `shutdown()` 시 큐 완전 비우기 + atexit 등록

2. **큐 오버플로우**
   - 대응: 큐 크기 모니터링 + 경고 로그

3. **순서 보장**
   - 대응: 단일 스레드에서 순차 처리로 순서 유지

---

## 참고

- Python `asyncio.to_thread()`: https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread
- `logging.handlers.QueueHandler`: https://docs.python.org/3/library/logging.handlers.html#queuehandler
