# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 8

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 8
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: event contract 문서 검증
> 진행률: 0/6 (0%)
> 요약: Redis Pub/Sub와 별도로 GCP Pub/Sub event contract를 public demo 형태로 설계한다.

## TODO

### Phase 1: Event Contract

1. - [ ] **topic 후보 분리** — worker event 중심
   - [ ] `app/worker`: task lifecycle event 후보를 확인한다
   - [ ] `app/modules/dev_runner`: log stream event와 public demo event의 차이를 문서화한다

2. - [ ] **Pub/Sub schema 작성** — minimal message
   - [ ] `docs/plan`: `event_id`, `event_type`, `source`, `status`, `created_at` message schema를 작성한다
   - [ ] `docs/plan`: payload에 raw prompt, URL token, credential을 넣지 않는 금지 조건을 작성한다

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: `event_id`, `event_type`, `source`, `status`, `created_at` message schema가 정확히 정의된다.
- **B**oundary: 월 메시지량이 free-tier(10GB/월) 내다.
- **I**nverse: payload에 raw prompt, URL token, credential이 0건임을 역검증한다.
- **C**ross-check: worker task lifecycle event 후보와 public demo event 차이를 교차 확인한다.
- **E**rror: 금지 payload 필드가 들어오면 publish를 차단한다.
- **P**erformance/cost: 메시지량 상한으로 10GB/월 초과를 방지한다(Always Free 범위).

---

*진행률: 0/6 (0%)*
