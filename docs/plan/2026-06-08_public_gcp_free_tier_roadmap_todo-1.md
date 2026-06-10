# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 1

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 1
> 선행조건: 없음
> branch:
> worktree:
> worktree-owner:
> 테스트명령: 문서/설정 plan, 구현 전 secret scan evidence
> 상태: 검토완료
> 진행률: 0/12 (0%)
> 요약: `personal-hub`의 backend/frontend env boundary를 확인하고 Secret Manager PoC 기준을 문서화한다.

## TODO

### Phase 1: Secret Boundary 확인

1. - [ ] **public sanitization evidence 고정** — 공개 repo 상태 확인
   - [ ] `README.md:L57-60`: 기존 "Public Sanitization" 섹션에 removed content 범위(tracked .env history, local backup files, private agent/mirror surfaces, automated transaction execution code)가 기술됐음을 확인하고 현황을 `docs/plan/secret-manager-boundary.md`에 기록한다
   - [ ] `.env.example:L1-5`: 5개 키(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, EMAIL_ADDRESS, EMAIL_PASSWORD, RECIPIENT_EMAIL) 모두 빈값 placeholder임을 확인하고 실제 secret 0건임을 기록한다
   - [ ] `frontend/.env.example:L4`: `PUBLIC_KAKAO_APP_KEY=your_javascript_key_here` — placeholder 확인, public frontend key와 server credential 혼입 없음을 기록한다
   - [ ] `gitleaks detect --source .` (또는 `--no-git` 옵션): working tree secret scan을 실행하고 결과(0건 또는 발견 목록)를 `docs/plan/secret-manager-boundary.md`에 evidence로 기록한다

2. - [ ] **Secret Manager 후보 분류** — backend 설정 키 분류
   - [ ] `app/core/config.py:L95-100`: 알림 secret 4종(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, EMAIL_ADDRESS, EMAIL_PASSWORD) → Secret Manager 1순위 대상 목록에 추가한다
   - [ ] `app/core/config.py:L215-217,L220`: OAuth/JWT secret 3종(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET) → Secret Manager 대상 목록에 추가한다 — JWT_SECRET 기본값 `"change-me-in-production-use-random-string"`은 production 배포 전 교체 필수로 표시한다
   - [ ] `app/core/config.py:L235-239,L258`: 검색/통합 API key 6종(NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, KAKAO_REST_API_KEY, GOOGLE_SEARCH_API_KEY, GOOGLE_SEARCH_CSE_ID, ACTIVITY_HUB_SYNC_API_KEY) → Secret Manager 대상 목록에 추가한다
   - [ ] `app/core/config.py:L55`: DATABASE_URL 기본값(`postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor`)이 password를 포함하므로 Secret Manager 대상에 추가하고, public demo에서 빈값 또는 별도 demo DB URL로 대체하는 기준을 기록한다
   - [ ] `app/core/config.py:L217,L224-228,L257`: public demo에서 빈값 허용 가능한 key 7종(RECIPIENT_EMAIL, ADMIN_EMAIL, API_BASE_URL, ADMIN_TOOLS_BASE_URL, EXTERNAL_API_URL, EXTERNAL_FRONTEND_URL, TUNNEL_ID) → 별도 "빈값 허용" 목록으로 기록한다
   - [ ] `app/core/config.py:L79,L246,L277`: 하드코딩된 개인 로컬 경로 3곳(DRIVER_PATH `D:\Programs\...`, MEGABEAUTY_KAKAO_ALERT_CLI_PATH `D:\work\...`, GIT_REPOS_ALLOWED_PATHS `["D:\\work\\"]`) → secret은 아니지만 public repo에서 개인 경로 노출 항목으로 override 권고 목록에 기록한다

### Phase 2: 완료 기준

3. - [ ] **문서화 기준 작성** — 후속 TODO 선행조건
   - [ ] `docs/plan/secret-manager-boundary.md` (신규): Secret Manager 대상 14종과 빈값 허용 7종을 분류한 source-of-truth 표를 작성한다 — 각 key별 `{key명 | 분류 | 이유 | public demo 기본값}` 컬럼 포함
   - [ ] `docs/plan/secret-manager-boundary.md`: ENABLE_SECRET_MANAGER=false 기본값 gate 기준과 활성 버전 6개 초과 시 과금 경고를 추가한다
   - [ ] `docs/plan/secret-manager-boundary.md`: secret scan evidence(Phase 1-1 결과)와 개인 경로 override 권고 목록을 함께 기록한다

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: backend secret key 목록과 public 허용(빈 값 가능) key 목록이 상호 배타적이고, 합집합이 `config.py` 전체 설정 키를 덮는다.
- **B**oundary: public 허용 key는 빈 문자열/누락 상태에서도 앱이 기동한다(필수 검증 통과).
- **I**nverse: `.env.example`/`frontend/.env.example`에 실제 secret 값이 0건이고 placeholder만 존재함을 역검증한다.
- **C**ross-check: secret scan(gitleaks 등) 결과가 분류표와 일치한다 — scan이 잡은 모든 secret이 Secret Manager 목록에 포함된다.
- **E**rror: public 허용 목록에 실제 secret이 섞이면 분류 실패로 표시한다.
- **P**erformance/cost: `ENABLE_SECRET_MANAGER=false` 기본값에서 활성 secret 버전 0개 → 과금 0.

---

*진행률: 0/12 (0%)*
