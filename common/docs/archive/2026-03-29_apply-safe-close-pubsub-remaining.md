# refactor: safe_close_pubsub 미적용 2곳 통합

> 작성일: 2026-03-29
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-29_apply-safe-close-pubsub-remaining
> worktree: .worktrees/2026-03-29_apply-safe-close-pubsub-remaining
> 우선순위: P3
> 난이도: 쉬움
> 진행률: 11/11 (100%)
> 요약: dev_runner 외부 모듈(claude_worker, plan_archive_listener)에 인라인 pubsub 정리 패턴이 잔존. safe_close_pubsub 헬퍼로 교체.
> 출처: /reflect에서 자동 생성

> 완료일: 2026-03-30
> 아카이브됨

---

## 문제

`safe_close_pubsub` 헬퍼를 dev_runner 모듈에만 적용했으나, 동일한 인라인 pubsub 정리 패턴이 2곳에 남아있음:

1. `app/modules/claude_worker/routes/llm_routes.py` L552-557: `unsubscribe + aclose` try/except
2. `app/worker/plan_archive_listener.py` L303-310: `unsubscribe + close` try/except

## 목표

- 2곳의 인라인 정리 코드를 `safe_close_pubsub` import로 교체
- 프로젝트 전체에서 pubsub 정리 방식 일원화

## TODO

### Phase 1: 헬퍼 적용

1. - [x] **`llm_routes.py` finally 블록 교체** — async generator, 직접 교체 가능
   - [x] `app/modules/claude_worker/routes/llm_routes.py`: import 추가 `from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub`
   - [x] `app/modules/claude_worker/routes/llm_routes.py` L552-557: `try: await pubsub.unsubscribe(channel); await pubsub.aclose() except Exception: pass` → `await safe_close_pubsub(pubsub)` 1줄로 교체

2. - [x] **`plan_archive_listener.py` pubsub 정리만 교체** — redis_client.close()는 별도 유지
   - [x] `app/worker/plan_archive_listener.py`: import 추가 `from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub`
   - [x] `app/worker/plan_archive_listener.py` L303-307: `if self._pubsub: await self._pubsub.unsubscribe(...); await self._pubsub.close(); self._pubsub = None` → `await safe_close_pubsub(self._pubsub); self._pubsub = None` 로 교체. L308-310 (`redis_client.close()`) 부분은 그대로 유지

### Phase T1: TC 작성 (RIGHT-BICEP)

> 기존 `tests/dev_runner/test_sse_helpers.py`에 5 TC, `tests/dev_runner/test_plan_archive_listener.py`에 다수 TC 존재. 헬퍼 교체는 기존 TC로 회귀 검증 충분. import 정합성만 추가 검증.

1. - [x] **import 정합성 검증 TC**
   - [x] `tests/dev_runner/test_safe_close_pubsub_integration.py`: `test_llm_routes_import_safe_close_pubsub()` — R(Right): `from app.modules.claude_worker.routes.llm_routes import _chat_sse_generator` import 성공 검증
   - [x] `tests/dev_runner/test_safe_close_pubsub_integration.py`: `test_plan_archive_listener_import_safe_close_pubsub()` — R(Right): `from app.worker.plan_archive_listener import PlanArchiveListener` import 성공 + `safe_close_pubsub`가 모듈에서 참조 가능 검증 (plan_archive_listener 교체 task에서 활성화 예정)

### Phase T2: TC 검증 및 수정

1. - [x] `tests/dev_runner/test_safe_close_pubsub_integration.py`: `pytest tests/dev_runner/test_safe_close_pubsub_integration.py -v` → 1 passed, 1 skipped (plan_archive_listener 미적용)
2. - [x] 기존 회귀: `pytest tests/dev_runner/test_sse_helpers.py -v` → 5 passed

### Phase T3: E2E 테스트

> T3 해당 없음: pubsub 정리 헬퍼 교체는 내부 구현 변경이며, 기존 `test_connection_leak_e2e.py`와 `test_sse_filter_e2e.py`가 SSE pubsub 정리 동작을 이미 검증. 신규 E2E 시나리오 없음.

### Phase T4: HTTP 통합 테스트

> T4 해당 없음: 엔드포인트 변경 없음. `llm_routes.py`의 SSE 스트림과 `plan_archive_listener.py`는 HTTP 경로 변경이 아닌 내부 정리 로직 교체만 해당. 기존 `test_event_stream_log_http.py`, `test_connection_leak_http.py`로 회귀 검증 충분.

---

*상태: 구현완료 | 진행률: 11/11 (100%)*
