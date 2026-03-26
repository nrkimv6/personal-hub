# dev-runner: Redis 잔존 상태 정리 버튼 + pull-sync 자동 정리

> 작성일: 2026-03-10
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-10_dev-runner-stale-redis-cleanup-button
> worktree: .worktrees/2026-03-10_dev-runner-stale-redis-cleanup-button
> 진행률: 29/29 (100%)
> 요약: plan 파일이 사라졌거나 비활성 상태인 stale runner를 Redis에서 정리하는 API를 신설한다. Sync 버튼 옆에 수동 정리 아이콘 버튼을 추가하고, pull-sync 스킬 실행 시에도 자동으로 호출되도록 통합한다.

> 완료일: 2026-03-26
> 아카이브됨

---

## 개요

plan-runner가 비정상 종료(plan 파일 소실, 조기 return 등)되면 Redis에 runner 상태가 잔존한다.
현재는 수동으로 `python -c`로 직접 Redis 키를 삭제해야 하며, UI에서 정리할 수 없다.

### pull-sync 통합 방향

pull-sync는 Claude 스킬이라 Redis 직접 접근이 불가하지만, **API 호출**은 가능하다.
git pull 후 `POST /runners/cleanup-stale` API를 자동 호출하여 잔존 상태를 정리한다.

### stale 판단 기준

plan 파일 없음 판정 시 **archive 존재 여부를 추가로 확인**한다.

| plan 파일 | archive 파일 | status / 기타 | 판단 | reason |
|-----------|-------------|--------------|------|--------|
| 없음 | **있음** | — | stale (정상 완료) | 아카이브됨, Redis만 정리 |
| 없음 | **없음** | stopped | stale + **버그** | 파일 소실, `reason=file_lost` 플래그 |
| 없음 | **없음** | running + 10분+ | stale + **버그** | 좀비 runner + 파일 소실 |
| 없음 | **없음** | running + 10분 미만 | 유예 | 방금 시작, 파일 생성 중 가능 |
| **있음** | — | — | 정상 | 정리 안 함 |
| `active_runners` PID 죽음 | — | — | stale (기존 로직) | — |

Redis에는 `last_active`/`heartbeat`가 없고 `start_time` + `status`만 있어 이 두 값으로 판단한다.

**archive 경로 계산**: `plan_file` 경로에서 `docs/plan/` → `docs/archive/` 치환.

---

## 기술적 고려사항

- `executor_service.py`의 `_cleanup_stale_runners()`는 `active_runners`만 처리. `recent_runners` 미처리.
- 새 public 메서드 `cleanup_stale_runners()`를 추가하여 양쪽 모두 정리.
- `start_time` 파싱: ISO 8601 형식 (`2026-03-10T15:22:54.715438`) → `datetime.fromisoformat()` 사용.
- API: `POST /api/v1/dev-runner/runners/cleanup-stale` (멱등, 여러 번 호출 안전)
- 프론트: `RunStatusBar.svelte`의 `onSync` 버튼 패턴을 그대로 따라 `onCleanup` prop 추가.
- 아이콘: Trash2 SVG (h-3 w-3), 기존 버튼 스타일 동일.
- pull-sync 스킬: git pull 완료 후 `POST /api/v1/dev-runner/runners/cleanup-stale` 호출 1줄 추가.

---

## TODO

### Phase 1: 백엔드 — cleanup API 신설

1. - [x] **`executor_service.py`에 public cleanup 메서드 추가**
   - - [x] `app/modules/dev_runner/services/executor_service.py`: `async def cleanup_stale_runners()` public 메서드 추가
     - `active_runners` 중 PID 죽은 항목: 기존 `_cleanup_stale_runners()` 내부 로직 재활용
     - `recent_runners` 전체 순회 → 각 runner에 대해:
       - plan_file 키 읽기 → `Path(plan_file).exists()` 확인
       - plan 파일 있으면 → 스킵
       - plan 파일 없으면:
         - archive 경로 계산 (`docs/plan/` → `docs/archive/` 치환)
         - archive에 있으면 → stale(정상완료), `reason="archived"`
         - archive에도 없으면 → stale(버그), `reason="file_lost"`
         - status 확인: `stopped` 이거나 (`running` + start_time 10분 초과)이면 정리
         - `running` + 10분 미만 → 유예 (스킵)
       - 정리 시: per-runner 키 전체 삭제 + `zrem recent_runners`
     - 반환: `{"cleaned_active": int, "cleaned_recent": int, "bugs": int, "total": int}`
       - `bugs`: `reason=file_lost`인 항목 수 (경고 로그 출력)

2. - [x] **`runner.py`에 엔드포인트 추가**
   - - [x] `app/modules/dev_runner/routes/runner.py`: `POST /runners/cleanup-stale` 엔드포인트 추가
     - `executor_service.cleanup_stale_runners()` 호출
     - 반환: `{"success": True, "cleaned": int, "detail": {"cleaned_active": int, "cleaned_recent": int}}`

