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
- `.claude/skills/` 또는 `.agents/skills/`를 수정할 때는 wtools 원본에서 반영이 필요한지 검토하고 결과를 `반영|비반영|별도 계획|해당 없음`으로 기록한다. monitor-page mirror surface 직접 수정은 금지한다.
- wtools 내부 `.agents`와 `.claude`는 각 엔진의 독립 primary surface이며 서로 mirror가 아니다. monitor-page의 동일 경로명은 receiver mirror surface로만 취급한다.
- cross-model surface 변경은 wtools 원본 기준으로 분류한다. 공통 정책/워크플로우 계약은 다른 surface 반영을 검토하고, 모델별 authoring/실행 메커니즘은 해당 surface 한정으로 둔다.
- mirror surface(`.agents/`, `.agent/`, `.claude/`, `.gemini/`) 직접 수정·로컬 커밋 금지. wtools 원본 수정 후 원격 sync commit을 `git pull --ff-only`로만 수신한다.
- plan draft scratch는 `.worktrees/drafts/plan/<slug>_draft.md` 단일 파일만 사용한다. `.worktrees/drafts/plan/<session-id>/` 폴더와 `metadata.json` + `draft.md` 세션 형식은 신규 작성 대상이 아니다.
- backup/restore 브랜치를 main에 반영할 때 source branch에 mirror/skill 변경이 섞여 있는지 먼저 확인한다: `git diff --name-status <base> <source> -- .agents .agent .claude .gemini`. 사용자가 skill 제외를 지시했거나 mirror 변경이 범위 밖이면 병합 입력 단계에서 제외하고, merge 전후 `.agents/.agent/.claude/.gemini` diff가 비어 있지 않으면 완료 처리 금지.
- root `main`과 `origin/main` 관계는 `git rev-list --left-right --count HEAD...origin/main`으로 분류한다. `behind-only`는 `git pull --ff-only` 수신 후보이고, `diverged`는 즉시 blocker가 아니라 mirror diff와 충돌 가능성을 먼저 보고하는 `명시 merge 결정 필요` 상태다. 단, sync tip을 plain `git pull`이나 push-first local merge로 닫지 않는다.
- root worktree(`main`/non-main 공통)에서는 구현성 경로를 직접 수정·커밋하지 않는다. 현재 impl worktree 또는 대상 repo worktree로 reroute한다. root branch guard는 `scripts/git-hooks/root-branch-guard.ps1`이며, root checkout이 main 밖으로 이동하면 `.git/root-branch-guard.violation` sentinel을 남긴다.

## Receiver Mirror Scope

- monitor-page root의 `.agents/`, `.claude/`, `.gemini/`, `.agent/` mirror surface는 모두 wtools sync 결과로 취급한다.
- 여기서 mirror surface는 monitor-page receiver 복제본을 뜻한다. wtools 원본의 `.agents`/`.claude` primary authoring surface 관계를 mirror로 해석하지 않는다.
- Codex, Claude, Gemini 운영자는 root에서 mirror conflict를 직접 resolve하거나 mirror-only sync merge를 만들지 않는다.
- mirror sync routing은 `git fetch origin` 후 `git rev-list --left-right --count HEAD...origin/main` tuple을 기준으로 한다. `git status --short --branch`는 display evidence다.
- `behind-only`(`left=0,right>0`)는 `git pull --ff-only` 수신 후보다.
- `ahead-only`(`left>0,right=0`)만 owner가 `git push origin main`으로 origin을 정렬한 뒤 `git pull --ff-only`를 retry할 수 있다.
- `diverged`(`left>0,right>0`)는 push-first 금지다. mirror path가 관련되면 자동화된 wtools sync 재생성, wtools source owner flow, sync worker, 또는 GitHub Actions `sync-skills.yml` evidence를 확보한 뒤 downstream read-back으로 닫는다. mirror path가 없고 사용자가 명시 승인한 일반 divergence만 fetch/rev-list/mirror diff read-back 후 충돌 없는 merge decision으로 진행할 수 있다.
- 세부 절차: [`docs/dev-guide/root-branch-guard.md`](docs/dev-guide/root-branch-guard.md)

