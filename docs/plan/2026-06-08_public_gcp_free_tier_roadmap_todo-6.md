# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 6

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 6
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-5.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: metric spec 문서 검증
> 진행률: 0/6 (0%)
> 요약: Cloud Logging 기반 log metric과 Cloud Monitoring alert 후보를 정의한다.

## TODO

### Phase 1: Metric 후보 정의

1. - [ ] **운영 metric 후보 분류** — SLO 초안
   - [ ] `docs/plan`: API health, worker heartbeat, task failure, queue backlog metric 이름을 정의한다
   - [ ] `docs/plan`: free-tier PoC에서 alert channel을 만들지 않고 threshold만 문서화한다

2. - [ ] **readiness 기준 작성** — local dependency 분리
   - [ ] `docker-compose.yml`: local PostgreSQL/Redis readiness와 Cloud Run demo readiness 차이를 문서화한다
   - [ ] `docs/plan`: synthetic uptime check 대상 endpoint를 하나로 제한한다

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: metric 이름(API health, worker heartbeat, task failure, queue backlog)이 정의되고 todo-5 로그 필드에서 도출 가능하다.
- **B**oundary: free-tier PoC에서 alert channel을 생성하지 않고 threshold만 문서화한다.
- **I**nverse: synthetic uptime check 대상 endpoint가 1개로 제한됨을 역으로 확인한다(다중 생성 금지).
- **C**ross-check: local PostgreSQL/Redis readiness와 Cloud Run demo readiness 차이를 교차 확인한다.
- **E**rror: metric 무수집/누락 시 표시 조건이 있다.
- **P**erformance/cost: GCP 자체 metric은 Always Free 범위이며 alert channel 미생성으로 과금 0.

---

*진행률: 0/6 (0%)*
