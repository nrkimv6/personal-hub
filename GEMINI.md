# GEMINI.md - Project Context & Instructions

이 파일은 **Monitor Page** 프로젝트에서 Gemini CLI와 협업하기 위한 핵심 지침입니다. 모든 작업은 여기에 명시된 규칙과 프로젝트의 `.agent/rules`를 최우선으로 준수해야 합니다.

## 🔴 Critical Core Rules

### 1. 코드 품질 및 인코딩 (절대 준수)
- **리팩토링**: 단일 소스 파일이 **700줄을 초과**할 경우 기능별 모듈 분리를 반드시 고려한다.
- **인코딩**: 모든 파일 수정 및 생성 시 반드시 **UTF-8 (BOM 없음)** 인코딩을 사용한다.
  - *사유*: 윈도우 환경에서 '占쏙옙' 등의 한글 깨짐 이슈와 SyntaxError를 방지하기 위함.
- **경로**: 모든 스크립트와 설정에서 **절대 경로**를 우선적으로 사용한다 (`D:/work/project/tools/monitor-page/...`).

### 2. .git 및 소스 보호
- **.git 디렉토리 절대 보호**: 어떤 상황에서도 `.git` 내부를 수정하거나 파괴적인 git 명령(`clean -fd`, `reset --hard`)을 수행하지 않는다.
- **데이터 보호**: `data/monitor.db` 등 데이터베이스 파일의 직접적인 삭제나 훼손에 주의한다.

---

## 프로젝트 개요
네이버 예약, 쿠팡, Instagram 등 다양한 플랫폼의 모니터링 및 자동화(스나이핑, 크롤링)를 수행하는 시스템입니다.

### 기술 스택
- **Backend**: Python 3.9+, FastAPI, SQLAlchemy (SQLite), Playwright.
- **Frontend**: SvelteKit 2 (Svelte 5), TailwindCSS 4, TypeScript.
- **Infrastructure**: Redis (Worker Queue), Windows NSSM Service (Session 0), User Session Worker (Session 1).

---

## 실행 및 관리 (CLI)

### 핵심 실행 스크립트
- **전체 시작**: `.\scripts\startup-browser-workers.ps1` (Session 1 로그인 시)
- **API 재시작**: `python scripts/browser_workers.py restart-api`
- **워커 재시작**: `python scripts/browser_workers.py restart`
- **DB 마이그레이션**: `app/migrations/*.sql` 생성 후 즉시 `sqlite3`를 통해 실행 필수.

### 커밋 규칙
- **직접 커밋 금지**: `git commit` 대신 전용 스크립트 사용.
  - `& "D:\work\project\tools\common\commit.ps1" "feat: message"`
- **Conventional Commits**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

---

## 스킬 및 워크플로우 실행 지침 (Skills & Workflows)

사용자가 아래 키워드를 언급하거나 명령할 경우, 반드시 해당 경로의 워크플로우 파일을 `read_file`로 읽고 그 안의 **절차와 페르소나를 엄격히 준수**하십시오.

| 키워드 (Intent) | 워크플로우 파일 경로 | 실행 지침 (Manual) |
|:---|:---|:---|
| `plan`, `/plan`, `계획` | `.agent/workflows/plan.md` | 구현 전 정밀한 단계별 계획 수립 및 문서화 |
| `next`, `/next`, `다음` | `.agent/workflows/next.md` | 현재 상태 분석 후 최우선 다음 작업 제안 |
| `implement`, `/implement` | `.agent/workflows/implement.md` | 계획된 작업을 실제 코드로 정밀하게 구현 |
| `done`, `/done`, `완료` | `.agent/workflows/done.md` | 작업 완료 검증 및 계획서 업데이트 |
| `test`, `/webapp-testing` | `.agent/workflows/webapp-testing.md` | 프론트엔드/백엔드 통합 테스트 및 빌드 확인 |
| `commit`, `/commit` | `.agent/workflows/commit.md` | 전용 스크립트를 이용한 표준 커밋 절차 수행 |
| `audit`, `/codebase-audit` | `.agent/workflows/codebase-audit.md` | 시스템 전반의 보안 및 아키텍처 정밀 점검 |

**주의**: 모든 워크플로우 실행 시 `.agent/rules`의 해당 도메인 규칙(예: `git-safety.md`)이 동시에 적용되어야 합니다.

### 주요 개발 루프
- `/plan` -> `/implement` -> `/done`                                                                                                                                                                                                    │
- **검증**: 구현 완료 후 `/webapp-testing`을 통해 빌드 및 런타임 오류를 반드시 체크한다.     

---

## 모듈 가이드
- **naver_booking**: 모니터링, 스나이핑, 슬롯 관리.
- **instagram**: 피드 크롤링 및 LLM 분류 (`caller_type=insta_classification`).
- **writing**: AI 기반 글 생성 및 가독성 교정 (`caller_type=writing_refine`).
- **notes**: 마크다운 메모 시스템 (History, Tags 지원).
- **dev_runner**: `plan-runner` 시스템 통합 및 엔진(Claude/Gemini) 관리.
- **image/file_classifier**: ML 기반 로컬 자산 자동 분류 및 정리.
