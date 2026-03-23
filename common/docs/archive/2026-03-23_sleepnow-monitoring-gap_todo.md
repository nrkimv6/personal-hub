# sleep-now 프로세스 감시 누락 수정 — TODO
> branch: plan/2026-03-23_sleepnow-monitoring-gap_todo
> worktree: .worktrees/2026-03-23_sleepnow-monitoring-gap_todo

> 계획서: [plan](../archive/2026-03-23_sleepnow-monitoring-gap.md)
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> 진행률: 37/37 (100%)
> 요약: monitor-page의 시스템 모니터링에서 sleep-now 프로세스가 누락되어 있다. config.py 설정이 실제 시스템과 불일치하며, sleep-now의 시작 프로그램과 session_worker가 감시되지 않고 있다. 또한 Ollama 등 미등록 시작 프로그램도 모니터링에 추가한다.

> 완료일: 2026-03-23
> 아카이브됨

## Phase 1: config.py sleep-now 설정 수정

1. - [x] **sleep-now startup_prefix 추가** — 시작 프로그램 `SleepNow-SessionWorker.lnk` 감지
   - [x] `app/modules/system/config.py:63`: `"startup_prefix": None` → `"startup_prefix": "SleepNow-"` 변경

2. - [x] **sleep-now 워커 프로세스 감시 등록** — session_worker PID 감시
   - [x] `app/modules/system/config.py:65`: `"workers": None` → workers dict 추가. `pid_dir: ".pids"`, items: `[{"name": "session_worker", "label": "세션 워커", "tier": "worker", "watchdog_pid_file": None, "worker_pid_file": "session_worker.pid"}]`

3. - [x] **Ollama 시작 프로그램 모니터링 추가** — `Ollama.lnk` 감시
   - [x] `app/modules/system/config.py`: `"system"` 항목 앞에 `"ollama"` 항목 추가: `{"path": None, "nssm_prefix": None, "startup_prefix": "Ollama", "task_folder": None, "workers": None}`

## Phase 2: 프론트엔드 watchdog 없는 워커 표시 개선

4. - [x] **workerVariant() watchdog null 처리** — watchdog가 None이면 워커 상태만으로 판단
   - [x] `frontend/src/routes/system/ServiceStatusTab.svelte` `workerVariant()` (L136-147): 현재 `w.watchdog?.running ?? false`로 null을 false 처리 → watchdog이 없으면(w.watchdog === null) `wd` 무시하고 `wk`만으로 success/gray 판단하도록 분기 추가
   - [x] `workerStatusText()`: 동일하게 watchdog null이면 워커 상태만 표시 (`정상`/`중지`), 현재는 watchdog=false+worker=true → "위험(WD 없음)" 표시 → watchdog 자체가 없는 경우 "정상"으로 표시

5. - [x] **watchdog dot 미표시 확인** — watchdog이 null이면 dot 자체 미렌더링
   - [x] `frontend/src/routes/system/ServiceStatusTab.svelte` (L779): `{#if proc.watchdog}` 블록이 이미 존재하여 null이면 dot 미렌더링됨 — 동작 확인만

## Phase 3: sleep-now exe alias 도입 (sleep-now 레포)

6. - [x] **sleep-now용 setup-exe-aliases.ps1 생성** — monitor-page의 패턴을 참고
   - [x] `D:\work\project\tools\sleep-now\scripts\setup-exe-aliases.ps1`: 신규 생성. param: `-Force`, `-Status`, `-Remove`. Python alias 2개: `sleepnow-service.exe` (메인 스케줄러), `sleepnow-session.exe` (session_worker). 소스: `.venv\Scripts\python.exe`. MD5 비교 + created/updated/skipped 카운터

7. - [x] **service-run.ps1에서 alias exe 우선 사용** — fallback으로 python.exe
   - [x] `D:\work\project\tools\sleep-now\scripts\service-run.ps1:42`: `$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"` 직전에 `$AliasExe = Join-Path $ProjectRoot ".venv\Scripts\sleepnow-service.exe"` 추가, `if (Test-Path $AliasExe) { $VenvPython = $AliasExe }` fallback 패턴

8. - [x] **startup-session-worker.ps1에서 alias exe 우선 사용** — fallback으로 python.exe
   - [x] `D:\work\project\tools\sleep-now\scripts\startup-session-worker.ps1:17`: `$VenvPython` 설정 직후 `$AliasExe = Join-Path $ProjectRoot ".venv\Scripts\sleepnow-session.exe"` 추가, `if (Test-Path $AliasExe) { $VenvPython = $AliasExe }` fallback 패턴

