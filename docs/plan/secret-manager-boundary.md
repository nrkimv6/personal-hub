# personal-hub Secret Manager Boundary

> 작성일: 2026-06-11
> 기준 커밋: cc1983e7
> 관련 계획서: .worktrees/plans/docs/plan/2026-06-08_public_gcp_free_tier_roadmap_todo-1.md

## 1. Public Sanitization Evidence

### 1-1. README.md Public Sanitization 섹션 (L57-60)

```
Before publication, the repository history was scanned with gitleaks and rewritten with
git-filter-repo. Removed content includes tracked .env history, local backup files
containing tokens, private agent/mirror surfaces, and automated transaction execution code.
```

제거 범위:
- tracked `.env` history
- 토큰을 포함한 로컬 백업 파일
- private agent/mirror surfaces
- automated transaction execution code

### 1-2. .env.example 확인 (L1-5)

| 키 | 값 | 판정 |
|----|-----|------|
| TELEGRAM_BOT_TOKEN | (빈 값) | ✅ placeholder 확인 |
| TELEGRAM_CHAT_ID | (빈 값) | ✅ placeholder 확인 |
| EMAIL_ADDRESS | (빈 값) | ✅ placeholder 확인 |
| EMAIL_PASSWORD | (빈 값) | ✅ placeholder 확인 |
| RECIPIENT_EMAIL | (빈 값) | ✅ placeholder 확인 |

실제 secret 0건 확인됨.

### 1-3. frontend/.env.example 확인 (L4)

| 키 | 값 | 판정 |
|----|-----|------|
| PUBLIC_KAKAO_APP_KEY | `your_javascript_key_here` | ✅ placeholder, server credential 혼입 없음 |

public frontend key와 server credential 분리 확인됨.

### 1-4. Secret Scan Evidence (gitleaks)

```
gitleaks detect --source . --no-git
scanned ~33617810 bytes (33.62 MB) in 3.58s
no leaks found
```

**결과: 0건 (clean)**

---

## 2. Secret Manager 후보 분류표

| 키 | 분류 | 이유 | public demo 기본값 | Secret Manager 우선순위 |
|----|------|------|--------------------|------------------------|
| TELEGRAM_BOT_TOKEN | Secret Manager 1순위 | 텔레그램 알림 bot token, 노출 시 메시지 발송 가능 | `""` | 필수 |
| TELEGRAM_CHAT_ID | Secret Manager 1순위 | 특정 채널 ID, bot token과 쌍으로 사용 | `""` | 필수 |
| EMAIL_ADDRESS | Secret Manager 1순위 | Gmail 계정 주소 | `""` | 필수 |
| EMAIL_PASSWORD | Secret Manager 1순위 | Gmail 앱 비밀번호 | `""` | 필수 |
| GOOGLE_CLIENT_ID | Secret Manager 1순위 | Google OAuth client id | `""` | 필수 |
| GOOGLE_CLIENT_SECRET | Secret Manager 1순위 | Google OAuth client secret | `""` | 필수 |
| JWT_SECRET | Secret Manager 1순위 | JWT 서명 키 — **기본값 `"change-me-in-production-use-random-string"` production 배포 전 반드시 교체 필수** | random string | 필수 |
| NAVER_CLIENT_ID | Secret Manager 대상 | 네이버 API 클라이언트 ID | `""` | 권고 |
| NAVER_CLIENT_SECRET | Secret Manager 대상 | 네이버 API 클라이언트 secret | `""` | 권고 |
| KAKAO_REST_API_KEY | Secret Manager 대상 | 카카오 REST API 키 | `""` | 권고 |
| GOOGLE_SEARCH_API_KEY | Secret Manager 대상 | Google Custom Search API 키 | `""` | 권고 |
| GOOGLE_SEARCH_CSE_ID | Secret Manager 대상 | Programmable Search Engine ID | `""` | 권고 |
| ACTIVITY_HUB_SYNC_API_KEY | Secret Manager 대상 | Activity Hub 동기화 API 키 | `""` | 권고 |
| DATABASE_URL | Secret Manager 대상 | 기본값에 password 포함 (`postgresql://monitor_user:monitor_pass_2026@...`) — public demo는 빈 값 또는 별도 demo DB URL로 대체 | `""` or demo URL | 권고 |

**Secret Manager 대상 합계: 14종**

---

## 3. 빈값 허용 목록 (public demo 기동 가능)

