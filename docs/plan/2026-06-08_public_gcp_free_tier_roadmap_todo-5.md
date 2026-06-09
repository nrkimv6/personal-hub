# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 5

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 5
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: Python 변경 시 pytest T1~T5 규칙 적용
> 진행률: 0/6 (0%)
> 요약: FastAPI/worker 로그를 Cloud Logging으로 보낼 구조화 로그 계약을 설계한다.

## TODO

### Phase 1: Logging Contract

1. - [ ] **로그 필드 표준화 후보 확인** — JSON log 중심
   - [ ] `app/core/config.py`: 현재 logging 설정과 formatter를 확인한다
   - [ ] `app/utils/async_logger.py`: worker/file logger와 Cloud Logging adapter 분리 가능성을 확인한다

2. - [ ] **Cloud Logging adapter 범위 작성** — demo 전용
   - [ ] `docs/plan`: `severity`, `module`, `run_id`, `request_id`, `duration_ms` 필드 계약을 작성한다
   - [ ] `docs/plan`: secret/token/URL query logging 금지 조건을 작성한다

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: `severity`, `module`, `run_id`, `request_id`, `duration_ms` 필드 계약이 정확히 정의된다.
- **B**oundary: 월 로그 ingestion이 free-tier(50GB/월) 내다.
- **I**nverse: secret/token/URL query string이 로그에 0건 기록됨을 역검증한다.
- **C**ross-check: 현재 formatter 출력과 Cloud Logging adapter 필드 매핑을 교차 확인한다.
- **E**rror: 금지 필드(secret/token/URL query) 로깅 시 마스킹 또는 차단한다.
- **P**erformance/cost: 로그량 상한과 sampling 기준으로 50GB/월 초과를 방지한다.

---

*진행률: 0/6 (0%)*
