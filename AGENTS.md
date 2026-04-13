# AGENTS.md

에이전트 작업 진입점 문서.

## Source of Truth

- 전체 규칙/워크플로우/금지사항 원문: [`CLAUDE.md`](CLAUDE.md)

## Quick Guardrails

- 환경: **Windows + PowerShell 기준** (bash 문법 사용 금지)
- `.git` 보호: 삭제/강제 초기화/일괄 되돌리기 금지
- 파괴적 git 금지: `git clean -fd`, `git reset --hard`, `git checkout .`, `git restore .`
- 서비스 충돌 방지: `run.ps1`, `stop.ps1` 직접 실행 금지 (NSSM과 충돌)
- frontend verify 경계: `implement`/worktree 단계에서는 `frontend verify(sync/check/build)` 금지, `/merge-test` + main에서만 허용한다. 예시로 `npm run build`, `npm run check`, `npm run check:watch`, `svelte-kit sync`, `svelte-check`, `vite build`, `node ... svelte-kit.js sync`가 모두 포함된다.
- `_build_worktree.ps1`는 setup 전용 helper 예외이며, implement 중 임의 probe 근거로 사용하면 안 된다.
- 스킬 원본 수정: monitor-page의 `.claude/skills`, `.claude/agents` 직접 수정 금지  
  `D:\work\project\service\wtools\.claude\`에서 수정 후 동기화

## Operational Commands

```powershell
# API 재시작
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\services\browser_workers.py" restart-api

# 워커 재시작
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\services\browser_workers.py" restart

# Frontend 재시작 (Admin DEV)
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\services\browser_workers.py" restart-frontend

# Frontend 재시작 (Public PREVIEW)
& "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe" "D:\work\project\tools\monitor-page\scripts\services\browser_workers.py" restart-frontend --public
```

주의: `--restart-frontend`는 오입력. 위치 인자 `restart-frontend` 사용.

## Commit Rule

- `git commit` 직접 사용 금지
- 커밋 스크립트 사용:
  `& "D:\work\project\tools\common\commit.ps1" "type: message"`

## Proxy Operations

- 공유 프록시는 `proxy_list_get.txt` / `proxy_list_post.txt`를 우선 읽고, 파일이 없으면 `proxy_list.txt`로 fallback한다.
- `status.json` 운영 점검 시에는 `method_summary`와 `active_24h_by_method`를 함께 확인한다.

## Skill Authoring Guardrail

- 스킬 파일에 단일 파일 기준의 고정 설명/제한(예: 특정 파일 N줄 이하 유지, 특정 파일만 구조 강제) 작성 금지.
- 예시 금지: `loop.py <= 220`, `commands.py <= 550` 같은 파일별 수치 임계값.
- 파일 경로 명시는 작업 대상 지정 목적에 한해 허용한다.
- 품질 기준은 파일 크기 숫자 대신 동작 계약, 테스트 검증, 실패/리스크 조건으로 작성한다.

## Troubleshooting

- 통합 트러블슈팅: [`docs/dev-guide/troubleshooting.md`](docs/dev-guide/troubleshooting.md)
- Frontend `6101` / `dev-monitor` 장애 전용:
  [`docs/dev-guide/frontend-6101-dev-monitor-troubleshooting.md`](docs/dev-guide/frontend-6101-dev-monitor-troubleshooting.md)
