# 메인 레포 main 브랜치 보호 + worktree 브랜치 충돌 수정

> 상태: 구현완료
> branch: plan/2026-03-08_worktree-branch-conflict-fix
> worktree: .worktrees/2026-03-08_worktree-branch-conflict-fix
> 우선순위: P0
> 난이도: 낮음
> 요약: 메인 레포에서 main 외 브랜치 체크아웃을 방지하고, worktree 생성 시 브랜치 충돌을 안전하게 처리.
> 진행률: 33/33 (100%)

> 완료일: 2026-03-28
> 아카이브됨

## 현상

1. 메인 레포가 `plan/2026-03-05-logs-follow-runner-detection` 브랜치에 체크아웃된 상태
2. 같은 plan으로 runner 시작 → worktree 생성 실패
3. `git reflog` 확인: `checkout: moving from main to plan/...` — **Claude agent가 메인 레포에서 직접 plan 브랜치를 체크아웃**

## 원인 분석

### 1차: 메인 레포에서 plan 브랜치 체크아웃 (근본 원인)

plan runner가 실행하는 Claude agent가 메인 레포(worktree가 아닌)에서 `git checkout plan/...`을 실행.
worktree 시스템은 각 plan을 격리된 worktree에서 실행하므로 메인 레포는 항상 main이어야 함.

### 2차: worktree_manager.py 방어 부재

`create()`에서 브랜치가 이미 존재+현재 체크아웃 상태일 때:
- `git branch -D` 실패(현재 브랜치 삭제 불가) → 결과 무시 → 재시도 실패

## 수정 계획

### Phase 1: 메인 레포 main 브랜치 강제 보호

plan runner 진입점에서 메인 레포가 main 브랜치가 아니면 자동 복구.

1. - [x] **`ensure_main_branch()` 함수 추가**
   - [x] `scripts/worktree_manager.py`: `WorktreeManager` 클래스 위에 모듈 레벨 함수 `ensure_main_branch(project_root: Path) → None` 추가
     - `subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, encoding="utf-8", cwd=str(project_root))` 로 현재 브랜치 확인
     - `"main"` 이면 즉시 return (no-op)
     - main이 아니면 `logger.warning(f"[WorktreeManager] 메인 레포가 {branch}에 있음, main으로 복귀")` 출력
     - `subprocess.run(["git", "checkout", "main"], capture_output=True, text=True, encoding="utf-8", cwd=str(project_root))` 실행
     - `returncode != 0` 이면 `raise WorktreeError(f"메인 레포를 main으로 복귀 실패 (현재: {branch}): {result.stderr}")` — uncommitted changes 등
   - [x] `scripts/worktree_manager.py`: `create()` line 69 (`base_dir.mkdir` 직전)에 `ensure_main_branch(base_dir.parent)` 호출 추가

2. - [x] **`_do_start_plan_runner()`에서도 사전 검증**
   - [x] `scripts/dev-runner-command-listener.py`: line 1594 (`# worktree 생성 또는 재사용` 주석) 직전에 `ensure_main_branch(PROJECT_ROOT)` 호출 추가
   - [x] `scripts/dev-runner-command-listener.py`: import 블록(line 46 부근)에 `ensure_main_branch` 추가: `from worktree_manager import WorktreeManager, WorktreeError, ensure_main_branch`

### Phase 2: worktree create() 브랜치 충돌 안전 처리

1. - [x] **기존 브랜치 재사용 로직으로 변경** — `scripts/worktree_manager.py` line 80-94
   - [x] `scripts/worktree_manager.py` line 80-88: `git worktree prune` 실행 후, `git branch -D` 대신 먼저 `-b` 없이 `git worktree add {path} {branch}` (기존 브랜치 체크아웃) 시도
   - [x] `scripts/worktree_manager.py` line 89-94: 위 시도 실패 시에만 `git branch -D` 실행 → `del_result.returncode` 확인 → 0이 아니면 `raise WorktreeError(f"브랜치 '{branch}'가 현재 체크아웃 상태여서 삭제 불가. main으로 전환 후 재시도하세요.")` → 삭제 성공 시 `-b` 로 재생성

### Phase 3: encoding='utf-8' 추가 (부수 수정)