### Phase 2: 프론트엔드 — 정리 버튼 UI

3. - [x] **API 클라이언트에 cleanupStale 추가**
   - - [x] `frontend/src/lib/api/dev-runner.ts`: `devRunnerRunnerApi`에 `cleanupStale()` 메서드 추가
     - `POST /runners/cleanup-stale` 호출
     - 반환 타입: `{ success: boolean; cleaned: number; detail: { cleaned_active: number; cleaned_recent: number } }`

4. - [x] **RunStatusBar에 onCleanup prop 추가**
   - - [x] `frontend/src/lib/components/dev-runner/RunStatusBar.svelte`: `onCleanup?: () => void` prop 추가
     - Sync 버튼(`onSync`) 바로 다음에 위치
     - 아이콘: Trash2 SVG (h-3 w-3), title="Redis 잔존 상태 정리"
     - 스타일: `h-6 w-6 flex items-center justify-center rounded-md hover:bg-secondary transition-colors` (기존 버튼 동일)

5. - [x] **DevRunnerTab에 handleCleanup 연결**
   - - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: `handleCleanup()` 함수 추가
     - `devRunnerRunnerApi.cleanupStale()` 호출
     - 완료 후 `fetchRunners()` 재조회 + toast 메시지 (`정리 완료: N개 항목 제거`)
     - `RunStatusBar`에 `onCleanup={handleCleanup}` 전달

### Phase 3: pull-sync 스킬 통합

6. - [x] **pull-sync 스킬에 cleanup API 호출 추가**
   - - [x] `D:\work\project\service\wtools\.claude\skills\pull-sync\SKILL.md`: git pull 완료 후 단계에 cleanup 호출 추가
     - monitor-page API 베이스 URL(`http://localhost:8001`) 기준
     - `POST /api/v1/dev-runner/runners/cleanup-stale` 호출 (curl 또는 Bash tool)
     - 응답에서 `cleaned` > 0 이면 결과 리포트에 "Redis 잔존 N개 정리됨" 표시
     - API 실패 시 (서버 미실행 등) 경고만 출력하고 pull-sync 계속 진행

### T1: TC 작성

7. - [x] **cleanup_stale_runners() 단위 테스트 작성**
   - - [x] `tests/dev_runner/test_executor_cleanup.py` 신규 생성
     - - [x] `test_cleanup_stale_archived_plan()` — plan 없음 + archive 있음 → stale 정리 + reason=archived (R)
     - - [x] `test_cleanup_stale_file_lost()` — plan 없음 + archive도 없음 + stopped → stale 정리 + reason=file_lost + bugs=1 (R)
     - - [x] `test_cleanup_stale_running_old_file_lost()` — plan 없음 + archive 없음 + running + 10분+ → 정리 + bugs=1 (R)
     - - [x] `test_cleanup_stale_running_new_skipped()` — plan 없음 + archive 없음 + running + 10분 미만 → 유예 (B)
     - - [x] `test_cleanup_stale_plan_exists_skipped()` — plan 파일 존재 → 정리 안 됨 (B)
     - - [x] `test_cleanup_stale_dead_pid_active()` — active_runners PID 죽음 → 정리 (R)
     - - [x] `test_cleanup_stale_empty_returns_zero()` — 정리 대상 없을 때 0 반환 (E)

### T2: TC 검증

8. - [x] **테스트 실행 및 passed 확인**
   - - [x] `python -m pytest tests/dev_runner/test_executor_cleanup.py -v --timeout=30` → 7 passed
   - - [x] 회귀 확인: `python -m pytest tests/dev_runner/ -v --timeout=30 --ignore=tests/dev_runner/test_executor_cleanup.py`

### T3: 통합 TC

9. - [x] **실제 Redis로 cleanup 동작 확인**
   - - [x] `tests/dev_runner/test_executor_cleanup.py`에 통합 TC 추가:
     - 실제 Redis에 `recent_runners` zset에 더미 runner_id 추가 (status=stopped, plan_file=없는경로)
     - `cleanup_stale_runners()` 직접 호출 → `cleaned_recent >= 1` 확인
     - 테스트 후 더미 키 정리

### T4: E2E

10. - [x] T4 E2E — 스킵: 버튼 클릭 → API 호출 흐름은 T5 HTTP로 커버됨. 별도 E2E 시나리오 없음.

### T5: HTTP 통합

11. - [x] **POST /runners/cleanup-stale HTTP 테스트**
    - - [x] `tests/dev_runner/test_http_runner.py` 또는 관련 HTTP 테스트 파일에 추가:
      - `test_cleanup_stale_endpoint_returns_200()` — 정상 응답 200 + success: true 확인
      - `test_cleanup_stale_endpoint_idempotent()` — 두 번 호출해도 동일한 응답 확인

---

*상태: 구현완료 | 진행률: 29/29 (100%)*
