# GEMINI.md - Monitor Page Project Context

이 문서는 Monitor Page 프로젝트의 아키텍처, 환경 규칙 및 Gemini CLI를 위한 작업 지침을 정의합니다.

## 1. 필수 규칙 (Critical Rules)

### 1.1 보안 및 시스템 무결성 (Security First)
- **Credential 보호**: `.env` 파일, `.git` 폴더, 그리고 `data/*.db` 파일은 절대 외부로 유출하거나 출력하지 마십시오. Claude API Key, Naver 계정 정보 등이 포함되어 있습니다.
- **Git 안전**: `git clean -fd` 또는 `git reset --hard`와 같은 파괴적인 명령어는 사용자의 명시적 요청 없이 실행하지 마십시오.
- **환경 변수**: 신규 API 키나 설정 추가 시 반드시 `.env` 파일을 업데이트하고 `app/core/config.py` 등에 반영 여부를 확인하십시오.

### 1.2 실행 환경 (Windows/PowerShell)
- **PowerShell 전용**: 모든 쉘 명령은 PowerShell 문법을 따릅니다. `ls`, `rm`, `export` 대신 `Get-ChildItem`, `Remove-Item`, `$env:VAR`를 사용하십시오.
- **경로 규칙**: 
  - 경로에는 반드시 **백슬래시(`\`)**를 사용하십시오.
  - 공백이 포함될 수 있으므로 모든 경로는 **큰따옴표(`"`)**로 감싸십시오. (예: `Get-Content "D:\path\to\file"`)
- **인코딩**: 모든 소스 코드와 문서는 **UTF-8 (BOM 없음)** 인코딩으로 저장되어야 합니다. 한글 깨짐 방지를 위해 필수적입니다.

### 1.3 아키텍처 및 세션 관리
- **Session 0 (Service)**: API 서버 및 백그라운드 서비스가 실행되는 환경입니다. GUI가 없는 `NSSM` 서비스로 관리됩니다.
- **Session 1 (User)**: Playwright GUI 브라우저 워커가 실행되는 환경입니다. 실제 사용자 화면에서 브라우저가 동작해야 하므로 수동 실행 또는 스케줄러를 통해 Session 1에서 구동됩니다.
- **프로세스 제어**: `scripts/browser_workers.py` 또는 `scripts/run.ps1`을 사용하여 서비스를 통합 관리합니다.

---

## 2. 프로젝트 개요 (Project Overview)

네이버 예약, 인스타그램, 상품 정보 등을 모니터링하고 Claude AI를 통해 내용을 분류 및 자동 생성하는 자동화 시스템입니다.

- **Stack**:
  - **Backend**: FastAPI (Python 3.12+), SQLAlchemy, Alembic, Playwright.
  - **Frontend**: SvelteKit 2 (Svelte 5), TailwindCSS 4, TypeScript.
  - **Database**: SQLite (D:\work\project\tools\monitor-page\data\monitor.db).
  - **Service**: Windows NSSM Service, Redis (Queue 관리).

---

## 3. 디렉토리 구조 및 주요 파일

- `app/`: FastAPI 백엔드 코드.
  - `modules/`: 모니터링 대상별 로직 (Booking, Instagram, Product).
  - `worker/`: Playwright 기반 크롤러 및 LLM 워커.
- `frontend/`: SvelteKit 프론트엔드.
- `data/`: SQLite DB 파일 및 Alembic 마이그레이션.
- `scripts/`: 서비스 관리 및 자동화를 위한 PowerShell/Python 스크립트.
  - `browser_workers.py`: 워커 및 API 통합 관리 도구.
  - `service-install.ps1`: NSSM 서비스 설치 스크립트.
- `tests/`: Pytest 기반의 방대한 테스트 스위트.
- `.pids/`: 실행 중인 프로세스의 PID 저장소.

---

## 4. 실행 및 관리 지침 (Operation Guide)

### 4.1 서비스 제어
```powershell
# 전체 서비스 재시작 (API + Workers)
python "scripts\browser_workers.py" restart

# API 서버만 재시작
python "scripts\browser_workers.py" restart-api

# 특정 워커 로그 확인
Get-Content "logs\worker_unified.log" -Wait
```

### 4.2 데이터베이스 관리
- **마이그레이션**: `alembic upgrade head`를 사용하여 스키마를 최신으로 유지하십시오.
- **DB 체크**: `python check_db.py`를 실행하여 데이터 무결성을 확인할 수 있습니다.

### 4.3 테스트 실행
```powershell
# 전체 테스트 실행
pytest

# 특정 모듈 테스트
pytest "tests\modules\test_instagram_service.py"
```

---

## 5. Gemini 워크플로우 (Workflows)

| 명령어 | 대상 파일 | 목적 |
|:---|:---|:---|
| `/plan` | `docs\plan\*.md` | 신규 기능 설계 및 작업 순서 정의 |
| `/implement` | `app\`, `frontend\` | 계획에 기반한 코드 구현 |
| `/webapp-testing` | `tests\` | 빌드 확인 및 Pytest 실행 |
| `/done` | `docs\DONE.md` | 작업 완료 기록 및 아카이브 |
| `/codebase-audit` | - | 전체 코드 구조 및 성능 점검 |

---

## 6. 특이사항 및 주의사항 (Notes)

- **Playwright Anti-Detection**: `tests\test_anti_detection.py`에 정의된 지침을 준수하여 봇 탐지를 회피하십시오.
- **LLM Cost 관리**: Claude API 호출 시 `writing` 서비스의 토큰 사용량을 모니터링하십시오.
- **Log Cleanup**: 로그 파일이 비대해질 수 있으므로 `scripts\cleanup-logs.ps1`을 주기적으로 검토하십시오.
- **Mobile Server**: `mobile-server/` 디렉토리는 별도의 FastAPI 서버로 동작하며 모바일 연동 기능을 담당합니다.
