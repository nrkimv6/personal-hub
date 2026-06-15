# GCP Cloud Run 구현 todo 누락 — roadmap gap 분석 및 impl todo 등록

> 출처: /reflect에서 자동 생성
> 대상 프로젝트: personal-hub
> 상태: 검토대기
> 진행률: 0/6 (0%)
> 요약: todo-2 설계 계약서가 "별도 todo에서 구현"으로 남긴 `app/main_cloudrun.py` slim entrypoint가 로드맵(todo-3~16) 어디에도 없음. 이 gap을 해소하는 impl todo를 작성하고 등록한다.

## 배경

`2026-06-08_public_gcp_free_tier_roadmap_todo-2.md` (archived)에서 확정된 설계 계약서(`2026-06-15_cloud-run-poc-design-contract.md`)는 다음을 명시한다:

1. **발견된 차단 사항 1**: `app/main_admin.py` line 88의 `from app.router_registry import register_routers` — `app/router_registry.py`가 personal-hub에 없음. 현재 `main_admin.py`로는 Cloud Run 기동 불가.
2. **권장 Option A**: 신규 `app/main_cloudrun.py` slim entrypoint 작성 — lifespan·router_registry 없음, `GET /`와 `GET /healthz`만 노출.
3. **"별도 todo에서 구현"**: 위 slim entrypoint 실제 코드 작성은 이 설계 산출물(todo-2)의 범위 밖이라 명시.

**gap**: todo-3~todo-15 전부 설계 문서 산출물 plan이고, todo-16(live T4/T5)은 이미 배포된 Cloud Run URL 대상 live 검증을 기대한다. 그 사이 단계(구현 → 배포)를 담당하는 todo가 없음.

## TODO

### Phase 1: gap 범위 확정

1. - [ ] **`router_registry.py` 누락 전파 범위 확인**
   - [ ] `app/main_admin.py` 외에 `app/router_registry` import를 사용하는 파일이 있는지 grep으로 확인
   - [ ] 새로운 `app/main_cloudrun.py`가 이 import를 우회하는지 설계 계약서 Option A 기준으로 검증

2. - [ ] **todo-16 의존성 분석**
   - [ ] `2026-06-08_public_gcp_free_tier_roadmap_todo-16.md` 읽고 "Cloud Run read-only/health endpoint 배포 URL live 200" 선행조건을 확인
   - [ ] 구현 todo 없이 todo-16이 실행되면 어떤 blocker가 발생하는지 기록

### Phase 2: 구현 todo 초안 작성 및 등록

3. - [ ] **`app/main_cloudrun.py` 구현 todo 초안 작성**
   - [ ] `2026-06-08_public_gcp_free_tier_roadmap_todo-17.md` (또는 적절한 번호) 신규 생성
   - [ ] 내용: 설계 계약서 Option A 기반 `app/main_cloudrun.py` 작성, `Dockerfile.cloudrun` 작성, Cloud Run 배포 command 문서화
   - [ ] 선행조건: todo-2(설계), pytest T1(단위 테스트) 적용 대상 명시

4. - [ ] **로드맵 TODO.md 등록**
   - [ ] `.worktrees/plans/TODO.md`에 신규 impl todo 링크 추가
   - [ ] 기존 todo-16 선행조건에 신규 impl todo 번호 반영 여부 검토

### Phase M: Merge Handoff

> T1~T3: `app/main_cloudrun.py` 작성이 포함될 경우 pytest 대상. 본 plan은 설계·분석·todo 등록만 수행하므로 T1~T5 해당 없음.
> T4/T5: 실제 Cloud Run 배포 검증은 신규 impl todo 또는 todo-16에서 수행.

### Phase Z: Post-Merge Cleanup

Z. - [ ] **post-merge 정리**
   - [ ] worktree remove, branch remove, 헤더 meta 제거

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

### 검증 기준 (RIGHT-BICEP)

- **R**ight: `GET /` 와 `GET /healthz`가 PostgreSQL/Redis 없이 200 반환.
- **B**oundary: 신규 impl todo가 설계 계약서의 cold start 60초·concurrency 80·min-instances 0 결정값을 상속.
- **I**nverse: `app/router_registry`·`app/lifespan` import가 `main_cloudrun.py`에 없음을 확인.
- **C**ross-check: 신규 impl todo의 선행조건이 todo-2 설계 계약서를 참조.
- **E**rror: `router_registry.py` 미생성 상태에서 `main_cloudrun.py`가 정상 기동됨(독립적).

---

*진행률: 0/6 (0%)*
