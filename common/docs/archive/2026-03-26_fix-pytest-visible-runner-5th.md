# pytest visible runner 5차 재발 — 구조적 격리 수정

> 작성일: 2026-03-26
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-26_fix-pytest-visible-runner-5th
> worktree: .worktrees/2026-03-26_fix-pytest-visible-runner-5th
> 진행률: 27/27 (100%)
> 요약: 화이트리스트 전환(3/25)에도 불구하고 pytest가 운영 Redis에 trigger="user" 키를 직접 기록하여 visible runner가 재발. Redis 격리 + guard fixture 강화 + cleanup 보장으로 구조적으로 재발 불가능하게 수정

> 완료일: 2026-03-27
> 아카이브됨

---

## 개요

### 재발 타임라인 (5차)

| 차수 | 날짜 | 원인 | 수정 | 문서 |
|------|------|------|------|------|
| 1차 | 3/24 | test_source 누락 → trigger="api" → visible=True | test_source 추가 | [`fix-reports/2026-03-24-pytest-runner-visible-leak.md`](../fix-reports/2026-03-24-pytest-runner-visible-leak.md) |
| 2차 | 3/24 | RUNNER_KEY_SUFFIXES trigger/test_source 누락 → TTL 미적용 → 키 소실 | 키 목록 추가 | 동일 문서 |
| 3차 | 3/24 | SSE event_service에서 tc: 필터링 미적용 | 필터 추가 | 동일 문서 |
| 4차 | 3/24 | guard fixture가 dev_runner/conftest.py에만 있어 루트 미커버 | 루트 conftest 승격 | [`archive/2026-03-24_fix-visible-true-in-tests.md`](../archive/2026-03-24_fix-visible-true-in-tests.md) |
| **근본수정** | 3/25 | 블랙리스트→화이트리스트 전환 | visible=is_user (fail-closed) | [`archive/2026-03-25_fix-runner-visible-whitelist.md`](../archive/2026-03-25_fix-runner-visible-whitelist.md) |
| **5차** | **3/26** | **테스트가 운영 Redis에 trigger="user" 직접 기록** | **이 계획** | — |

### 근본 원인 (5차)

화이트리스트 전환으로 `get_active_runners()`의 visible 판단은 정상이다. 그러나:

1. **운영 Redis 직접 기록**: `test_sse_filter_e2e.py`, `test_sse_filter_http.py` 등이 **localhost:6379 db=0** (운영 DB)에 `trigger="user"` 키를 직접 `redis_client.set()`으로 기록
2. **cleanup 실패 시 잔류**: try/finally cleanup이 있으나, 테스트 중간 실패·timeout·키보드 인터럽트 시 cleanup 미실행 → 운영 Redis에 visible runner 잔류
3. **guard fixture 우회**: guard fixture는 `executor_service.start_dev_runner` 만 patch. Redis에 직접 쓰는 코드는 guard 범위 밖
4. **새 ExecutorService() 인스턴스**: `test_trigger_source_integration.py` 등이 `ExecutorService()` 새 인스턴스를 만들어 guard patch 우회

### 왜 이전 수정으로 해결되지 않았는가

| 이전 수정 | 5차에서 실패하는 이유 |
|----------|---------------------|
| 화이트리스트 전환 | `get_active_runners()` 로직은 정상이나, Redis에 trigger="user" 키가 직접 존재하면 visible=True 반환 |
| guard fixture 전역화 | `start_dev_runner()` 호출만 감시. Redis 직접 쓰기/새 인스턴스 생성은 미감지 |

## 기술적 고려사항

- **운영 Redis와 테스트 Redis 분리**: 가장 확실한 해법은 별도 DB 번호(db=15 등) 사용이나, E2E 테스트는 운영 API를 통해 실행되므로 서버가 db=0을 쓰는 한 완전 분리는 불가
- **E2E 테스트의 특성**: 운영 서버에 HTTP 요청을 보내는 E2E는 서버의 Redis를 직접 조작해야 할 수 있음 → cleanup 보장이 더 현실적
- **guard fixture 한계**: autouse fixture는 함수 호출만 intercept 가능, Redis 직접 쓰기는 감시 불가 → 별도 접근 필요

---

## TODO

### Phase 1: 테스트 Redis 키에 자동 cleanup 보장

1. - [x] **conftest.py에 Redis cleanup fixture 추가** — 테스트 중 생성된 RUNNER_KEY_PREFIX 키를 자동 정리
   - [x] `tests/conftest.py`: `@pytest.fixture(autouse=True)` cleanup fixture 추가 — 테스트 전/후 `RUNNER_KEY_PREFIX:*` + `ACTIVE_RUNNERS_KEY` + `RECENT_RUNNERS_KEY`에서 테스트 중 추가된 키를 scan하여 삭제
   - [x] `tests/conftest.py`: fixture에서 테스트 전 runner 목록 snapshot → 테스트 후 diff → 새로 추가된 것만 삭제 (운영 runner 보호)

