# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 3

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 3
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: schema 문서 검증
> 진행률: 0/8 (0%)
> 요약: 운영 이벤트를 BigQuery로 보낼 수 있도록 개인정보 없는 synthetic schema를 정의한다.

## TODO

### Phase 1: Export Schema 후보 선정

1. - [ ] **event source 후보 조사** — 민감정보 제외
   - [ ] `app/models`: monitoring event, worker run, report model 중 export 가능 필드를 분류한다
   - [ ] `app/modules`: LLM request, proxy usage, worker status 중 synthetic event로 대체 가능한 필드를 분류한다

2. - [ ] **BigQuery schema 초안 작성** — demo dataset 기준
   - [ ] `docs/plan`: `event_time`, `event_type`, `module`, `status`, `duration_ms` 중심의 table schema를 작성한다
   - [ ] `docs/plan`: memo body, URL token, account id 같은 금지 필드 목록을 작성한다

### Phase 2: 완료 기준

3. - [ ] **free-tier guard 기록** — 비용 상한
   - [ ] `docs/plan`: 월 저장/쿼리 제한과 sample row volume 상한을 명시한다

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: 테이블 스키마가 `event_time`, `event_type`, `module`, `status`, `duration_ms`를 정확한 타입으로 정의한다.
- **B**oundary: 월 저장/쿼리 제한과 sample row volume 상한이 명시된다.
- **I**nverse: 금지 필드(memo body, URL token, account id)가 스키마에 0건 존재함을 역검증한다.
- **C**ross-check: export 가능 필드 집합 ∩ 금지 필드 집합 = ∅ 를 교차검증한다.
- **E**rror: 금지 필드가 export row에 들어오면 export를 차단하는 조건이 있다.
- **P**erformance/cost: free-tier(저장 10GB, 쿼리 1TB/월) 초과 방지 기준이 있다.

---

*진행률: 0/8 (0%)*
