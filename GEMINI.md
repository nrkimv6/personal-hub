# GEMINI.md - Monitor Page Project Context

이 문서는 Monitor Page 프로젝트의 아키텍처, 규칙, 그리고 Gemini CLI를 위한 워크플로우를 정의합니다.

## 1. 필수 규칙 (Critical Rules)

### 1.1 보안 및 시스템 무결성
- **Credential 보호**: .env 파일, .git 폴더, 그리고 data/*.db 파일은 절대 외부로 유출되거나 커밋되지 않도록 보호합니다.
- **Git 조작 주의**: git clean -fd나 git reset --hard와 같은 파괴적인 명령은 사용자의 명시적인 요청 없이는 수행하지 않습니다.
- **API Key 관리**: Claude/Gemini API Key, Naver 로그인 정보 등은 .env 파일에서 관리하며 코드에 하드코딩하지 않습니다.

### 1.2 실행 환경 (Windows/PowerShell)
- **PowerShell 기반**: 모든 쉘 명령은 PowerShell 문법을 따릅니다. ls, m, export 대신 Get-ChildItem, Remove-Item, $env:VAR를 사용합니다.
- **경로 규칙**: 
  - 경로 구분자는 반드시 **백슬래시(\)**를 사용합니다.
  - 공백이 포함될 수 있으므로 모든 경로는 **큰따옴표(")**로 감쌉니다.
- **인코딩**: 모든 파일은 **UTF-8 (BOM 없음)** 인코딩으로 저장해야 한글 깨짐을 방지할 수 있습니다.

### 1.3 서비스 구조
- **Session 0 (NSSM)**: 백그라운드 서비스(API, Workers)는 NSSM을 통해 Windows 서비스로 등록되어 실행될 수 있습니다.
- **Session 1 (Interactive)**: Playwright GUI가 필요한 작업은 사용자 세션(Session 1)에서 실행되어야 브라우저 창이 보입니다.

---

## 2. 프로젝트 개요 (Project Overview)

네이버 예약 및 각종 사이트 모니터링을 자동화하고, LLM(Claude/Gemini)을 활용하여 데이터를 분석하거나 예약을 시도하는 시스템입니다.

- **Backend**: FastAPI (Python 3.12+), SQLAlchemy, Alembic, Playwright
- **Frontend**: SvelteKit 2 (Svelte 5), TailwindCSS 4, TypeScript
- **Database**: SQLite (data/monitor.db)
- **Messaging**: Redis (Task Queue 및 상태 공유)
- **Process Management**: scripts/browser_workers.py를 통한 통합 관리

---

## 3. 디렉토리 구조

- pp/: FastAPI 백엔드 소스
  - modules/: 모니터링/예약 로직 (Booking, Instagram 등)
  - worker/: Playwright 기반 워커 프로세스
- rontend/: SvelteKit 프론트엔드
- data/: SQLite DB 및 Alembic 마이그레이션 파일
- scripts/: 서비스 관리용 PowerShell/Python 스크립트
- docs/: 프로젝트 문서 및 계획(plan), 아카이브
- .agent/: Gemini CLI 전용 워크플로우 및 설정

---

## 4. 모니터링 상태 관리 (State Machine)

모니터링 대상(Target)은 다음 세 가지 상태 변수로 관리됩니다.

| 필드 | 관리 주체 | 설명 |
|:---|:---|:---|
| is_enabled | **사용자(API)** | 모니터링 사용 여부 (On/Off) |
| is_active | **워커(Worker)** | 실제 워커 프로세스가 해당 대상을 감시 중인지 여부 |
| un_status | **워커(Worker)** | 상세 실행 상태 (idle, unning, paused, stopped, error) |

- **동작 원리**: 사용자가 is_enabled=true로 설정하면 워커가 이를 감지하여 is_active=true로 전환하고 모니터링을 시작합니다.

---

## 5. 주요 운영 명령 (Operation Guide)

`powershell
# 전체 시스템 재시작 (API + Workers)
python "scripts\browser_workers.py" restart

# 워커 상태 확인
python "scripts\browser_workers.py" status

# 테스트 실행
pytest
`

---

## 6. Gemini CLI 워크플로우

| 명령 | 설명 |
|:---|:---|
| /plan | 새로운 기능 설계 및 docs/plan/에 문서 생성 |
| /implement | 계획에 따른 코드 구현 및 단위 테스트 수행 |
| /webapp-testing | 프론트엔드/백엔드 통합 테스트 및 빌드 확인 |
| /done | 작업 완료 후 TODO 업데이트 및 변경사항 정리 |
| /codebase-audit | 코드 품질 점검 및 아키텍처 분석 |

---

## 7. 주의 사항 (Notes)

- **Playwright Anti-Detection**: 네이버 등 보안이 강화된 사이트 대응을 위해 stealth 모드 및 적절한 User-Agent 설정이 필수입니다.
- **LLM 비용 관리**: 불필요한 API 호출을 최소화하고, 캐싱 로직을 적극 활용합니다.
- **Log 관리**: logs/ 폴더에 생성되는 로그 파일이 비대해지지 않도록 주기적으로 관리합니다 (scripts/cleanup-logs.ps1).