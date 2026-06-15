# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 3

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 3
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: schema 문서 검증
> 진행률: 0/17 (0%)
> 요약: 운영 이벤트를 BigQuery로 보낼 수 있도록 개인정보 없는 synthetic schema를 정의한다.

## TODO

### Phase 0: Worktree 준비 (/implement 진입 게이트)

0. - [ ] **worktree 생성 또는 재개** — 산출물은 `docs/plan` 스키마 설계 문서
   - [ ] `impl/gcp-todo-3-bigquery-schema` 브랜치와 worktree를 생성하거나 기존 것을 재개한다
   - [ ] 이 plan 헤더 `> branch:`/`> worktree:`/`> worktree-owner:`를 생성한 값으로 채운다
   - [ ] worktree cwd를 고정한다

### Phase 1: Export Schema 후보 선정 (설계·문서화)

1. - [ ] **event source 후보 조사** — 민감정보 제외 (코드 수정 없음, read-only 분석)
   - [ ] `app/models`: `monitoring_event.py`, `scheduled_task_log.py`, `test_run.py`(worker run), `modules/reports`(report) 중 export 가능 필드를 분류한다
   - [ ] `app/models`: `proxy_usage.py`, `instagram_worker_status.py`, `error_log.py`, `request_log.py` 중 synthetic event로 대체 가능한 필드를 분류한다

2. - [ ] **BigQuery schema 초안 작성** — demo dataset 기준 (`docs/plan` 산출물)
   - [ ] `docs/plan`: `event_time`(TIMESTAMP), `event_type`(STRING), `module`(STRING), `status`(STRING), `duration_ms`(INTEGER) 중심의 table schema를 정확한 타입으로 작성한다
   - [ ] `docs/plan`: memo body, URL token, account id 같은 금지 필드 목록을 작성한다
   - [ ] `docs/plan`: export 가능 필드 집합 ∩ 금지 필드 집합 = ∅ 임을 교차 확인해 기록한다

### Phase 2: 완료 기준 (`docs/plan` 산출물)

3. - [ ] **free-tier guard 기록** — 비용 상한
   - [ ] `docs/plan`: 월 저장(10GB)/쿼리(1TB/월) 제한과 sample row volume 상한을 명시한다
   - [ ] `docs/plan`: 금지 필드가 export row에 유입되면 차단하는 조건(검증 게이트)을 명시한다

### Phase M: Merge Handoff

> 이 plan은 schema 설계 문서만 산출하므로 별도 live 검증 대상이 없다. 실제 BigQuery dataset 생성/적재는 후속 todo 또는 deployment owner에서 수행한다.

> T1~T5 해당 없음: 이 plan은 Python 소스를 수정하지 않고 `app/models`·`app/modules`를 read-only로 분석해 `docs/plan`에 BigQuery synthetic schema 설계 문서를 산출한다. 코드 변경 산출물이 없으므로 pytest 5-Phase 대상이 아니다. (tests/ 하위에 e2e/http 파일은 존재하나 본 plan의 변경 대상이 아님)

### Phase Z: Post-Merge Cleanup (/merge-test owner)

Z. - [ ] **post-merge 정리**
   - [ ] main merge 시도 + (필요 시) root dirty stash/apply
   - [ ] worktree remove, branch remove, 헤더 meta(`> branch:`/`> worktree:`/`> worktree-owner:`) 제거

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: 테이블 스키마가 `event_time`, `event_type`, `module`, `status`, `duration_ms`를 정확한 타입으로 정의한다.
- **B**oundary: 월 저장/쿼리 제한과 sample row volume 상한이 명시된다.
- **I**nverse: 금지 필드(memo body, URL token, account id)가 스키마에 0건 존재함을 역검증한다.
- **C**ross-check: export 가능 필드 집합 ∩ 금지 필드 집합 = ∅ 를 교차검증한다.
- **E**rror: 금지 필드가 export row에 들어오면 export를 차단하는 조건이 있다.
- **P**erformance/cost: free-tier(저장 10GB, 쿼리 1TB/월) 초과 방지 기준이 있다.

---

*진행률: 0/17 (0%)*
