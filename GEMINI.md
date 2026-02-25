# GEMINI.md - Project Context & Instructions

프로젝트: **Monitor Page** (네이버 예약, 쿠팡, 인스타그램 모니터링 및 자동화 서비스)

## ⚠️ Critical Core Rules (필수 규칙 - Gemini CLI 전용)

### 1. 보안 및 데이터 보호 (Security First)
- **.git 보호**: .git 디렉토리와 내부 데이터를 절대 수정하거나 삭제하지 마세요. git clean -fd, git reset --hard 등 파괴적 명령어 사용 금지.
- **비밀번호/키 보호**: .env 파일과 API 키(Claude, Naver 등)를 절대 로그에 노출하거나 커밋하지 마세요.
- **데이터베이스 보호**: data/monitor.db는 실제 운영 데이터가 포함되어 있으므로 삭제나 초기화 시 반드시 백업을 확인하세요.

### 2. 환경 및 실행 표준 (Windows/PowerShell)
- **Windows + PowerShell**: 반드시 PowerShell 문법을 사용하세요. bash 명령어(ls, rm, export, cd ~ 등) 사용 금지.
- **경로 규칙**: 
  - 경로를 인자로 전달할 때는 반드시 **큰따옴표(" ")**로 감싸세요.
  - 슬래시(/) 대신 **백슬래시(\\)**를 사용하세요 (Python 내부 코드 제외).
  - 파일 조작 시 가능한 **절대 경로**(D:\work\project\tools\monitor-page\...)를 사용하세요.
- **파일 인코딩**: 모든 텍스트 파일(코드, JSON, Markdown 등)은 반드시 **UTF-8 (BOM 없음)**로 저장하세요. 한글 깨짐 방지를 위해 필수입니다.

### 3. 개발 가이드라인
- **리팩토링**: 단일 파일 700줄 초과 시 모듈화를 제안하되, 기존의 작동하는 로직을 불필요하게 대규모로 변경하지 마세요.
- **버그 수정**: 버그 수정 시 반드시 **재현 스크립트(Reproduction script)**를 먼저 작성하여 실패를 확인한 후 수정을 진행하세요.
- **테스트**: 기능 추가 시 	ests/ 디렉토리에 대응하는 테스트 코드를 작성하거나 기존 테스트를 업데이트하세요.

---

## 🏗️ Project Overview (프로젝트 개요)

네이버 예약 상태 모니터링, 쿠팡 가격 추적, 인스타그램 데이터 추출을 위한 통합 자동화 시스템입니다.

- **Stack**: 
  - Backend: FastAPI (Python 3.12+), SQLAlchemy, Playwright.
  - LLM: Claude API (Content Generation & Classification).
  - Frontend: SvelteKit 2 (Svelte 5), TailwindCSS 4, TypeScript.
  - Infrastructure: Windows NSSM Service (Session 0 - API), User Session Worker (Session 1 - GUI Browser).

### 주요 디렉토리 구조
- pp/: FastAPI 백엔드
  - modules/: 핵심 비즈니스 로직 (Booking, Instagram, Product)
  - worker/: Playwright 기반 오케스트레이터 및 워커
- rontend/: SvelteKit 웹 인터페이스
- data/: SQLite DB 및 로그, 크롤링 결과물
- scripts/: 서비스 관리(Restart, Alias)를 위한 스크립트
- .pids/: 실행 중인 워커 프로세스 ID 관리

---

## 🚀 Execution & Management (실행 및 관리)

### 핵심 실행 명령어 (PowerShell)
- **전체 서비스 재시작**: python scripts/browser_workers.py restart
- **API 서버만 재시작**: python scripts/browser_workers.py restart-api
- **DB 스키마 적용**:
  `powershell
  python -c "import sqlite3; conn = sqlite3.connect('D:/work/project/tools/monitor-page/data/monitor.db'); sql = open('data/migrations/latest.sql', encoding='utf-8').read(); conn.executescript(sql); conn.commit(); conn.close();"
  `

### 프로세스 관리 (Exe Aliases)
Task Manager에서 프로세스를 쉽게 구분하기 위해 별칭을 사용합니다.
- monitorpage-api.exe, monitorpage-worker.exe, monitorpage-claude.exe
- 설정: .\scripts\setup-exe-aliases.ps1 실행

---

## 🛠️ Workflows & Skills (Gemini 워크플로우)

| 명령어 | 워크플로우 | 용도 |
|:---|:---|:---|
| /plan | plan.md | 구현 계획 수립 및 TODO.md 업데이트 |
| /next | 
ext.md | TODO.md에서 다음 우선순위 작업 자동 선택 |
| /implement | implement.md | 실제 코드 작성 및 단위 테스트 |
| /done | done.md | 완료 처리, 검증 및 변경사항 문서화 |
| /webapp-testing | webapp-testing.md | SvelteKit/FastAPI 통합 테스트 및 빌드 확인 |
| /codebase-audit | codebase-audit.md | 전체 시스템 아키텍처 및 보안 점검 |

---

## 🧩 Capabilities (주요 기능)

- **naver_booking**: 네이버 예약 슬롯 실시간 모니터링 및 상태 변경 감지.
- **instagram**: 포스팅 크롤링, 데이터 분석 및 트렌드 추적.
- **writing**: Claude API를 활용한 컨텐츠 생성 및 요약 자동화.
- **dev_runner**: plan-runner를 통한 자동화된 개발 및 테스트 루프.
- **image/file_classifier**: 머신러닝 기반 이미지 분류 및 파일 정리.

---

## 📚 Rules Reference (참조 규칙)
상세 규칙은 .agent/rules/ 디렉토리의 개별 파일을 확인하세요.
- git-safety.md: Git 조작 시 안전 수칙
- path-conventions.md: Windows 환경 경로 가이드
- commit.md: 커밋 메시지 규칙
- 
o-file-deps.md: 의존성 관리 원칙