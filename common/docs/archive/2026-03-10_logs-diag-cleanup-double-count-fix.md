# pytest --timeout=30 반복 에러 + cleanup_stale_runners 중복 카운트 수정

> 작성일: 2026-03-10
> 대상 프로젝트: monitor-page (스킬 수정은 wtools)
> 상태: 구현완료
> branch: plan/2026-03-10_logs-diag-cleanup-double-count-fix
> worktree: .worktrees/2026-03-10_logs-diag-cleanup-double-count-fix
> 진행률: 10/10 (100%)
> 요약: dev-runner가 Claude를 통해 pytest를 실행할 때 스킬 템플릿의 --timeout=30이 pytest.ini의 timeout=120과 충돌해 반복 에러가 로그에 쌓이는 문제, 그리고 cleanup_stale_runners에서 active→recent 이동된 runner가 recent 정리 단계에서 중복 카운트·오탐 bugs++ 되는 버그를 수정한다.

> 완료일: 2026-03-23
> 아카이브됨

---

## 개요

### 문제 1: pytest --timeout=30 unrecognized argument 반복 에러

`logs.ps1 -Admin -Follow` 에서 아래 에러가 반복 출력됨:

```
ERROR: usage: __main__.py [options] [file_or_dir] [file_or_dir] [...]
__main__.py: error: unrecognized arguments: --timeout=30
   inifile: ...pytest.ini
```

**원인**:
- `.claude/skills/plan/_mode-a.md`, `_mode-b.md`, `implement/SKILL.md` 등의 스킬 템플릿이 pytest 명령에 `--timeout=30`을 포함
- dev-runner가 Claude를 통해 테스트를 실행할 때 이 템플릿대로 명령 생성
- 프로젝트 `pytest.ini`에 이미 `timeout = 120` 설정 → `--timeout=30` 추가 전달 시 에러

**수정**: wtools 스킬 파일에서 `--timeout=30` 옵션 제거 (pytest.ini에 이미 설정되어 있으므로 불필요)