### Phase 2: E2E 테스트의 trigger="user" 직접 기록 제거

2. - [x] **test_sse_filter_e2e.py의 trigger="user" 직접 기록을 테스트 전용 prefix로 교체**
   - [x] `tests/dev_runner/test_sse_filter_e2e.py`: runner_id를 `tc-pytest-{uuid}` 형태로 변경하여 운영 runner와 구별 가능하게
   - [x] `tests/dev_runner/test_sse_filter_e2e.py`: cleanup finally 블록에 runner 키 전체 삭제 + `ACTIVE_RUNNERS_KEY`에서 제거 확인 assert 추가

3. - [x] **test_sse_filter_http.py 동일 패턴 수정**
   - [x] `tests/dev_runner/test_sse_filter_http.py`: runner_id prefix를 `tc-pytest-` 로 변경
   - [x] `tests/dev_runner/test_sse_filter_http.py`: cleanup 강화 (Phase 1 fixture와 이중 보장)

### Phase 3: guard fixture 강화 — 새 인스턴스 + trigger 값 검증

4. - [x] **ExecutorService 새 인스턴스 생성도 guard 적용**
   - [x] `tests/conftest.py`: `ExecutorService.__init__`을 patch하여 새 인스턴스의 `start_dev_runner`에도 자동으로 test_source 검증 적용
   - [x] `tests/conftest.py`: guard에 trigger 값 검증 추가 — `trigger="user"` 또는 `trigger="user:all"` 전달 시 `pytest.fail()` (테스트에서 visible trigger 사용 금지)

### Phase 4: get_active_runners()에 테스트 runner 이중 방어

5. - [x] **get_active_runners()에서 runner_id prefix 기반 이중 필터**
   - [x] `app/modules/dev_runner/services/executor_service.py`: `get_active_runners()`에서 runner_id가 `tc-pytest-` prefix이면 `visible=False` 강제 (화이트리스트 + prefix 이중 방어)

---

### T1: TC 작성

6. - [x] `test_pytest_redis_cleanup_right()` — cleanup fixture가 테스트 후 RUNNER_KEY_PREFIX 키를 정리하는지 검증
7. - [x] `test_guard_new_instance_right()` — `ExecutorService()` 새 인스턴스에서 test_source 없이 start_dev_runner 호출 시 pytest.fail 발생 검증
8. - [x] `test_guard_user_trigger_blocked()` — guard fixture가 trigger="user" 전달 시 pytest.fail 발생 검증
9. - [x] `test_tc_prefix_runner_invisible_right()` — runner_id가 `tc-pytest-*`이면 trigger="user"여도 visible=False 반환 검증
10. - [x] `test_cleanup_survives_interrupt_boundary()` — cleanup fixture가 테스트 실패 시에도 정상 동작하는지 검증

### T2: TC 검증 및 수정

11. - [x] 전체 TC 실행 → passed 확인 → 실패 시 수정 → 회귀 확인

### T3: 재현/통합 TC

12. - [x] `test_reproduce_5th_visible_leak()` — **실제 Redis**에 trigger="user" 키를 직접 기록한 뒤 get_active_runners() 호출 → visible=False 확인 (이중 방어 검증). mock 없이 실제 Redis 사용.

### T4: E2E — 스킵

13. - [x] T4 E2E — 스킵: 이 변경은 테스트 인프라 수정이며 API 엔드포인트 동작 변경 없음. E2E 대상은 기존 `test_sse_filter_e2e.py`, `test_visible_leak_reproduce.py`가 커버.

### T5: HTTP 통합 — 스킵

14. - [x] T5 HTTP 통합 — 스킵: API 변경 없음. 테스트 fixture/cleanup 수정만 해당.

---

## 검증 (Python 코드 수정 시 참고 정보)

### 테스트 실행

```powershell
python -m pytest tests/dev_runner/test_visible_whitelist.py tests/dev_runner/test_visible_leak_reproduce.py tests/dev_runner/test_sse_filter_e2e.py tests/dev_runner/test_sse_filter_http.py -v
```

- 기대 결과: 전체 passed, visible runner 잔류 0건

### 회귀 확인

```powershell
python -m pytest tests/ -v --timeout=120
```

### 검증 기준

- [x] pytest 실행 후 Redis에 `RUNNER_KEY_PREFIX:tc-pytest-*` 키 잔류 0건
- [x] guard fixture가 새 ExecutorService() 인스턴스에도 적용됨
- [x] trigger="user" 직접 전달 시 guard가 차단함
- [x] 운영 visible runner에 영향 없음

---

*상태: 구현완료 | 진행률: 27/27 (100%)*
