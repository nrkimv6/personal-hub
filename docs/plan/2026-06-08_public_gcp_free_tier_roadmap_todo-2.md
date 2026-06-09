# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 2

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 2
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: Python 변경 시 pytest T1~T5 규칙 적용
> 진행률: 0/7 (0%)
> 요약: 전체 앱 이전이 아니라 read-only/health FastAPI endpoint만 Cloud Run PoC로 분리한다.

## TODO

### Phase 1: Cloud Run 대상 축소

1. - [ ] **entrypoint 후보 확인** — 최소 API surface 선택
   - [ ] `app/main_admin.py`: Cloud Run demo entrypoint로 가능한 FastAPI app 객체를 확인한다
   - [ ] `app/core/config.py`: Cloud Run에서 필요한 env key와 local-only key를 분리한다
   - [ ] `docker-compose.yml`: PostgreSQL/Redis 의존이 없는 health/read-only route 후보를 표시한다

2. - [ ] **Cloud Run PoC 계약 작성** — 운영 이전과 분리
   - [ ] `docs/plan`: full app migration 금지와 read-only demo 범위를 명시한다
   - [ ] `docs/plan`: cold start, timeout, concurrency, unauthenticated access 여부를 결정 항목으로 둔다

### Phase M: Merge Handoff

> live Cloud Run 배포 검증은 `/merge-test` 이후 또는 별도 deployment owner에서만 수행한다.

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: 선택된 read-only/health route 집합이 PostgreSQL/Redis 의존 없이 200을 반환한다.
- **B**oundary: cold start, timeout, concurrency 상한값이 명시되고 Cloud Run free-tier 한도 내다.
- **I**nverse: full-app migration이 범위에서 제외됨을 역으로 확인한다(쓰기/DB-필요 route 미포함).
- **C**ross-check: `docker-compose.yml` 의존성과 선택 route 의존성을 교차 확인한다 — 선택 route는 무의존 후보 표에 있어야 한다.
- **E**rror: DB가 필요한 route 호출 시 503 또는 명시적 에러를 반환한다(빈 데이터 위장 금지).
- **P**erformance/cost: unauthenticated 접근 여부 결정값을 기록하고, 월 요청 수가 free-tier(200만/월) 내다.

---

*진행률: 0/7 (0%)*
