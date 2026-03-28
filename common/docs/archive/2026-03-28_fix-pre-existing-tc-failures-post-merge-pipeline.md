# test_post_merge_pipeline.py: pre-existing TC 3개 실패 수정

> 작성일: 2026-03-28
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-28_fix-pre-existing-tc-failures-post-merge-pipeline
> worktree: .worktrees/2026-03-28_fix-pre-existing-tc-failures-post-merge-pipeline
> 우선순위: P1
> 난이도: 낮음
> 진행률: 14/14 (100%)
> 요약: `test_post_merge_pipeline.py`에 main에서도 실패하는 pre-existing TC 3개가 있음. (1) `RUNNER_KEY_SUFFIXES`에 `restart_after_merge`가 실제로 존재하는데 "제거됨" 검증, (2) `subprocess.run` mock이 git rev-parse도 인터셉트하여 post-merge 호출 횟수 불일치, (3) exit_code=1 시 `_launch_general_merge_resolver_process`가 실제 Popen 실행 → merged 전이. TC 또는 코드를 현실에 맞게 정렬.
> 출처: /review에서 자동 생성

> 완료일: 2026-03-29
> 아카이브됨

---

## 배경

`/implement fix-post-merge-test-failed-no-retry` 중 T2 단계에서 3개 TC가 main에서도 동일하게 실패함을 확인하고 "pre-existing failure"로 분류하여 통과시켰다.

## 실패 TC 목록

### TC1: `test_restart_after_merge_not_in_runner_key_suffixes_R`

**현재 코드**: `RUNNER_KEY_SUFFIXES`(라인 73)에 `restart_after_merge`가 실제로 존재하며 라인 1334, 1380에서 실제 사용됨.
**TC 검증 내용**: `restart_after_merge`가 `RUNNER_KEY_SUFFIXES`에 없어야 한다고 검증 → **코드-테스트 불일치**.
**수정 방향**: TC 자체가 outdated — `restart_after_merge`는 여전히 필요하므로 TC를 삭제하거나 "존재함"으로 수정.

### TC2: `test_do_retry_merge_calls_plan_runner_subprocess_R`

**현재 코드**: `_do_retry_merge` → `_execute_merge_with_lock` 내부에서 `git rev-parse --abbrev-ref HEAD`(현재 브랜치 확인용)를 `subprocess.run`으로 호출. 따라서 `subprocess.run`이 **2번** 호출됨.
**TC 검증 내용**: `mock_run.assert_called_once()` → 1회만 호출됐다고 검증 → **실패**.
**수정 방향**: `assert_called_once()` → `assert_any_call(...)` 또는 호출 횟수를 2로 수정. 또는 git 명령 호출을 별도 함수로 분리하여 mock 범위를 좁힘.

### TC3: `test_do_inline_merge_subprocess_exit1_sets_error_E`

**현재 코드**: exit_code=1(else 분기)에서 `_launch_general_merge_resolver_process` 호출 → 내부에서 `_run_subprocess_streaming` → `subprocess.Popen` 실행. `subprocess.run`만 mock하면 Popen은 실제 실행 → plan-runner가 우연히 exit code 0 반환 시 merged 전이.
**TC 검증 내용**: `"merged" not in status_values` → 실제 Popen이 성공 시 merged가 들어와 **실패**.
**수정 방향**: `_launch_general_merge_resolver_process`를 patch하거나 `subprocess.Popen`도 mock.

## TODO

### Phase 1: TC3 수정 (exit_code=1 테스트)

1. - [x] `tests/dev_runner/test_post_merge_pipeline.py`: `test_do_inline_merge_subprocess_exit1_sets_error_E` 수정
   - [x] `_launch_general_merge_resolver_process`를 `patch("_dr_merge._launch_general_merge_resolver_process", ...)` 으로 mock 추가

### Phase 2: TC2 수정 (subprocess.run 호출 횟수)

2. - [x] `tests/dev_runner/test_post_merge_pipeline.py`: `test_do_retry_merge_calls_plan_runner_subprocess_R` 수정
   - [x] `assert_called_once()` → `assert_called()` + plan_runner+post-merge 인자를 포함한 호출 필터 검증으로 교체

### Phase 3: TC1 수정 (RUNNER_KEY_SUFFIXES 검증)

3. - [x] `tests/dev_runner/test_post_merge_pipeline.py`: `test_restart_after_merge_not_in_runner_key_suffixes_R` 삭제
   - [x] `restart_after_merge`는 코드에서 실제로 사용 중이므로 TC를 삭제 (outdated 검증)

### Phase T1: 수정 후 TC 전체 실행

4. - [x] `python -m pytest tests/dev_runner/test_post_merge_pipeline.py -v` → 대상 3개 TC 모두 passed. 나머지 6개 실패는 main에서도 동일 (pre-existing)
5. - [x] 기존 통과 TC regression 없음 확인 (main 14 passed → worktree 14 passed)

### Phase T2: TC 검증 및 수정

6. - [x] 수정된 3개 TC가 올바른 동작을 검증하는지 리뷰
   - [x] TC2: `assert_called()` + plan_runner+post-merge 필터 → 실제 의도(post-merge subprocess 호출) 커버 확인
   - [x] TC3: `_dr_merge._launch_general_merge_resolver_process` patch → exit1에서 general resolver 실행 안 되어 merged 전이 방지 확인
   - [x] TC1: 삭제 — `restart_after_merge`는 코드에서 실제 사용 중(라인 1334, 1380)이므로 올바른 삭제

### Phase T4: E2E 테스트

7. - [x] (스킵) — 이 plan은 테스트 파일만 수정. 실제 코드 로직 변경 없음. E2E 테스트 대상 없음.

### Phase T5: HTTP 통합 테스트

8. - [x] (스킵) — 테스트 파일만 수정. API 엔드포인트 변경 없음. HTTP 통합 테스트 대상 없음.

---

*상태: 구현완료 | 진행률: 14/14 (100%)*
