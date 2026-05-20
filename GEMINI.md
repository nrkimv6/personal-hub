# GEMINI.md - Monitor Page Project Context

이 문서는 Monitor Page 프로젝트의 아키텍처, 규칙, 그리고 Gemini CLI를 위한 워크플로우를 정의합니다.

## 1. 필수 규칙 (Critical Rules)

### 1.1 보안 및 시스템 무결성
- **Credential 보호**: `.env` 파일, `.git` 폴더, 그리고 `data\*.db` 파일은 절대 외부로 유출하거나 커밋하지 않도록 보호합니다.
- **Git 조작 주의**: `git clean -fd`나 `git reset --hard`와 같은 파괴적인 명령은 사용자의 명시적인 요청 없이 수행하지 않습니다.
- **커밋 규칙**: `git commit`을 직접 사용하지 않고 반드시 `& "D:\work\project\tools\common\commit.ps1"` 스크립트를 사용하여 커밋합니다.
- **Mirror surface 보호**: monitor-page의 `.agents\`, `.agent\`, `.claude\`, `.gemini\`는 wtools에서 동기화되는 receiver mirror surface입니다. 이 경로를 직접 수정하거나 로컬 mirror-only 커밋으로 닫지 않습니다.
- **Sync 수신 규칙**: wtools 원본 변경은 원격 sync commit을 `git pull --ff-only`로 수신합니다. root `main`과 `origin/main`이 diverged이면 push-first나 plain pull로 닫지 않고 owner-approved merge/rebase/source regeneration/abort 중 하나로 처리합니다.
- **Primary/mirror 구분**: wtools 내부 `.agents`와 `.claude`는 각 엔진의 독립 primary surface입니다. monitor-page의 동일 경로명은 sync mirror이므로 두 개념을 혼동하지 않습니다.
- **정책 cross-link**: mirror 정책의 상세 기준은 monitor-page `AGENTS.md`의 mirror surface 항목과 `CLAUDE.md`의 "이 프로젝트에서 `.claude/skills/`, `.claude/agents/` 직접 수정 금지" 섹션을 따릅니다.

### 1.2 실행 환경 (Windows/PowerShell)
- **PowerShell 전용**: 모든 쉘 명령은 PowerShell 문법을 따릅니다. bash 문법(ls, rm, export 등) 사용을 금지하며, PowerShell 명령어(Get-ChildItem, Remove-Item, $env:VAR 등)를 사용합니다.
- **경로 규칙**: 
  - 경로 구분자에는 반드시 **백슬래시(\)**를 사용합니다.
  - 모든 경로는 **따옴표(")**로 감싸서 공백 및 특수문자 문제를 방지합니다.
- **인코딩**: 모든 파일은 **UTF-8 (BOM 없음)** 인코딩으로 저장하여 한글 깨짐을 방지해야 합니다.

---

## 2. 프로젝트 개요 (Project Overview)

네이버 예약 및 각종 사이트 모니터링을 자동화하고, LLM(Claude/Gemini)을 활용하여 데이터를 분석하거나 예약을 시도하는 시스템입니다.

- **Backend**: FastAPI (Python 3.12+), SQLAlchemy, Playwright
- **Frontend**: SvelteKit 2 (Svelte 5), TailwindCSS 4, TypeScript
- **Database**: PostgreSQL 16 (`monitor` database)
- **Messaging**: Redis (Task Queue 및 상태 공유)
- **Process Management**: NSSM(Session 0) 및 `scripts\browser_workers.py`(Session 1) 통합 관리

---

## 3. 디렉토리 구조 (Directory Structure)

- `app\`: FastAPI 백엔드 소스
  - `modules\`: 도메인별 로직 (naver_booking, instagram, writing, file_search 등)
  - `worker\`: 통합 브라우저 워커 (`orchestrator.py` 및 각종 모니터링 워커)
  - `models\`: SQLAlchemy 데이터베이스 모델
  - `migrations\`: DB 마이그레이션 SQL 파일
- `frontend\`: SvelteKit 프론트엔드
- `data\`: runtime evidence, exports, and local data artifacts
- `scripts\`: 서비스 관리 및 자동화용 PowerShell/Python 스크립트
- `.worktrees\plans\docs\plan\`: 프로젝트 계획(plan) 문서
- `.worktrees\plans\docs\archive\`: 완료된 계획 아카이브
- `docs\`: 프로젝트 문서 및 가이드
- `tests\`: 테스트 수트 (Unit, Integration, E2E, dev_runner 등)
- `logs\`: 실행 로그 관리
- `.agent\`: Gemini CLI 전용 설정 및 워크플로우
- `.agents\`, `.claude\`, `.gemini\`: wtools sync로만 갱신되는 mirror surface

---

## 4. 프로세스 및 운영 (Operations)

### 4.1 프로세스 별칭 (Exe Aliases)
관리 편의를 위해 `python.exe`를 각 역할별 별칭(`monitorpage-*.exe`)으로 복사하여 사용합니다. (`scripts\setup\setup-exe-aliases.ps1`)

| 프로세스 별칭 | 역할 |
|:---|:---|
| `monitorpage-api.exe` | FastAPI API 서버 |
| `monitorpage-worker.exe` | 통합 브라우저 워커 |
| `monitorpage-claude.exe` | Claude/LLM 워커 |
| `monitorpage-cmdlistener.exe` | Redis 커맨드 리스너 |

### 4.2 주요 운영 명령
```powershell
# 시스템 상태 확인
python "scripts\browser_workers.py" status

# 워커 재시작
python "scripts\browser_workers.py" restart

# API 재시작 (Self-Restart)
python "scripts\browser_workers.py" restart-api

# DB 마이그레이션 실행 (SQL 파일 적용 후)
# app\migrations\XXX.sql 파일을 생성한 후 즉시 실행 필요
```

---

## 5. Gemini CLI 워크플로우

| 명령 | 설명 |
|:---|:---|
| `/plan` | `.worktrees\plans\docs\plan\`에 새로운 기능 설계 및 단계별 계획 수립 |
| `/implement` | 수립된 계획에 따라 linked worktree에서 구현 및 단위 테스트 수행 |
| `/merge-test` | 구현 branch를 main에 머지한 뒤 post-merge 검증과 cleanup 수행 |
| `/reflect` | 구현 후 회고와 후속 corrective plan 생성 |
| `/review-plan` | 새 계획서 재검토, TODO 확장, docs commit 처리 |
| `/webapp-testing` | 프론트엔드/백엔드 통합 테스트 및 빌드 확인 |
| `/done` | 구현 완료 후 TODO 업데이트 및 문서 정리 |
| `/codebase-audit` | 코드 품질 및 아키텍처 점검 (명시적 요청 시 실행) |

---

## 6. 개발 가이드라인 (Dev Guidelines)

- **UI 구현**: 100건 이상의 데이터 처리 시 반드시 페이지네이션(`$lib\utils\pagination.svelte`)을 적용합니다.
- **이벤트 처리**: 카드 내 버튼 클릭 등 중첩 클릭 시 `e.stopPropagation()`을 잊지 않습니다.
- **비동기 주의**: FastAPI와 asyncio 사용 시 리소스(transport 등)가 제대로 닫히지 않는 누수에 주의합니다.
- **타입 안전성**: 프론트엔드 수정 후 `npm run check`를 통해 TypeScript 에러가 없는지 확인합니다.
- **마이그레이션**: 모델 변경 시 `app\migrations\`에 SQL 파일을 생성하고 즉시 DB에 적용해야 합니다.
