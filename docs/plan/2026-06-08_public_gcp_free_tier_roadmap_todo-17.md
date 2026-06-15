# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 17

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 17
> 선행조건: ./2026-06-15_cloud-run-poc-design-contract.md + ../archive/2026-06-08_public_gcp_free_tier_roadmap_todo-2.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: Python 변경 시 pytest T1~T5 규칙 적용
> 진행률: 0/27 (0%)
> 요약: 설계 계약서 Option A 기반으로 app/main_cloudrun.py slim entrypoint와 Dockerfile.cloudrun을 작성하고 Cloud Run 배포 command를 문서화한다.

## 배경

`2026-06-15_cloud-run-poc-design-contract.md`에서 확정된 Option A 구현 단계다.

**현재 차단 사항**:
- `app/router_registry.py`: personal-hub에 없음 (monitor-page에만 존재) — `app/main_admin.py` line 88에서 import하여 main_admin.py 기동 불가
- `app/main_cloudrun.py`: 미존재 (이 todo에서 신규 작성)
- `Dockerfile.cloudrun`: 미존재 (이 todo에서 신규 작성)

**확인된 참조처**:
- `app/main_admin.py:88` — `from app.router_registry import register_routers` (기동 blocker)
- `app/core/runtime_fingerprint.py:21` — `"app/router_registry.py"` 경로 참조 (존재 체크)

todo-16 live T4/T5 검증은 이 todo의 배포 완료 후 실행된다.

## TODO

### Phase 0: Worktree 준비

0. - [ ] **worktree 생성 또는 재개**
   - [ ] `impl/gcp-todo-17-cloudrun-impl` 브랜치와 worktree를 생성하거나 기존 것을 재개한다
   - [ ] 이 plan 헤더 `> branch:`/`> worktree:`/`> worktree-owner:`를 생성한 값으로 채운다

### Phase 1: app/main_cloudrun.py 작성

1. - [ ] **slim entrypoint 구현**
   - [ ] `app/main_cloudrun.py` 신규 파일 작성 — FastAPI app, `GET /`, `GET /healthz`
   - [ ] `GET /` → `{"status": "ok", "version": "poc"}` 응답 확인
   - [ ] `GET /healthz` → `{"healthy": True}` 응답 확인
   - [ ] `from app.router_registry` import 없음 확인
   - [ ] `from app.lifespan` import 없음 확인
   - [ ] FastAPI app title `"personal-hub Cloud Run PoC"` 설정 확인

### Phase 2: Dockerfile.cloudrun 작성

2. - [ ] **컨테이너 정의**
   - [ ] `Dockerfile.cloudrun` 신규 파일 작성
   - [ ] uvicorn module path `app.main_cloudrun:app` 확인
   - [ ] `$PORT` 환경변수 사용 (`CMD ["sh", "-c", "uvicorn app.main_cloudrun:app --host 0.0.0.0 --port ${PORT:-8080}"]`)
   - [ ] slim dependency 설치 범위: fastapi, uvicorn만 (DB/Redis/browser 의존 제외)

### Phase 3: Cloud Run 배포 command 문서화

3. - [ ] **배포 절차 기록** (`docs/plan`에 노트로 추가)
   - [ ] service name, region, unauthenticated flag 결정값 기록
   - [ ] min-instances 0 (free-tier) 설정 기록
   - [ ] `gcloud run deploy` 명령 샘플 작성 (실제 실행은 deployment owner)
   - [ ] 배포 완료 URL을 todo-16 선행조건에 기재할 수 있도록 placeholder 남기기

### Phase T1: pytest 단위 TC

4. - [ ] **단위 테스트 작성**
   - [ ] `tests/test_main_cloudrun.py` 신규 작성
   - [ ] `GET /` 200 + `{"status": "ok", "version": "poc"}` assert
   - [ ] `GET /healthz` 200 + `{"healthy": True}` assert
   - [ ] `router_registry`/`lifespan` import 없음 검증 (AST or import smoke)

### Phase T2: local pytest 실행

5. - [ ] **단위 테스트 실행** (worktree cwd에서)
   - [ ] `pytest tests/test_main_cloudrun.py -v` 실행 + 결과 기록

### Phase T3: import smoke

6. - [ ] **import smoke**
   - [ ] `python -c "from app.main_cloudrun import app; print('ok')"` 실행 + 결과 기록

### Phase M: Merge Handoff

> T4/T5: Cloud Run 배포 URL live 검증은 배포 owner 또는 todo-16에서 수행. 이 phase에서는 live URL 호출 금지.

### Phase Z: Post-Merge Cleanup

Z. - [ ] **post-merge 정리**
   - [ ] worktree remove, branch remove, 헤더 meta 제거

### 검증 기준 (RIGHT-BICEP)

- **R**ight: `GET /`와 `GET /healthz`가 pytest T1에서 200 반환.
- **B**oundary: cold start 60초·concurrency 80·min-instances 0 설계 계약서 값 상속.
- **I**nverse: `router_registry`·`lifespan` import 0건 확인.
- **C**ross-check: 선행조건이 todo-2 설계 계약서를 참조.
- **E**rror: `router_registry.py` 미생성 상태에서 `main_cloudrun.py`가 정상 기동됨.
- **P**erformance/cost: min-instances 0 + unauthenticated 접근 free-tier 범위 유지.

---

*진행률: 0/27 (0%)*
