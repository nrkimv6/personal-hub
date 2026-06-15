# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 2

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 2
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch: impl/gcp-todo-2-cloud-run-poc
> worktree: D:\work\project\public\personal-hub\.worktrees\impl-gcp-todo-2-cloud-run-poc
> worktree-owner: claude-sonnet-4-6
> 테스트명령: Python 변경 시 pytest T1~T5 규칙 적용
> 상태: 구현중
> 진행률: 0/15 (0%)
> 요약: 전체 앱 이전이 아니라 read-only/health FastAPI endpoint만 Cloud Run PoC로 분리한다.

## TODO

### Phase 0: Worktree 준비 (/implement 진입 게이트)

0. - [ ] **worktree 생성 또는 재개** — 산출물은 `docs/plan` 설계 문서이므로 plans 워크트리 기준
   - [ ] `impl/gcp-todo-2-cloud-run-poc` 브랜치와 worktree를 생성하거나 기존 것을 재개한다
   - [ ] 이 plan 헤더 `> branch:`/`> worktree:`/`> worktree-owner:`를 생성한 값으로 채운다
   - [ ] worktree cwd를 고정한다

### Phase 1: Cloud Run 대상 축소 (설계·문서화)

1. - [ ] **entrypoint 후보 확인** — 최소 API surface 선택 (코드 수정 없음, read-only 분석)
   - [ ] `app/main_admin.py`: Cloud Run demo entrypoint 후보 FastAPI app 객체(`app`, line 24)를 확인하고 mount된 라우터 목록을 추출한다
   - [ ] `app/core/config.py`: 실제 `BaseSettings`(pydantic_settings) 정의처임을 확인하고(`app/config.py`는 re-export shim), Cloud Run 필요 env key와 local-only key(`DATABASE_URL`, `REDIS` 등)를 분류·문서화한다
   - [ ] `docker-compose.yml`: PostgreSQL/Redis 의존이 없는 health/read-only route 후보를 식별해 무의존 후보 표로 정리한다

2. - [ ] **Cloud Run PoC 계약 작성** — 운영 이전과 분리 (`docs/plan` 산출물)
   - [ ] `docs/plan`: full app migration 금지와 read-only demo 범위를 명시한다
   - [ ] `docs/plan`: cold start, timeout, concurrency, unauthenticated access 여부를 결정 항목으로 명시 기록한다
   - [ ] `docs/plan`: Phase 1에서 식별한 무의존 route 표를 PoC 대상 route 집합으로 고정한다

### Phase M: Merge Handoff

> live Cloud Run 배포 검증과 선택 route의 실제 200/503 응답 확인(검증 기준 R/E)은 `/merge-test` 이후 또는 별도 deployment owner에서만 수행한다. worktree 단계에서 배포/live 호출을 계획하지 않는다.

> T1~T5 해당 없음: 이 plan은 Python 소스를 수정하지 않고 `app/` 코드를 read-only로 분석해 `docs/plan` 설계 계약 문서를 산출한다. 코드 변경 산출물이 없으므로 pytest 5-Phase 대상이 아니다. (tests/ 하위에 e2e/http 파일은 존재하나 본 plan의 변경 대상이 아님)

### Phase Z: Post-Merge Cleanup (/merge-test owner)

Z. - [ ] **post-merge 정리**
   - [ ] main merge 시도 + (필요 시) root dirty stash/apply
   - [ ] worktree remove, branch remove, 헤더 meta(`> branch:`/`> worktree:`/`> worktree-owner:`) 제거

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: 선택된 read-only/health route 집합이 PostgreSQL/Redis 의존 없이 200을 반환한다.
- **B**oundary: cold start, timeout, concurrency 상한값이 명시되고 Cloud Run free-tier 한도 내다.
- **I**nverse: full-app migration이 범위에서 제외됨을 역으로 확인한다(쓰기/DB-필요 route 미포함).
- **C**ross-check: `docker-compose.yml` 의존성과 선택 route 의존성을 교차 확인한다 — 선택 route는 무의존 후보 표에 있어야 한다.
- **E**rror: DB가 필요한 route 호출 시 503 또는 명시적 에러를 반환한다(빈 데이터 위장 금지).
- **P**erformance/cost: unauthenticated 접근 여부 결정값을 기록하고, 월 요청 수가 free-tier(200만/월) 내다.

---

*진행률: 0/15 (0%)*