| 키 | 위치 | 기본값 | 비고 |
|----|------|--------|------|
| RECIPIENT_EMAIL | config.py:L100 | `""` | 알림 수신 주소, 미설정 시 알림 미발송 |
| ADMIN_EMAIL | config.py:L217 | `""` | 관리자 이메일, Google OAuth 로그인 없이 기동 가능 |
| API_BASE_URL | config.py:L228 | `""` | Cloudflare Tunnel URL, 로컬에서는 불필요 |
| ADMIN_TOOLS_BASE_URL | config.py:L229 | `""` | 관리 도구 URL, 선택 사항 |
| EXTERNAL_API_URL | config.py:L272 | `""` | 외부 API URL (Cloudflare Tunnel) |
| EXTERNAL_FRONTEND_URL | config.py:L273 | `""` | 외부 프론트엔드 URL (Cloudflare Tunnel) |
| TUNNEL_ID | config.py:L232 | `None` | Cloudflare Tunnel ID, 선택 사항 |

**빈값 허용 합계: 7종**

---

## 4. 개인 경로 Override 권고 목록

아래 항목은 secret이 아니지만 public repo에서 개인 로컬 경로가 하드코딩되어 있어 공개 시 노출됨. 환경변수로 override 권고.

| 키 | 위치 | 현재 하드코딩 값 | 권고 조치 |
|----|------|-----------------|-----------|
| DRIVER_PATH | config.py:L79 | `D:\Programs\executable\chromedriver\135.0.7023\chromedriver.exe` | 환경변수 또는 PATH 조회로 대체 |
| MEGABEAUTY_KAKAO_ALERT_CLI_PATH | config.py:L246 | `D:\work\project\tools\kakaocli-win\.venv\Scripts\kakaocli-win.exe` | 환경변수 또는 빈 문자열로 대체 (MEGABEAUTY_KAKAO_ALERT_ENABLED=false 시 미사용) |
| GIT_REPOS_ALLOWED_PATHS | config.py:L277 | `["D:\\work\\"]` | 환경변수 JSON 배열로 override 또는 빈 리스트로 대체 |

---

## 5. Secret Manager Gate 기준

### ENABLE_SECRET_MANAGER 플래그

- **기본값**: `ENABLE_SECRET_MANAGER=false`
- Secret Manager는 server-side worker/API가 생길 때만 적용한다.
- 기본 배포는 환경변수 `.env` 파일에서 secret을 주입하고, GCP Secret Manager는 미사용.
- `ENABLE_SECRET_MANAGER=true`로 설정했을 때만 GCP Secret Manager에서 secret을 조회한다.

### 과금 경고

- GCP Secret Manager **활성 secret 버전 6개 초과 시 과금** 발생 (Always Free: 6개 버전/월).
- `ENABLE_SECRET_MANAGER=false` 기본값에서 활성 버전 0개 → **과금 0**.
- Secret Manager 적용 시 버전 수를 6개 이내로 관리하거나 비활성 버전은 즉시 disable한다.

---

## 6. 검증 결과 (RIGHT-BICEP)

| 항목 | 결과 |
|------|------|
| **R**ight — 분류 상호배타성 | Secret Manager 14종 ∩ 빈값허용 7종 = {} (겹침 없음 확인). DATABASE_URL을 Secret Manager에, RECIPIENT_EMAIL·ADMIN_EMAIL·API_BASE_URL·ADMIN_TOOLS_BASE_URL·EXTERNAL_API_URL·EXTERNAL_FRONTEND_URL·TUNNEL_ID를 빈값허용에 배치. |
| **B**oundary — 빈값 기동 가능 | 빈값허용 7종은 모두 optional 필드(기본값 `""` 또는 `None`). 앱 기동 시 미설정 상태에서도 import 단계 오류 없음. |
| **I**nverse — .env.example 실제 secret 0건 | .env.example 5개 키 모두 빈 값 placeholder 확인. frontend/.env.example PUBLIC_KAKAO_APP_KEY placeholder 확인. |
| **C**ross-check — scan과 분류표 일치 | gitleaks 0건. 분류표 14종 모두 working tree에서 빈 값으로 설정돼 있어 scan 대상 아님. |
| **E**rror — public 허용 목록에 secret 혼입 없음 | 빈값허용 7종은 모두 URL/이메일 주소류. 인증 토큰/비밀번호/API 키 없음 확인. |
| **P**erformance/cost | ENABLE_SECRET_MANAGER=false 기본값, 활성 버전 0개 → 과금 0. |
