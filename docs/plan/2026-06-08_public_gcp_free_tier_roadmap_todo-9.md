# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 9

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 9
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-8.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: Python 변경 시 pytest T1~T5 규칙 적용
> 진행률: 0/6 (0%)
> 요약: crawl/report/classification 작업을 Cloud Tasks idempotent job 모델로 설계한다.

## TODO

### Phase 1: Task Model

1. - [ ] **idempotency 후보 확인** — 중복 실행 방지
   - [ ] `app/worker`: 작업 식별자로 쓸 수 있는 run/task id 후보를 확인한다
   - [ ] `app/models`: task status 저장 모델과 Cloud Tasks retry 모델 충돌 여부를 확인한다

2. - [ ] **Cloud Tasks 계약 작성** — accepted/status/result 분리
   - [ ] `docs/plan`: task name, dedup key, retry count, deadline 필드를 정의한다
   - [ ] `docs/plan`: long-running job은 HTTP 요청에서 결과를 기다리지 않는다고 명시한다

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: `task_name`, `dedup_key`, `retry_count`, `deadline` 필드가 정의된다.
- **B**oundary: 월 작업 수가 free-tier(100만 operations/월) 내다.
- **I**nverse: long-running job이 HTTP 요청에서 결과를 기다리지 않음을 역으로 확인한다(accepted/status/result 분리).
- **C**ross-check: 기존 task status 저장 모델과 Cloud Tasks retry 모델의 충돌 여부를 교차 확인한다.
- **E**rror: dedup key 기반으로 중복 실행(idempotency 깨짐)을 방지한다.
- **P**erformance/cost: 작업량 상한으로 100만/월 초과를 방지한다(Always Free 범위).

---

*진행률: 0/6 (0%)*