## Plans Worktree (활성)

계획서·아카이브는 orphan `plans` 브랜치의 고정 워크트리로 관리됩니다.

| 항목 | 경로 |
|------|------|
| 활성 plan 경로 | `.worktrees/plans/docs/plan/` |
| archive 경로 | `.worktrees/plans/docs/archive/` |
| 브랜치 | `plans` (orphan — main과 공통 조상 없음) |

**활성 안내**: 계획서와 아카이브는 `.worktrees/plans`가 단일 진실원입니다. main에서 `docs/plan/` 또는 `docs/archive/`를 커밋하려 하면 pre-commit hook이 차단합니다.

## Draft Scratch Surface

- 신규 plan 초안은 canonical plans worktree에 바로 만들지 않고, repo root 기준 ignored scratch file `.worktrees/drafts/plan/<slug>_draft.md`에서 작성한다.
- `.worktrees/drafts/plan/<session-id>/` 하위 폴더와 `metadata.json` + `draft.md` 세션 형식은 legacy draft로만 취급한다. 신규 작성·publish 가능한 입력으로 쓰지 않는다.
- `<slug>_draft.md`에는 publish 대상 후보, 승인된 요구사항, 미승인 제안, 작성/갱신 시각을 front matter 또는 본문 metadata로 남긴다.
- stale draft 판단은 `<slug>_draft.md` 파일 mtime 또는 flat metadata `updated_at` 기준 14일 이상으로 한다. 삭제·덮어쓰기는 사용자 확인 후에만 수행한다.

### 세션 시작 시 ensure 명령

```powershell
# PowerShell: plans 워크트리가 없으면 복구
if (-not (git worktree list | Select-String "\.worktrees[\\/]plans")) {
    git worktree add .worktrees/plans plans
}
```

```bash
# Bash: plans 워크트리가 없으면 복구
git worktree list | grep -q ".worktrees/plans" || git worktree add .worktrees/plans plans
```

### P1-2 Tier 결정 (Claude 앱 환경)

사용자 수동 검증 전까지 **Tier 2 가정**: Claude 앱에서는 plan 조회/생성만 허용, 구현/머지는 PC CLI에서. `git show plans:<파일경로>` 읽기 폴백 사용.

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

## Child Helper Contract

- mirror surface(`.agents/.claude/.gemini/.agent`)가 `common\tools\<helper>.ps1|.sh|.py`를 언급하면 monitor-page child repo에서는 다음 순서로 해석한다:
  1. repo-local `common\tools\<helper>`
  2. `D:\work\project\service\wtools\common\tools\<helper>`
  3. 둘 다 없으면 `helper_unavailable`로 기록하고 직접 read-back fallback을 사용한다.
- `D:\work\project\tools\common\commit.ps1`, `commit.sh`, `version-bump.ps1`, `version-bump.sh` 같은 legacy common script는 `common\tools` helper surface가 아니다. helper missing과 섞어 판단하지 않는다.
- mirror 문서를 직접 고쳐 child 경로 문제를 해결하지 않는다. 진단은 project-owned `scripts\diagnostics\check-helper-contract.ps1`를 사용한다.

## Agent Temporary Artifacts

- agent/browser/CDP/test/dev-server probe가 만드는 disposable 산출물은 기본적으로 repo 밖 `$env:TEMP\codex\monitor-page\<plan-slug>\<timestamp>\`를 사용한다.
- repo 안에 증거를 남겨야 할 때만 ignored evidence root `.tmp/codex/<plan-slug>/<timestamp>/`를 사용한다.
- `.tmp/codex-browser-artifacts/`는 기존 browser-only evidence와의 compatibility path다. 신규 산출물은 `.tmp/codex/<plan-slug>/<timestamp>/`를 preferred path로 사용한다.
- root `tmp/`, root `temp/`, root 직하위 screenshot/json/md/evidence 파일 또는 디렉터리는 금지한다.
- 조사/검증 후 closeout 전에는 `git status --short --untracked-files=all`와 `& ".\scripts\diagnostics\check-root-artifacts.ps1"`로 산출물 잔여를 확인한다.

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