1. - [x] **cp949 디코딩 에러 방지** — `scripts/worktree_manager.py` 내 모든 `text=True` 호출
   - [x] `scripts/worktree_manager.py` line 70-72: `create()` 첫 번째 `subprocess.run`에 `encoding="utf-8"` 추가
   - [x] `scripts/worktree_manager.py` line 89-91: `create()` 재시도 `subprocess.run`에 `encoding="utf-8"` 추가
   - [x] `scripts/worktree_manager.py` line 123-125: `remove()` `subprocess.run`에 `encoding="utf-8"` 추가
   - [x] `scripts/worktree_manager.py` line 131: `remove()` `git branch -D` `subprocess.run`에 `encoding="utf-8"` 추가
   - [x] `scripts/worktree_manager.py` line 165-167: `merge_to_main()` `git merge` `subprocess.run`에 `encoding="utf-8"` 추가
   - [x] `scripts/worktree_manager.py` line 192-194: `list_worktrees()` `subprocess.run`에 `encoding="utf-8"` 추가

### Phase 4: merge_to_main() finally 보호

1. - [x] **예외 발생 시에도 main 복귀 보장** — `scripts/worktree_manager.py` `merge_to_main()` (line 154-186)
   - [x] `scripts/worktree_manager.py`: 기존 `try` 블록(line 154)의 `except` 분기(line 185-186)에 `finally:` 추가하여 `subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(project_root))` 실행
   - [x] `scripts/worktree_manager.py`: 기존 line 156 `git checkout main` 은 `ensure_main_branch(project_root)` 호출로 대체 (Phase 1 함수 재사용, 로그 통합)

### Phase T1: 단위 테스트

`tests/dev_runner/test_worktree_manager.py`에 추가:

1. - [x] `test_ensure_main_branch_on_plan_branch()` — R(Right): `tmp_git_repo`에서 plan 브랜치 생성+체크아웃 → `ensure_main_branch()` 호출 → `git rev-parse --abbrev-ref HEAD` == `"main"` 확인
2. - [x] `test_ensure_main_branch_already_main()` — B(Boundary): main 상태에서 호출 → no-op, 예외 없음 확인
3. - [x] `test_ensure_main_branch_uncommitted_changes_raises()` — E(Error): plan 브랜치 + uncommitted 변경 상태 → `ensure_main_branch()` → `WorktreeError` 발생 확인
4. - [x] `test_create_calls_ensure_main_branch()` — R(Right): `create()` 호출 시 내부적으로 `ensure_main_branch` 실행 확인 (plan 브랜치에서 create 호출해도 성공)
5. - [x] `test_create_branch_already_exists_reuse()` — R(Right): 기존 브랜치가 있고 디렉토리 없는 상태에서 `create()` → `-b` 없이 기존 브랜치 체크아웃 성공 확인
6. - [x] `test_merge_to_main_finally_restores_main()` — E(Error): 머지 실패 시에도 메인 레포가 main 브랜치에 있는지 확인

### Phase T2: TC 검증

1. - [x] `pytest tests/dev_runner/test_worktree_manager.py -v` 실행 → 기존 TC + 신규 TC 전체 passed 확인
2. - [x] 실패 TC 수정 후 재실행
3. - [x] 기존 TC 회귀 없음 확인

### Phase T3: E2E 테스트

`tests/dev_runner/test_worktree_e2e.py`에 추가 — 실제 git 조작 기반 (mock 없음):

1. - [x] `test_e2e_5_create_while_on_plan_branch()` — 메인 레포가 plan 브랜치인 상태에서 `create()` 호출 → `ensure_main_branch`가 자동 복구 → worktree 정상 생성 → main 브랜치 복귀 확인
2. - [x] `test_e2e_6_full_lifecycle_after_branch_drift()` — plan 브랜치 체크아웃 상태에서 전체 lifecycle (create → 파일 수정 → 커밋 → merge_to_main → remove) 정상 완료 + 최종 main 브랜치 확인
3. - [x] `test_e2e_7_merge_failure_restores_main()` — 머지 충돌 발생 시에도 메인 레포가 main 브랜치에 있는지 확인 (finally 보호 검증)

### Phase T4: HTTP 통합

`tests/dev_runner/test_worktree_http.py`에 추가 — fakeredis 기반 TestClient:

1. - [x] `test_http_run_with_plan_on_wrong_branch()` — `POST /dev-runner/run` 요청 시 executor_service가 Redis command에 plan_file을 포함하는지 확인 + command 구조에 worktree 관련 필드 존재 검증 (API → command listener 연동 경로의 입구 검증)
2. - [x] `test_http_get_runners_branch_field_populated()` — fakeredis에 runner의 branch 키를 세팅 후 `GET /runners` → 응답의 `branch` 필드가 올바르게 반환되는지 확인 (ensure_main_branch 실행 후 worktree 브랜치 정보가 API까지 전달되는 경로 검증)
