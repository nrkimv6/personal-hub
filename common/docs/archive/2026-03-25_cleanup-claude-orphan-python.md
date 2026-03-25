# Claude Code 고아 Python 프로세스 정리

> 작성일: 2026-03-25
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-25_cleanup-claude-orphan-python
> worktree: .worktrees/2026-03-25_cleanup-claude-orphan-python
> 진행률: 10/10 (100%)
> 요약: Claude Code가 스폰한 pyenv 글로벌 Python 프로세스가 고아로 남아 5GB+ 메모리를 점유하는 문제. cleanup-zombie-processes.ps1에 부모 프로세스 사망 기반 정리 섹션을 추가한다.

> 완료일: 2026-03-25
> 아카이브됨

---

## 개요

Claude Code(또는 기타 도구)가 pyenv 글로벌 Python(`C:\Users\Narang\.pyenv\...`)을 스폰하는데, 부모 프로세스가 종료된 후에도 자식 python.exe가 살아남아 고아가 된다.

기존 고아 정리 메커니즘이 이를 못 잡는 이유:
- **OrphanDetector** (Python 런타임): ProcessRegistry에 등록된 프로세스만 추적 → pyenv python은 등록된 적 없음
- **cleanup-zombie-processes.ps1** (수동): `CommandLine -like '*monitor-page*'` 조건 → pyenv python의 CommandLine에 "monitor-page"가 없어 스킵

### 범인 프로필 (2026-03-25 실제 사례)

| 항목 | 값 |
|------|------|
| PID | 22544 |
| 실행 파일 | `C:\Users\Narang\.pyenv\pyenv-win\versions\3.12.1\python.exe` |
| 메모리 | 5GB+ |
| monitor-page 프로세스 | 아님 (.venv 사용하지 않음) |
| 부모 프로세스 | 이미 사망 (고아 상태) |

## 기술적 고려사항

- pyenv python은 monitor-page `.venv` 외부 → 기존 필터링 조건에 안 걸림
- 부모 프로세스 사망 여부(`ParentProcessId`)로 판별해야 함
- **제외 대상**: 부모가 살아있는 정상 python, 서비스로 등록된 python
- WMI(`Get-CimInstance Win32_Process`)가 느릴 수 있음 → 이미 이 스크립트가 WMI 사용 중이라 추가 부담 적음
- `monitorpage-*` exe와 `.venv\Scripts\python.exe`는 기존 섹션 [3]에서 처리 → 중복 방지 필요

### 방법 B 참고 (미구현, 아이디어)

OrphanDetector에 시스템 레벨 스캔을 추가하는 방법도 있다. psutil로 pyenv python 프로세스를 직접 스캔하고 부모가 없으면 정리. 단, OrphanDetector는 자체 Registry 기반 설계이므로 책임 범위가 달라져 현재는 채택하지 않음. 향후 Registry 외부 프로세스까지 관리가 필요해지면 재검토.

---

## TODO

### Phase 1: cleanup-zombie-processes.ps1에 섹션 [4] 추가

1. - [x] **섹션 [4] 고아 Python 스캔 블록 삽입** — L101 `if ($pythonProcs)...` 뒤, `# --- Results ---` 앞에 삽입
   - [x] `scripts\cleanup-zombie-processes.ps1`: `# --- 4. Orphan python (parent dead) ---` 헤더 + `Write-Host "[4] Scanning orphan python (parent dead)..."` 추가
   - [x] `scripts\cleanup-zombie-processes.ps1`: 기존 섹션 [1]-[3]에서 이미 수집된 PID를 `$alreadyTargeted` HashSet으로 수집 (중복 방지용) — `$AllTargets | ForEach-Object { $_.PID }` 로 추출
   - [x] `scripts\cleanup-zombie-processes.ps1`: `Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' }` 로 모든 python 프로세스 조회 후, 각각에 대해:
     - `$alreadyTargeted`에 있으면 스킵 (섹션 [1]-[3] 중복 방지)
     - `$_.Name -like 'monitorpage-*'` 이면 스킵 (섹션 [3] 영역)
     - `$_.CommandLine -like '*monitor-page*'` 이면 스킵 (섹션 [3] 영역)
     - `ParentProcessId`로 `Get-Process -Id $ppid -ErrorAction SilentlyContinue` 시도 → 부모가 살아있으면 스킵
     - `StartTime`이 `$Cutoff` 이후면 스킵 (`$MaxAgeHours` 미만)
   - [x] `scripts\cleanup-zombie-processes.ps1`: 통과한 프로세스를 `[PSCustomObject]@{ Type='orphan-python'; PID; MemMB; StartTime; Age; Command }` 로 생성, `$AllTargets`에 추가

### Phase 2: 수동 검증

2. - [x] **dry-run 실행으로 동작 확인**
   - [x] 현재 살아있는 PID 15336 (pyenv python, 부모 사망)이 Type='orphan-python'으로 출력되는지 확인
   - [x] 정상 서비스 python (PID 2000 등 `.venv` python)이 나오지 않는지 확인
   - [x] monitorpage-* 프로세스가 섹션 [4]에 중복 출력되지 않는지 확인

### Phase 3: 커밋

3. - [x] 커밋: `feat: cleanup-zombie에 부모 사망 고아 python 정리 섹션 추가`

---

*상태: 구현완료 | 진행률: 10/10 (100%)*
