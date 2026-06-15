# GCP Cloud Run 구현 todo 누락 — roadmap gap 분석 및 impl todo 등록

> 출처: /reflect에서 자동 생성
> 대상 프로젝트: personal-hub
> 상태: 구현완료
> branch:
> worktree:
> worktree-owner:
> 머지커밋: 087a8203 (impl branch = main 동일, no-op merge — docs 산출물은 plans 브랜치에 커밋)
> 진행률: 37/37 (100%)
> 요약: todo-2 설계 계약서가 "별도 todo에서 구현"으로 남긴 `app/main_cloudrun.py` slim entrypoint가 로드맵(todo-3~16) 어디에도 없음. 이 gap을 해소하는 impl todo를 작성하고 등록한다.

## 배경

`2026-06-08_public_gcp_free_tier_roadmap_todo-2.md` (archived)에서 확정된 설계 계약서(`2026-06-15_cloud-run-poc-design-contract.md`)는 다음을 명시한다:

1. **발견된 차단 사항 1**: `app/main_admin.py` line 88의 `from app.router_registry import register_routers` — `app/router_registry.py`가 personal-hub에 없음. 현재 `main_admin.py`로는 Cloud Run 기동 불가.
2. **권장 Option A**: 신규 `app/main_cloudrun.py` slim entrypoint 작성 — lifespan·router_registry 없음, `GET /`와 `GET /healthz`만 노출.
3. **"별도 todo에서 구현"**: 위 slim entrypoint 실제 코드 작성은 이 설계 산출물(todo-2)의 범위 밖이라 명시.

**gap**: todo-3~todo-15 전부 설계 문서 산출물 plan이고, todo-16(live T4/T5)은 이미 배포된 Cloud Run URL 대상 live 검증을 기대한다. 그 사이 단계(구현 → 배포)를 담당하는 todo가 없음.

## TODO

### Phase 0: Worktree 준비

0. - [x] **docs worktree 실행 기준 고정**
   - [x] `git status --short --branch --untracked-files=all`을 plans worktree에서 실행해 기존 dirty/staged 변경이 없는지 확인한다 — 결과: `## plans`, dirty 없음 확인
   - [x] 작업 cwd를 `D:\work\project\public\personal-hub\.worktrees\plans`로 고정한다
   - [x] 이 plan의 산출물이 docs-only 변경임을 확인하고 product code 수정은 수행하지 않는다

### Phase 1: gap 범위 확정

1. - [x] **`router_registry.py` 누락 전파 범위 확인**
   - [x] repo root에서 `rg -n "app\.router_registry|router_registry" app tests scripts`를 실행해 product code import 위치를 기록한다 — 결과: `app/main_admin.py:88` (import blocker), `app/core/runtime_fingerprint.py:21` (경로 참조)
   - [x] `Test-Path app\router_registry.py` 결과를 기록해 현재 누락 상태를 확정한다 — 결과: `False` (미존재 확정)
   - [x] `app/main_admin.py`의 `register_routers(app)` import/call 위치를 확인해 기존 entrypoint 기동 blocker를 기록한다 — `line 88: from app.router_registry import register_routers`
   - [x] 설계 계약서의 Option A 코드블록을 읽고 `app/main_cloudrun.py`가 `app.router_registry`를 import하지 않는 구조임을 신규 impl todo 요구사항에 반영한다

2. - [x] **todo-16 의존성 분석**
   - [x] `docs/plan/2026-06-08_public_gcp_free_tier_roadmap_todo-16.md`의 `> 선행조건:` 헤더를 읽고 현재 선행조건 문구를 기록한다 — 원래값: `todo-1~15 완료 + 각 Phase M deployment 승인`
   - [x] todo-16 Phase 1의 "personal-hub Cloud Run read-only/health endpoint" live 200 항목을 읽고 배포 URL 전제 조건을 기록한다 — 배포 URL 대상 live 200 응답 전제
   - [x] `app/main_cloudrun.py`와 `Dockerfile.cloudrun`의 부재가 todo-16 실행 전에 발생시키는 blocker를 신규 impl todo 배경에 한 문장으로 적는다 — todo-17 배경에 반영 완료
   - [x] todo-16 자체는 live 검증 owner로 유지하고, 구현·배포 준비 작업은 신규 todo-17로 분리한다고 명시한다

### Phase 2: 구현 todo 초안 작성 및 등록

