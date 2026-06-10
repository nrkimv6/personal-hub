# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 4

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 4
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-3.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: dashboard spec 문서 검증
> 진행률: 0/6 (0%)
> 요약: BigQuery synthetic dataset 위에 Looker Studio public demo dashboard를 설계한다.

## TODO

### Phase 1: Dashboard Spec

1. - [ ] **dashboard page 정의** — 분석 목적 분리
   - [ ] `docs/plan`: worker health, event volume, error rate, duration distribution chart를 정의한다
   - [ ] `docs/plan`: personal 운영 데이터 없이 synthetic/sample data만 사용한다고 명시한다

2. - [ ] **Looker 연결 기준 작성** — 공개 공유 제한
   - [ ] `docs/plan`: Looker Studio data source 권한과 공개 범위를 기록한다
   - [ ] `docs/plan`: row-level 민감정보가 들어오면 dashboard publish 금지 조건을 둔다

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: 정의된 차트(worker health, event volume, error rate, duration distribution)가 BigQuery 필드와 1:1로 매핑된다.
- **B**oundary: synthetic/sample data만 사용하고 personal 운영 row는 0건이다.
- **I**nverse: row-level 민감정보가 유입되면 dashboard publish를 금지하는 역조건이 있다.
- **C**ross-check: Looker data source 권한/공개 범위와 민감정보 부재를 교차 확인한다.
- **E**rror: 민감 row 감지 시 dashboard publish를 차단한다.
- **P**erformance/cost: Looker Studio는 무료 제품이라 과금 N/A — 단 연결된 BigQuery 쿼리량은 todo-3 free-tier 상한을 상속한다.

---

*진행률: 0/6 (0%)*
