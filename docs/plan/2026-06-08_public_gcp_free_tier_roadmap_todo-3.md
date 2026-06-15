# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 3

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 3
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch: impl/gcp-todo-3-bigquery-schema
> worktree: .worktrees/impl/gcp-todo-3-bigquery-schema
> worktree-owner: D:\work\project\public\personal-hub\.worktrees\impl\gcp-todo-3-bigquery-schema
> 상태: 구현중
> 테스트명령: schema 문서 검증
> 진행률: 0/17 (0%) — 구현중
> 요약: 운영 이벤트를 BigQuery로 보낼 수 있도록 개인정보 없는 synthetic schema를 정의한다.

## TODO

### Phase 0: Worktree 준비 (/implement 진입 게이트)

0. - [ ] **worktree 생성 또는 재개** — 산출물은 plans worktree `docs/plan/bigquery-schema-design.md`
   - [ ] `git worktree add .worktrees/impl/gcp-todo-3-bigquery-schema -b impl/gcp-todo-3-bigquery-schema` 실행
   - [ ] 이 plan 헤더 `> branch: impl/gcp-todo-3-bigquery-schema` / `> worktree: .worktrees/impl/gcp-todo-3-bigquery-schema` / `> worktree-owner: <절대경로>` 기록
   - [ ] 산출물 경로 확정: plans worktree 기준 `docs/plan/bigquery-schema-design.md` 신규 작성 예정

### Phase 1: Export Schema 후보 선정 (설계·문서화)

1. - [ ] **Group A — 직접 export 후보 필드 분류** (코드 수정 없음, read-only 분석)
   - [ ] `app/models/monitoring_event.py` 읽기 → export 가능: `timestamp`(→`event_time`), `event_type`, `status`; 금지: `slots_info`(JSON 슬롯 상세)
   - [ ] `app/models/scheduled_task_log.py` 읽기 → export 가능: `task_name`(→`module`), `started_at`(→`event_time`), `status`, `duration_seconds`(×1000→`duration_ms`); 금지: `error_message`, `details`(JSON)
   - [ ] `app/models/test_run.py` 읽기 → export 가능: `started_at`(→`event_time`), `status`, `duration_seconds`(→`duration_ms`); 금지: 없음
   - [ ] `app/modules/reports/` 구조 확인 → report event synthetic 후보 여부 판단

2. - [ ] **Group B — synthetic 대체 후보 필드 분류**
   - [ ] `app/models/error_log.py` 읽기 → export 가능: `source`(→`module`), `severity`, `error_type`; 금지: `message`, `traceback`, `context`(account_id·url 포함)
   - [ ] `app/models/instagram_worker_status.py` 읽기 → export 가능: `current_state`; 금지: `worker_id`(UUID)
   - [ ] `app/models/proxy_usage.py` 읽기 → export 가능: FK 제외 집계 필드; 금지: 개인 식별 FK
   - [ ] `app/models/request_log.py` 읽기 → export 가능 여부 판단; URL/body는 금지 후보로 분류

3. - [ ] **BigQuery schema 초안 작성** (`docs/plan/bigquery-schema-design.md` 신규 작성)
   - [ ] 핵심 5컬럼 table schema 정의: `event_time TIMESTAMP`, `event_type STRING`, `module STRING`, `status STRING`, `duration_ms INTEGER`
   - [ ] 선택 2컬럼 추가: `severity STRING NULLABLE`, `error_type STRING NULLABLE`
   - [ ] `event_type` 허용값 열거: `check`, `slot_detected`, `slot_booked`, `task_run`, `test_run`, `error`
   - [ ] `module` 허용값 열거: `naver_booking`, `scheduled_task`, `test_run`, `error_log`, `instagram_worker`
   - [ ] 금지 필드 목록 작성: `message`, `traceback`, `context`, `account_id`, `url_token`, `slots_info`, `error_message`, `details`, `worker_id`
   - [ ] export 가능 필드 집합 ∩ 금지 필드 집합 = ∅ 교차 확인 결과 기록

### Phase 2: 완료 기준 (`docs/plan/bigquery-schema-design.md` 산출물)

4. - [ ] **free-tier guard 기록** — 비용 상한 명시
   - [ ] 월 저장 10GB / 쿼리 1TB 제한 명시 (BigQuery Always Free)
   - [ ] 추정 row 크기 ~200 bytes → 10GB = 50M rows 상한 기록, 일 1,000 이벤트 기준 연 365K rows는 한도 내임을 확인
   - [ ] 금지 필드 유입 차단 조건 명시: export 전 필드명 allowlist 검증 게이트 (allowlist = 허용 5~7컬럼만)
   - [ ] 과금 방지 guard: 단일 쿼리 SELECT *는 금지, SELECT 컬럼 지정 필수 + 파티셔닝 기준(`event_time`) 명시

### Phase M: Merge Handoff

> 이 plan은 schema 설계 문서만 산출하므로 별도 live 검증 대상이 없다. 실제 BigQuery dataset 생성/적재는 후속 todo 또는 deployment owner에서 수행한다.

> T1~T5 해당 없음: 이 plan은 Python 소스를 수정하지 않고 `app/models`·`app/modules`를 read-only로 분석해 plans worktree `docs/plan/bigquery-schema-design.md`를 산출한다. 코드 변경 산출물이 없으므로 pytest 5-Phase 대상이 아니다.

### Phase Z: Post-Merge Cleanup (/merge-test owner)

Z. - [ ] **post-merge 정리**
   - [ ] plans worktree에서 `docs/plan/bigquery-schema-design.md` 커밋 후 main merge
   - [ ] `git worktree remove .worktrees/impl/gcp-todo-3-bigquery-schema`
   - [ ] `git branch -d impl/gcp-todo-3-bigquery-schema`
   - [ ] 이 plan 헤더 `> branch:` / `> worktree:` / `> worktree-owner:` 값 제거

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: `docs/plan/bigquery-schema-design.md`에 5컬럼(`event_time`, `event_type`, `module`, `status`, `duration_ms`)이 정확한 BigQuery 타입으로 정의된다.
- **B**oundary: 월 저장(10GB)/쿼리(1TB/월) 제한과 sample row volume 상한(50M rows)이 명시된다.
- **I**nverse: 금지 필드(`message`, `traceback`, `context`, `account_id`, `url_token`, `slots_info`)가 스키마 허용 필드 집합에 0건 존재함을 교차 확인 결과표로 역검증한다.
- **C**ross-check: export 가능 필드 집합 ∩ 금지 필드 집합 = ∅ 교차 검증 결과가 문서에 기록된다.
- **E**rror: 금지 필드 유입 시 차단하는 allowlist 검증 게이트 조건이 문서에 명시된다.
- **P**erformance/cost: SELECT * 금지 + `event_time` 파티셔닝 기준이 free-tier guard로 문서화된다.

---

*상태: 구현중 | 진행률: 0/17 (0%)*
