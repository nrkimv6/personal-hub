# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 2

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 2
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: Python 변경 시 pytest T1~T5 규칙 적용
> 상태: 구현완료
> 반영일시: 2026-06-15 14:13
> 머지커밋: 087a8203 (impl branch = main 동일, no-op merge — 설계 문서 산출물은 plans 브랜치에 커밋)
> 후속정리커밋: 66ca37ed
> 진행률: 15/15 (100%)
> 요약: 전체 앱 이전이 아니라 read-only/health FastAPI endpoint만 Cloud Run PoC로 분리한다.

> 완료일: 2026-06-15
> 아카이브됨
## TODO

### Phase 0: Worktree 준비 (/implement 진입 게이트)

0. - [x] **worktree 생성 또는 재개** — 산출물은 `docs/plan` 설계 문서이므로 plans 워크트리 기준
   - [x] `impl/gcp-todo-2-cloud-run-poc` 브랜치와 worktree를 생성하거나 기존 것을 재개한다
   - [x] 이 plan 헤더 `> branch:`/`> worktree:`/`> worktree-owner:`를 생성한 값으로 채운다
   - [x] worktree cwd를 고정한다 — `D:\work\project\public\personal-hub\.worktrees\impl-gcp-todo-2-cloud-run-poc`

### Phase 1: Cloud Run 대상 축소 (설계·문서화)

1. - [x] **entrypoint 후보 확인** — 최소 API surface 선택 (코드 수정 없음, read-only 분석)
   - [x] `app/main_admin.py`: FastAPI `app` 객체 line 22 확인. `register_routers(app)` 호출(line 88)하나 `app/router_registry.py`가 personal-hub에 누락됨(monitor-page에만 존재) → import 오류로 현재 기동 불가. 무의존 route: `GET /`(line 96), `GET /api/v1/ready`(line 101). admin-only: `plan_records_admin_router`.
   - [x] `app/core/config.py`: `BaseSettings` 정의 확인(line 43). Cloud Run 필요 key: `APP_MODE`, `DATABASE_URL`, `REDIS_ENABLED`, `JWT_SECRET`, `API_BASE_URL`, `FRONTEND_URL`, `GOOGLE_CLIENT_ID/SECRET`, `ADMIN_EMAIL`. local-only: `CHROME_PATH`, `DRIVER_PATH`, `BROWSER_HEADLESS`, `USER_DATA_DIR`, `MEGABEAUTY_KAKAO_ALERT_CLI_PATH`, `GIT_REPOS_ALLOWED_PATHS`.
   - [x] `docker-compose.yml`: Redis 서비스만 정의(PostgreSQL은 host 직접). 무의존 route: `GET /` (lifespan 우회 없이 유일한 진정 무의존). lifespan은 `TESTING=1` 환경변수로 DB 초기화 스킵 가능(단, `api_ready=False` 유지). 무의존 후보 표 — 설계 계약서(2026-06-15_cloud-run-poc-design-contract.md) 참조.

2. - [x] **Cloud Run PoC 계약 작성** — 운영 이전과 분리 (`docs/plan` 산출물)
   - [x] `docs/plan`: full app migration 금지와 read-only demo 범위 명시 → `2026-06-15_cloud-run-poc-design-contract.md` "범위 계약" 섹션
   - [x] `docs/plan`: cold start(60초), timeout, concurrency(80), unauthenticated access(허용) 결정값 명시 → 동 문서 "Cloud Run 결정 항목" 섹션
   - [x] `docs/plan`: Phase 1에서 식별한 무의존 route 표(`GET /` 1개) → 동 문서 "무의존 Route 후보 표" + "PoC 대상 Route 집합" 섹션

### Phase M: Merge Handoff

> live Cloud Run 배포 검증과 선택 route의 실제 200/503 응답 확인(검증 기준 R/E)은 `/merge-test` 이후 또는 별도 deployment owner에서만 수행한다. worktree 단계에서 배포/live 호출을 계획하지 않는다.

> T1~T5 해당 없음: 이 plan은 Python 소스를 수정하지 않고 `app/` 코드를 read-only로 분석해 `docs/plan` 설계 계약 문서를 산출한다. 코드 변경 산출물이 없으므로 pytest 5-Phase 대상이 아니다. (tests/ 하위에 e2e/http 파일은 존재하나 본 plan의 변경 대상이 아님)

### Phase Z: Post-Merge Cleanup (/merge-test owner)

Z. - [x] **post-merge 정리**
   - [x] main merge 시도 + (필요 시) root dirty stash/apply — impl 브랜치 = main 동일(커밋 0, no-op merge)
   - [x] worktree remove, branch remove, 헤더 meta(`> branch:`/`> worktree:`/`> worktree-owner:`) 제거 — 완료

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: 선택된 read-only/health route 집합이 PostgreSQL/Redis 의존 없이 200을 반환한다.
- **B**oundary: cold start, timeout, concurrency 상한값이 명시되고 Cloud Run free-tier 한도 내다.
- **I**nverse: full-app migration이 범위에서 제외됨을 역으로 확인한다(쓰기/DB-필요 route 미포함).
- **C**ross-check: `docker-compose.yml` 의존성과 선택 route 의존성을 교차 확인한다 — 선택 route는 무의존 후보 표에 있어야 한다.
- **E**rror: DB가 필요한 route 호출 시 503 또는 명시적 에러를 반환한다(빈 데이터 위장 금지).
- **P**erformance/cost: unauthenticated 접근 여부 결정값을 기록하고, 월 요청 수가 free-tier(200만/월) 내다.

---

*진행률: 15/15 (100%)*