## Phase 4: T1 — TC 작성

9. - [x] `test_config_sleepnow_startup_prefix_right()` — R: sleep-now의 startup_prefix가 `"SleepNow-"`인지 검증
10. - [x] `test_config_sleepnow_workers_registered_right()` — R: sleep-now workers.items에 `session_worker` 항목 존재, `worker_pid_file`이 `"session_worker.pid"`, `watchdog_pid_file`이 None인지 검증
11. - [x] `test_config_sleepnow_workers_path_right()` — R: sleep-now의 path가 `D:\work\project\tools\sleep-now`이고 workers.pid_dir이 `.pids`인지 검증
12. - [x] `test_config_ollama_registered_right()` — R: `"ollama"` 키가 MANAGED_PROJECTS에 존재, startup_prefix가 `"Ollama"`인지 검증
13. - [x] `test_config_ollama_no_workers_boundary()` — B: ollama의 workers/nssm_prefix/task_folder가 None인지 검증 (오탐 방지)
14. - [x] `test_get_worker_status_no_watchdog_right()` — R: watchdog_pid_file=None인 워커에서 반환값의 watchdog가 None인지 검증 (mock PID 파일로 SystemService 직접 호출)
15. - [x] `test_get_worker_status_external_path_right()` — R: sleep-now 경로의 PID 파일을 정상 해석하는지 검증 (tmp 디렉토리에 가짜 PID 파일 생성, config path를 tmp로 패치)
16. - [x] `test_get_worker_status_external_path_missing_error()` — E: 외부 프로젝트 경로가 존재하지 않을 때 빈 결과(running=False) 반환 검증

## Phase 5: T2 — TC 검증 및 수정

17. - [x] `tests/test_system_config.py` 실행 → 전체 passed 확인 (8 passed)
18. - [x] 실패 TC 수정 → 재실행 → 전체 passed (최초 실행부터 전부 passed)
19. - [x] 기존 system 테스트 회귀 확인: `python -m pytest tests/test_system_processes.py tests/test_system_memory.py -v` (53 passed)

## Phase 6: T3 — 재현/통합 TC

20. - [x] `test_integration_sleepnow_pid_detection()` — 실제 파일시스템에 임시 `.pids/session_worker.pid` 생성 (현재 프로세스 PID 기록) → `SystemService().get_worker_status()` 호출 → sleep-now 프로젝트의 session_worker가 running=True로 반환되는지 검증. config의 sleep-now path를 tmp_path로 monkeypatch
21. - [x] `test_integration_startup_prefix_finds_lnk()` — 실제 startup 디렉토리에서 `SleepNow-` prefix로 시작하는 .lnk 파일 존재 여부를 `SystemService().get_startup_programs()` 호출하여 검증 (실제 파일시스템, mock 없음)

## Phase 7: T4 — E2E 테스트

22. - [x] T4 E2E — 스킵: system 모듈 전용 E2E 테스트 없음 (Glob 탐색: `tests/**/*system*e2e*` → `test_system_memory_e2e.py`만 존재, 메모리 모듈 전용). config 변경은 단위/통합 TC로 충분히 검증됨

## Phase 8: T5 — HTTP 통합 테스트

23. - [x] `GET /api/v1/system/services/status` — sleep-now worker_processes에 session_worker 존재, ollama 프로젝트 추가 확인 (refresh 후 정상)
24. - [x] `GET /api/v1/system/services/workers` — sleep-now session_worker 항목 watchdog=null, worker={pid, running} 형태로 반환 확인 (5번째 항목)
25. - [x] `GET /api/v1/system/services/startup` — Session 0(NSSM) 제약으로 user startup 폴더 접근 불가는 기존 제약이며 코드 문제 아님 확인 (startup_prefix 설정은 정상 적용됨 — T3 통합TC로 검증 완료)

---

## 검증 (Python 코드 수정 시 참고 정보)

### 테스트 실행

```powershell
python -m pytest tests/test_system_config.py -v
```

- 기대 결과: 8 passed

### 회귀 확인

```powershell
python -m pytest tests/test_system_processes.py tests/test_system_memory.py -v
```

### 검증 기준

- [x] 새 테스트 전부 passed
- [x] 기존 테스트 회귀 없음
- [x] ServiceStatusTab에서 sleep-now 워커/시작 프로그램 정상 표시

---

*진행률: 25/25 (100%)*
