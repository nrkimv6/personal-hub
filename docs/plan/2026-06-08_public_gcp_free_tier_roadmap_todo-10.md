# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 10

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 10
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-2.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: scheduler spec 문서 검증
> 진행률: 0/7 (0%)
> 요약: nightly report/export/cleanup demo job을 Cloud Scheduler free-tier 범위로 설계한다.

## TODO

### Phase 1: Scheduler Job

1. - [ ] **job 후보 축소** — 하루 1회 demo
   - [ ] `app/worker/schedulers`: 기존 scheduler 중 public demo 가능한 job 후보를 확인한다
   - [ ] `app/modules/reports`: nightly report/export endpoint 후보를 확인한다

2. - [ ] **Cloud Scheduler 계약 작성** — 3 jobs free-tier 제한
   - [ ] `docs/plan`: scheduler job은 최대 3개까지로 제한한다고 명시한다
   - [ ] `docs/plan`: auth header, timeout, retry policy 후보를 기록한다
   - [ ] `docs/plan`: Cloud Scheduler는 옵션 플래그(`ENABLE_CLOUD_SCHEDULER`, 기본값 `false`)로 gate하고, 기본 disable·명시적 opt-in 시에만 활성화하는 기준을 작성한다 (계정당 job 3개 초과 시 과금)

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: nightly report/export/cleanup demo job 후보가 정의되고 todo-2 Cloud Run endpoint를 호출한다.
- **B**oundary: scheduler job이 계정당 최대 3개 경계를 넘지 않는다.
- **I**nverse: 3개 초과 job 생성을 금지하는 역조건이 있다.
- **C**ross-check: 기존 worker scheduler와 public demo job 후보를 교차 확인한다.
- **E**rror: auth header/timeout/retry policy 실패 시 처리 기준이 있다.
- **P**erformance/cost: `ENABLE_CLOUD_SCHEDULER=false` 기본값에서 생성 job 0개 → 과금 0.

---

*진행률: 0/7 (0%)*
