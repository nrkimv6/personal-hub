# GEMINI.md - Project Context & Instructions

이 프로젝트는 **Monitor Page** (네이버 예약, 쿠팡, 인스타그램 모니터링 및 자동화 서비스)로, Gemini CLI가 이 프로젝트를 수행하기 위한 최상위 지침 및 문맥을 제공합니다.

---

## ⚠️ Critical Core Rules (필수 규칙)

이 규칙은 모든 작업에 우선하며, 이를 위반할 경우 시스템 안정성이 저해될 수 있습니다.

### 1. 보안 및 데이터 보호
- **.git 절대 보호**: `.git` 디렉토리를 삭제하거나 수정하지 마세요. `git clean -fd`, `git reset --hard`와 같은 파괴적인 명령어는 절대 금지됩니다.
- **환경 변수 보호**: `.env` 파일과 API Key는 절대 커밋하거나 외부에 노출하지 마세요.
- **데이터 보존**: `data/monitor.db`는 실제 운영 데이터가 포함되어 있으므로, 직접적인 대량 삭제나 스키마 파괴 시 주의하세요.

### 2. 코드 및 파일 관리
- **700줄 제한**: 단일 파일이 **700줄**을 초과하면 반드시 모듈화하거나 리팩토링하세요.
- **UTF-8 (BOM 없음)**: 모든 텍스트 파일(특히 `.json`)은 반드시 UTF-8 (BOM 없음) 인코딩으로 저장하세요. 한글 깨짐 및 구문 오류를 방지합니다.
- **절대 경로 사용**: 스크립트 실행 및 파일 참조 시 반드시 **절대 경로**를 사용하세요. (`D:/work/project/tools/monitor-page/...`)
- **Windows + PowerShell**: 이 프로젝트는 Windows 환경에서 구동됩니다. bash 문법을 사용하지 마세요.

---

## 🏗️ Project Overview (프로젝트 개요)

네이버 예약 잔여석 감시, 쿠팡 가격 추적, 인스타그램 마케팅 모니터링을 위한 통합 자동화 플랫폼입니다.

### 기술 스택
- **Backend**: Python 3.9+ (FastAPI), SQLAlchemy (SQLite), Playwright, Redis (Queue).
- **Frontend**: SvelteKit 2 (Svelte 5), TailwindCSS 4, TypeScript.
- **Infrastructure**: Windows NSSM Service (Session 0), User Session Worker (Session 1).
- **Automation**: Playwright 기반 브라우저 제어 및 모니터링.

### 주요 디렉토리 구조
- `app/`: FastAPI 백엔드 
  - `modules/`: 주요 도메인 (naver_booking, instagram, writing, claude_worker)
  - `worker/`: 모니터링 워커 (Orchestrator, NaverMonitor, CrawlWorkers 등)
  - `models/`: SQLAlchemy 데이터베이스 모델
- `frontend/`: SvelteKit 프론트엔드
- `data/`: SQLite DB 및 로컬 저장소
- `scripts/`: 서비스 관리 및 자동화 PowerShell/Python 스크립트
- `.pids/`: 실행 중인 프로세스 ID 관리

---

## 🛠️ Execution & Management (실행 및 관리)

### 핵심 실행 명령어 (PowerShell)
- **API 재시작**: `python scripts/browser_workers.py restart-api`
- **워커 전체 재시작**: `python scripts/browser_workers.py restart`
- **DB 마이그레이션**: `app/migrations/*.sql` 파일을 `python -c`를 통해 SQLite에 적용.
  ```powershell
  python -c "import sqlite3; conn = sqlite3.connect('D:/work/project/tools/monitor-page/data/monitor.db'); sql = open('...', encoding='utf-8').read(); conn.executescript(sql); conn.commit(); conn.close();"
  ```

### Exe Aliases (프로세스 식별)
Task Manager에서 프로세스를 쉽게 구분하기 위해 `monitorpage-*.exe` 형태의 별칭을 사용합니다.
- `monitorpage-api.exe`, `monitorpage-worker.exe`, `monitorpage-claude.exe` 등.
- 설정: `.\scripts\setup-exe-aliases.ps1`

---

## 🔄 Workflows & Skills (워크플로우)

Gemini는 다음 워크플로우를 사용하여 작업을 수행합니다.

| 명령어 | 관련 워크플로우 | 용도 |
|:---|:---|:---|
| `/plan` | `.agent/workflows/plan.md` | 구현 계획 수립 및 TODO 작성 |
| `/next` | `.agent/workflows/next.md` | 다음 원자적 작업 수행 |
| `/implement` | `.agent/workflows/implement.md` | 계획에 따른 실제 코드 구현 |
| `/done` | `.agent/workflows/done.md` | 작업 완료 및 검증, TODO 업데이트 |
| `/webapp-testing` | `.agent/workflows/webapp-testing.md` | 프론트/백엔드 통합 테스트 및 빌드 확인 |
| `/commit` | `.agent/workflows/commit.md` | 공통 스크립트를 통한 안전한 커밋 |
| `/codebase-audit` | `.agent/workflows/codebase-audit.md` | 시스템 전반의 상태 점검 |

---

## 🚀 Capabilities (확장 기능)

- **naver_booking**: 네이버 예약 상태 감시 및 자동화.
- **instagram**: 인스타그램 타임라인 모니터링 및 데이터 추출.
- **writing**: AI 기반 글쓰기 및 보정 (Claude API 활용).
- **dev_runner**: `plan-runner`를 통한 장기 작업 자동화.
- **image/file_classifier**: ML 기반 이미지 분류 처리.

---

## 📌 Rules Reference (세부 규칙)

세부적인 운영 규칙은 `.agent/rules/` 디렉토리를 참조하세요.
- `git-safety.md`: Git 조작 시 금지 사항
- `path-conventions.md`: 절대 경로 및 경로 표기법
- `commit.md`: 커밋 메시지 컨벤션 및 스크립트 사용법
- `no-file-deps.md`: 파일 간 의존성 관리 지침