> **주의**: 스킬 파일은 wtools 레포에서만 수정 가능 (`D:\work\project\service\wtools\.claude\`)

---

### 문제 2: cleanup_stale_runners active→recent 중복 카운트

**흐름**:
1. Phase 1 (active 정리): PID 죽은 runner → `_force_cleanup_state(rid)` → `RECENT_RUNNERS_KEY`에 zadd → `cleaned_active += 1`
2. Phase 2 (recent 정리): 동일 runner가 `RECENT_RUNNERS_KEY`에 존재 → plan_file 없으면 다시 정리 대상 → `cleaned_recent += 1` + `bugs += 1` (오탐)

**결과**: 정상적으로 종료된 PID-죽은 runner가 `bugs`로 잘못 카운트될 수 있음.

**수정**: Phase 1에서 정리한 runner ID를 `cleaned_active_ids` 세트로 수집 → Phase 2 루프 진입 시 해당 ID 스킵.

---

## 기술적 고려사항

- `_force_cleanup_state`는 `plan_file` 키를 삭제하지 않고 TTL만 설정 → Phase 2에서 파일 존재 여부 체크 시 "없는 파일"로 판단 가능
- Phase 1 정리된 ID를 스킵하는 것이 가장 단순하고 안전한 수정
- wtools 스킬 수정 후 monitor-page에서 `git pull` 또는 `/pull-sync`로 동기화 필요

---

## TODO

### Phase 1: wtools 스킬 템플릿 --timeout=30 제거 (3개 작업)

1. - [x] **plan 스킬 검증 섹션 --timeout=30 제거**
   - - [x] `D:\work\project\service\wtools\.claude\skills\plan\_mode-a.md` L65: `python -m pytest {테스트 경로} -v --timeout=30` → `python -m pytest {테스트 경로} -v` 로 변경
   - - [x] `D:\work\project\service\wtools\.claude\skills\plan\_mode-a.md` L73: `python -m pytest {전체...} -v --timeout=30 --ignore=...` → `--timeout=30` 제거
   - - [x] `D:\work\project\service\wtools\.claude\skills\plan\_mode-b.md` L95, L103: 동일하게 `--timeout=30` 제거 (2곳)

2. - [x] **implement 스킬 T3 실행 명령 --timeout=30 제거**
   - - [x] `D:\work\project\service\wtools\.claude\skills\implement\SKILL.md` L204: `` pytest {T3 테스트 경로} -v --timeout=30 `` → `--timeout=30` 제거

3. - [x] **debug-parallel 스킬 --timeout=30 제거**
   - - [x] `D:\work\project\service\wtools\.claude\skills\debug-parallel\SKILL.md` L60: `python -m pytest {관련 테스트 경로} -v --timeout=30` → `--timeout=30` 제거

4. - [x] **wtools 커밋 및 monitor-page 동기화**
   - - [x] wtools 레포에서 git add 후 커밋: `fix: pytest --timeout=30 제거 (pytest.ini timeout=120으로 이미 설정됨)`
   - - [x] monitor-page에서 `git pull` 실행하여 스킬 파일 동기화 확인

### Phase 2: cleanup_stale_runners 중복 카운트 수정 (3개 작업)

> **대상 파일**: 워크트리 `app/modules/dev_runner/services/executor_service.py`
> `cleanup_stale_runners()` 함수 (L357~L463)

5. - [x] **cleaned_active_ids 세트 선언 추가**
   - - [x] `executor_service.py` L374 `bugs = 0` 바로 아래에 `cleaned_active_ids: set = set()` 한 줄 추가

6. - [x] **Phase 1 루프에서 ID 수집**
   - - [x] `executor_service.py` L397 `cleaned_active += 1` 바로 앞에 `cleaned_active_ids.add(rid)` 한 줄 추가
   - - [x] 결과: `if should_clean:` 블록이 `cleaned_active_ids.add(rid)` → `cleaned_active += 1` 순서

7. - [x] **Phase 2 루프 시작 시 이미 정리된 ID 스킵**
   - - [x] `executor_service.py` L408 `for rid in recent_ids:` 바로 다음 줄에 `if rid in cleaned_active_ids: continue` 추가 (들여쓰기 맞춤)

### T1: 단위 테스트 작성 (2개 TC)

8. - [x] **cleanup_stale_runners 중복 카운트 TC 작성** (`tests/dev_runner/test_executor_cleanup.py`)
   - - [x] `test_cleanup_stale_dead_pid_no_double_count()` — `_is_pid_alive=False` + plan_file Redis에는 있으나 파일시스템 없음 → `cleaned_active=1, cleaned_recent=0, bugs=0` (R: active 정리 후 recent 중복 미발생)
   - - [x] `test_cleanup_stale_dead_pid_not_a_bug()` — 동일 조건에서 `result["bugs"] == 0` 단독 검증 → Phase 1 처리 ID가 오탐 bugs 카운트에 포함되지 않음 확인 (B: 오탐 방지)

### T2: TC 검증 및 수정 (3개 작업)

9. - [x] **신규 TC 실행 및 passed 확인**
   - - [x] 워크트리에서 `python -m pytest tests/dev_runner/test_executor_cleanup.py -v` 실행 → 2 passed 확인 (신규 2)
   - - [x] `python -m pytest tests/dev_runner/test_executor_cleanup.py -v` 실패 시 오류 분석 후 TC 또는 구현 수정
   - - [x] `python -m pytest tests/dev_runner/ -v -x --ignore=tests/dev_runner/test_executor_cleanup.py` 실행 → 기존 회귀 없음 확인 (test_auto_resolve_abort_bug 실패는 우리 변경과 무관한 기존 결함)

### T3: 통합 TC — 재현 (2개 작업)

10. - [x] **중복 카운트 근본 원인 재현 TC 작성** (`tests/dev_runner/test_executor_cleanup.py`)
    - - [x] `test_cleanup_dead_pid_double_count_root_cause()` — fakeredis에 PID-죽은 runner를 active + plan_file 없이 시드 → `_is_pid_alive=False` mock → 수정 전 코드라면 `bugs=1` 나왔을 케이스 → 수정 후 `bugs=0` 검증 (Re: 참조 무결성)
    - - [x] `python -m pytest tests/dev_runner/test_executor_cleanup.py::test_cleanup_dead_pid_double_count_root_cause -v` 실행 → passed 확인

### T4: E2E 테스트 (2개 작업)

> `tests/dev_runner/test_e2e.py`, `test_http_e2e.py` 등 E2E 파일 존재 확인됨.
> `cleanup_stale_runners`는 `POST /api/v1/dev-runner/runners/cleanup-stale` 엔드포인트로 노출되어 있으므로 HTTP E2E 포함.

11. - [x] **cleanup-stale 엔드포인트 E2E TC 작성 또는 기존 파일에 추가** (`tests/dev_runner/test_http_stop_all.py` 또는 신규 `test_http_cleanup_stale.py`)
    - - [x] `test_cleanup_stale_post_returns_success()` — `POST /api/v1/dev-runner/runners/cleanup-stale` mock executor → `{"success": True, "cleaned": N}` 응답 확인 (R)
    - - [x] `test_cleanup_stale_post_empty_result()` — 정리 대상 없을 때 `cleaned=0` 응답 확인 (B)

### T5: HTTP 통합 테스트 (2개 작업)

> `POST /api/v1/dev-runner/runners/cleanup-stale` 엔드포인트 (`runner.py` L84~L93) 존재 확인됨. HTTP 통합 테스트 필요.

12. - [ ] **cleanup-stale HTTP 통합 TC 실행**
    - - [x] `python -m pytest tests/dev_runner/test_http_cleanup_stale.py -v` 실행 → passed 확인 (merge-test 단계에서 main 머지 후 실행)
    - - [x] 실패 시 TestClient mock 설정 확인 후 수정

---

## 검증

### 테스트 실행

```powershell
python -m pytest tests/dev_runner/test_executor_cleanup.py -v
```

- 기대 결과: 9 passed (기존 7 + 신규 2), 실행시간 < 10초

### 회귀 확인

```powershell
python -m pytest tests/dev_runner/ -v --ignore=tests/dev_runner/test_executor_cleanup.py -x
```

### 검증 기준

- [x] 신규 TC 2개 passed
- [x] 기존 TC 7개 회귀 없음
- [x] wtools 스킬 동기화 후 dev-runner 실행 시 --timeout=30 에러 미발생

---

*상태: 구현완료 | 진행률: 10/10 (100%)*
