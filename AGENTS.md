# AGENTS.md

에이전트 작업 진입점 문서.

## Source of Truth

- 전체 규칙/워크플로우/금지사항 원문: [`CLAUDE.md`](CLAUDE.md)

## Quick Guardrails

- 환경: **Windows + PowerShell 기준** (bash 문법 사용 금지)
- `.git` 보호: 삭제/강제 초기화/일괄 되돌리기 금지
- 파괴적 git 금지: `git clean -fd`, `git reset --hard`, `git checkout .`, `git restore .`
- 서비스 충돌 방지: `run.ps1`, `stop.ps1` 직접 실행 금지 (NSSM과 충돌)
- 스킬 원본 수정: monitor-page의 `.claude/skills`, `.claude/agents` 직접 수정 금지  
  `D:\work\project\service\wtools\.claude\`에서 수정 후 동기화

## Operational Commands

```powershell
# API 재시작
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\browser_workers.py" restart-api

# 워커 재시작
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\browser_workers.py" restart

# Frontend 재시작 (Admin DEV)
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\browser_workers.py" restart-frontend

# Frontend 재시작 (Public PREVIEW)
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\browser_workers.py" restart-frontend --public
```

주의: `--restart-frontend`는 오입력. 위치 인자 `restart-frontend` 사용.

## Commit Rule

- `git commit` 직접 사용 금지
- 커밋 스크립트 사용:
  `& "D:\work\project\tools\common\commit.ps1" "type: message"`

## Troubleshooting

- 통합 트러블슈팅: [`docs/dev-guide/troubleshooting.md`](docs/dev-guide/troubleshooting.md)
- Frontend `6101` / `dev-monitor` 장애 전용:
  [`docs/dev-guide/frontend-6101-dev-monitor-troubleshooting.md`](docs/dev-guide/frontend-6101-dev-monitor-troubleshooting.md)