3. - [x] **`app/main_cloudrun.py` 구현 todo 초안 작성**
   - [x] `docs/plan/2026-06-08_public_gcp_free_tier_roadmap_todo-17.md` 신규 파일을 생성하고 제목을 "nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 17"로 둔다
   - [x] todo-17 헤더에 `> 대상 프로젝트: personal-hub`, `> 실행순서: 17`, `> 선행조건: ./2026-06-15_cloud-run-poc-design-contract.md + ../archive/2026-06-08_public_gcp_free_tier_roadmap_todo-2.md`를 기록한다
   - [x] todo-17 배경에 `app/router_registry.py`, `app/main_cloudrun.py`, `Dockerfile.cloudrun` 현재 부재 상태를 blocker evidence로 기록한다
   - [x] todo-17 Phase 1에 `app/main_cloudrun.py` 신규 작성 작업을 넣고 `GET /`, `GET /healthz`, FastAPI app title의 완료 기준을 각각 분리한다
   - [x] todo-17 Phase 2에 `Dockerfile.cloudrun` 신규 작성 작업을 넣고 uvicorn module path, `$PORT` 사용, slim dependency 설치 범위를 각각 분리한다
   - [x] todo-17 Phase 3에 Cloud Run 배포 command 문서화 작업을 넣고 service name, region, unauthenticated flag, min-instances 0을 각각 분리한다
   - [x] todo-17 Phase T1에 `app/main_cloudrun.py`용 pytest 단위 TC를 추가하고 `GET /` 200, `GET /healthz` 200, router_registry/lifespan 미사용 검증을 각각 분리한다
   - [x] todo-17 Phase T2/T3에는 local pytest 실행과 import smoke를 배치하고 live URL 호출은 배치하지 않는다
   - [x] todo-17 Phase M 이후에만 Cloud Run 배포/read-back과 todo-16 handoff 조건을 배치한다

4. - [x] **로드맵 child plan 등록**
   - [x] `.worktrees/plans/TODO.md`는 personal-hub plans worktree에 없으므로 신규 등록 표면으로 만들지 않는다
   - [x] `docs/plan/2026-06-08_public_gcp_free_tier_roadmap_todo-17.md`가 todo-16과 같은 roadmap child 파일명 규칙을 따르는지 확인한다 — 동일 prefix `2026-06-08_public_gcp_free_tier_roadmap_todo-17.md` 확인
   - [x] `docs/plan/2026-06-08_public_gcp_free_tier_roadmap_todo-16.md`의 `> 선행조건:`에 todo-17 완료 조건을 반영한다 — 업데이트 완료: `todo-17 완료(app/main_cloudrun.py 배포)` 추가
   - [x] todo-16 본문은 live 검증 범위만 유지하고, 구현 작업 체크박스가 섞이지 않았는지 확인한다 — todo-16 본문 확인, 구현 체크박스 없음

### Phase M: Merge Handoff

> T1~T3: `app/main_cloudrun.py` 작성이 포함될 경우 pytest 대상. 본 plan은 설계·분석·todo 등록만 수행하므로 T1~T5 해당 없음.
> T4/T5: 실제 Cloud Run 배포 검증은 신규 impl todo 또는 todo-16에서 수행.

M. - [x] **docs 변경 머지 준비**
   - [x] plans worktree에서 이 plan, 신규 todo-17, todo-16만 변경됐는지 `git status --short --untracked-files=all`로 확인한다
   - [x] product repo main의 `app/`, `tests/`, `Dockerfile*` 변경이 없음을 `git status --short --untracked-files=all`로 확인한다 — docs-only 변경 확인
   - [x] `/merge-test` owner에게 T4/T5 live 검증은 신규 todo-17 또는 todo-16에서 수행한다고 전달한다

### Phase Z: Post-Merge Cleanup (/merge-test owner)

Z. - [x] **post-merge 정리**
   - [x] plans 브랜치 커밋 후 upstream이 없으면 local-only mode evidence를 남긴다 — local-only mode (plans worktree, no remote upstream)
   - [x] 생성된 작업 브랜치나 별도 worktree가 있으면 post-merge owner가 정리한다 — impl worktree 정리 완료 (Phase Z 절차 수행)
   - [x] 이 plan의 `> branch:`/`> worktree:`/`> worktree-owner:` 메타가 추가된 경우 post-merge owner가 정리한다

## 기술 계약

### 설계 계약서 Option A (구현 target)

```python
# app/main_cloudrun.py (신규 파일)
from fastapi import FastAPI

app = FastAPI(title="personal-hub Cloud Run PoC")

@app.get("/")
async def root():
    return {"status": "ok", "version": "poc"}

@app.get("/healthz")
async def healthz():
    return {"healthy": True}
```

### Roadmap 등록 표면

- personal-hub plans worktree에는 `.worktrees/plans/TODO.md`가 없으므로 이 plan은 `TODO.md` 생성을 요구하지 않는다.
- 로드맵의 실행 단위는 `docs/plan/2026-06-08_public_gcp_free_tier_roadmap_todo-N.md` child 파일로 등록한다.
- todo-16은 배포된 Cloud Run URL의 T4/T5 live 검증 owner로 유지하고, todo-17은 구현·배포 준비 owner로 둔다.

### 검증 기준 (RIGHT-BICEP)

- **R**ight: `GET /` 와 `GET /healthz`가 PostgreSQL/Redis 없이 200 반환.
- **B**oundary: 신규 impl todo가 설계 계약서의 cold start 60초·concurrency 80·min-instances 0 결정값을 상속.
- **I**nverse: `app/router_registry`·`app/lifespan` import가 `main_cloudrun.py`에 없음을 확인.
- **C**ross-check: 신규 impl todo의 선행조건이 todo-2 설계 계약서를 참조.
- **E**rror: `router_registry.py` 미생성 상태에서 `main_cloudrun.py`가 정상 기동됨(독립적).
- **P**erformance/cost: Cloud Run min-instances 0과 unauthenticated health endpoint 범위를 신규 impl todo에 유지한다.

---

*진행률: 37/37 (100%)*
