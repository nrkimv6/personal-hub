# scripts/ 인덱스

> 이 문서는 `scripts/` 하위 모든 파일의 카테고리 분류와 한 줄 설명을 제공합니다.
> 작성: 2026-04-11 (Phase 1 — 이동 없음, 문서화만)
> 관련 plan: [2026-04-11_scripts-reorganization.md](../docs/plan/2026-04-11_scripts-reorganization.md)
>
> 현재 `scripts/` 루트에는 148개 파일이 플랫하게 쌓여 있고, 하위 디렉토리 4개(`archive/`, `_deprecated/`, `dumptruck_templates/`, `__pycache__/`)가 존재합니다. 본 plan의 Phase 2~5에 걸쳐 아래 13개 카테고리 폴더로 단계적으로 이동합니다.

## 목차

- [범례](#범례)
- [services/](#services)
- [watchdogs/](#watchdogs)
- [plan_runner/](#plan_runner)
- [migrations/](#migrations)
- [diagnostics/](#diagnostics)
- [session_tools/](#session_tools)
- [cleanup/](#cleanup)
- [tests_scripts/](#tests_scripts)
- [probes/](#probes)
- [logs/](#logs)
- [fixes/](#fixes)
- [dumptruck/](#dumptruck)
- [setup/](#setup)
- [archive/ (기존)](#archive-기존)
- [_deprecated/ (기존)](#_deprecated-기존)
- [루트 유지](#루트-유지)
- [새 스크립트 추가 시 규칙](#새-스크립트-추가-시-규칙)

## 범례

| 기호 | 의미 |
|---|---|
| ⏳ | 예정 — 현재 루트에 있고, 본 plan 진행 중 이동 예정 |
| ✅ | 이동 완료 — 대상 폴더에 재배치됨 |
| ❌ | 이동 취소 / 삭제 |
| 🔴 | 운영 경로 (참조 많음, CLAUDE.md/NSSM/스킬에서 직접 참조) |
| 🟡 | 코드/테스트 import 결합 |
| 🟢 | 독립적 (참조 0~소수) |

파일명 뒤 괄호는 예정 위치 기준 상태입니다.

---

## services/

> 현재 위치: `scripts/services/` ✅ (_todo-4 완료 2026-04-12)
> 위험도: **🔴 고** — CLAUDE.md, NSSM, 스킬, 시작 프로그램에서 절대경로로 직접 참조
> 주요 외부 참조자: `CLAUDE.md`, `app/modules/system/services/worker_service.py`, `frontend/src/routes/system/ServiceStatusTab.svelte`, `docs/dev-guide/process-structure.md`, `scripts/setup-exe-aliases.ps1`, `.claude/skills/merge-test/SKILL.md`, `.agents/skills/merge-test/SKILL.md`, `tests/test_system_processes.py`, `tests/test_refactor_zombie_dedup.py`, `tests/test_process_tracker/test_snapshot_writer.py`

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `browser_workers.py` | 통합 워커 CLI 엔트리 (start/stop/status/restart/restart-api/restart-frontend). NSSM 외 수동 관리 명령 |
| ✅ | `browser-workers.ps1` | `browser_workers.py`의 PowerShell 래퍼 |
| ✅ | `run.ps1` | API + Frontend 동시 실행 (NSSM 미사용 수동 실행 경로) |
| ✅ | `start.ps1` | 서비스 시작 래퍼 (NSSM 설정 및 수동 기동) |
| ✅ | `stop.ps1` | 서비스 중지 래퍼 |
| ✅ | `service-install.ps1` | NSSM 서비스 등록 스크립트 (API/Frontend) |
| ✅ | `service-run.ps1` | NSSM AppDirectory/Application이 가리키는 진입 스크립트 |
| ✅ | `service-run.ps1.bak` | 위 파일 백업본 — 이동 시 제거 검토 |
| ✅ | `service_run.py` | `service-run.ps1`의 Python 구현 엔트리 |
| ✅ | `service_utils.py` | `service_run.py`와 `browser_workers.py`가 공유하는 유틸 |
| ✅ | `worker-command-listener.py` | API→워커 명령 리스너 (Redis pub/sub 또는 stream 기반) |
| ⏳ | `port-utils.ps1` | 포트 점유 확인 유틸 (서비스 기동 시 포트 검증) |

---

## watchdogs/

> 현재 위치: `scripts/watchdogs/` ✅ (_todo-4 완료 2026-04-12)
> 위험도: **🟡 중** — `docs/dev-guide/watchdog-architecture.md`, 시작 프로그램, NSSM에서 참조
> 주요 외부 참조자: `docs/dev-guide/watchdog-architecture.md`, `tests/test_system_status_dev_runner_listener.py`, `app/modules/system/services/worker_service.py`

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `api-watchdog.ps1` | FastAPI 서버(:8000/:8001) 헬스체크 및 재기동 |
| ✅ | `claude-watchdog.ps1` | Claude worker 프로세스 감시 |
| ✅ | `command-listener-watchdog.ps1` | `worker-command-listener.py` 감시 |
| ✅ | `crawl-watchdog.ps1` | 크롤러 프로세스 감시 |
| ✅ | `dev-runner-listener-watchdog.ps1` | `dev-runner-command-listener.py` 감시 — 내부에서 `_dr_*` 경로 spawn |
| ✅ | `llm-chat-executor-watchdog.ps1` | LLM 채팅 executor 감시 |
| ✅ | `startup-api-watchdog.ps1` | 부팅 시 api-watchdog 기동 |
| ✅ | `unified-worker-watchdog.ps1` | 통합 워커 감시 |
| ✅ | `worker-watchdog.ps1` | 범용 워커 감시 |
| ✅ | `watchdog-utils.ps1` | 위 watchdog 스크립트 공통 유틸 (로깅/pid 관리) |
| ✅ | `cleanup-zombie-processes.ps1` | 좀비/고아 프로세스 정리 — watchdog와 함께 동작하므로 watchdogs/에 귀속 |

---

## plan_runner/

> 현재 위치: `scripts/plan_runner/` ✅ (_todo-3 완료 2026-04-12)
> 위험도: **🟡 중** — Python import 밀집 결합, `tests/dev_runner/` 회귀 테스트 다수
> 엔트리: `_dr_plan_runner.py`
> Import 전략: **옵션 B (sys.path 주입)** — 각 파일에 `sys.path.insert(0, str(Path(__file__).parent))` 주입, 기존 flat import 유지
> 주요 외부 참조자: `tests/dev_runner/test_*.py` 40+개, `app/modules/dev_runner/services/plan_path_resolver.py`, `app/modules/dev_runner/tests/test_dr_plan_runner_session_arg.py`

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `_dr_plan_runner.py` | **엔트리** — plan 1개를 워크트리에서 실행하는 주 CLI |
| ✅ | `_dr_commands.py` | CLI 명령 디스패처 |
| ✅ | `_dr_constants.py` | 상수 정의 (상태, 경로, 타임아웃) |
| ✅ | `_dr_log_framing.py` | 로그 프레이밍 유틸 (start/end 마커) |
| ✅ | `_dr_merge.py` | merge 단계 로직 |
| ✅ | `_dr_plan_paths.py` | plan/archive 경로 해석 |
| ✅ | `_dr_process_utils.py` | 프로세스 spawn/kill 유틸 |
| ✅ | `_dr_runner_predicates.py` | 상태 전이 조건 판정 |
| ✅ | `_dr_runtime_utils.py` | 런타임 헬퍼 (env, cwd) |
| ✅ | `_dr_state.py` | 상태 머신 구현 |
| ✅ | `_dr_stream_cleanup.py` | 스트림 정리 단계 |
| ✅ | `_dr_subprocess.py` | subprocess 래퍼 |
| ✅ | `dev-runner-command-listener.py` | Redis stream 기반 명령 리스너 (API → plan-runner) — `_dr_*` 경로 spawn |
| ✅ | `merge_lock.py` | merge 레포 락 관리 |
| ✅ | `merge_queue.py` | merge 큐 (BRPOP 기반) |
| ✅ | `merge_workflow.py` | merge 워크플로우 orchestrator |
| ✅ | `plan_worktree_helpers.py` | plan 기반 worktree 생성/정리 헬퍼 — `_dr_*` import |
| ✅ | `workflow_manager.py` | 상위 워크플로우 매니저 |
| ✅ | `worktree_manager.py` | worktree 수명 관리 |
| ✅ | `conflict_resolver.py` | merge 충돌 자동 해결 |
| ✅ | `queue_archived_plans.py` | 아카이브된 plan 큐잉 유틸 |

---

## migrations/

> 현재 위치: `scripts/migrations/` ✅
> 위험도: **🟡 중** — `docs/dev-guide/db-migration.md`, `app/migrations/`와 연관
> 주요 외부 참조자: `CLAUDE.md` (migrations/migrate_sqlite_to_pg.py), `docs/wiki-schema.md`, `docs/plan/2026-04-10_fix-pg-instagram-posts-remigrate.md`, `docs/plan/2026-04-11_archive-db-first-rotation-and-wtools-ingest-cleanup.md`
> 제외: `queue_archived_plans.py` → `plan_runner/` (_todo-3 범위)
> 제외: `migrate-colors-phase*.py` → `fixes/` (일회성 마이그레이션, _todo-2에서 이관 완료)

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `001_url_book_data.sql` | 초기 URL 북 데이터 시드 |
| ✅ | `2025-11-30_urls.sql` | 날짜 스냅 URL 데이터 |
| ✅ | `database.sql` | 초기 스키마 |
| ✅ | `apply_migration.py` | SQL 파일 적용 유틸 |
| ✅ | `migrate_db.py` | 스키마 마이그레이션 실행기 |
| ✅ | `migrate_sqlite_to_pg.py` | SQLite → PG 데이터 이관 (2026-04-10 실행 완료) |
| ✅ | `migrate_browser_profiles.py` | 브라우저 프로필 테이블 이관 |
| ✅ | `create_archive_tables.py` | archive 전용 테이블 생성 |
| ✅ | `archive_batch_move.py` | 대량 archive 이관 배치 |
| ✅ | `archive_index_backfill.py` | archive 인덱스 backfill |
| ✅ | `verify_crawl_migration.py` | 크롤 데이터 마이그레이션 검증 |
| ✅ | `fix_pg_sequences.py` | PG serial sequence 동기화 (2026-04-11 plan 결과) |
| ✅ | `import_urls_bulk.py` | URL 대량 import |

---

## diagnostics/

> 현재 위치: `scripts/diagnostics/` ✅ (_todo-4 완료 2026-04-12)
> 예정 위치: `scripts/diagnostics/`
> 위험도: 🟢 저 — 대부분 독립적
> 대상: OS/프로세스/API 런타임 진단

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `_diag_find_cdb.ps1` | CDB(Windows 디버거) 설치 경로 탐색 |
| ✅ | `_diag_reboot.ps1` | 재부팅 원인 분석 |
| ✅ | `_diag_reboot2.ps1` | 재부팅 원인 분석 v2 |
| ✅ | `_diag_reboot3.ps1` | 재부팅 원인 분석 v3 |
| ✅ | `_check_plan_data.py` | plan DB 데이터 검증 |
| ✅ | `_check_visible.py` | visible 상태 검증 |
| ✅ | `analyze_duplicates.py` | DB 중복 분석 |
| ✅ | `analyze-dump.ps1` | 메모리 덤프 분석 |
| ✅ | `check_profile_config.py` | 브라우저 프로필 설정 검증 |
| ✅ | `check_requests.py` | 요청 로그 검사 |
| ✅ | `check_schedules.py` | 스케줄 상태 점검 |
| ✅ | `check_slots.py` | 슬롯 상태 점검 |
| ✅ | `debug_sse_log.py` | SSE 로그 디버그 |
| ✅ | `debug_sse_log2.py` | SSE 로그 디버그 v2 |
| ✅ | `diagnose-api.ps1` | API 진단 스크립트 — api-watchdog.ps1에서 참조, _todo-6에서 이관 완료 |
| ✅ | `ps-python-processes.ps1` | 파이썬 프로세스 트리 출력 |
| ✅ | `show-processes.ps1` | 프로세스 요약 출력 |
| ✅ | `test_pg_connection.py` | PG 연결 확인 (진단용 — migrations 아님) |
| ✅ | `register_process.py` | 프로세스 등록/추적 유틸 |

---

## session_tools/

> 현재 위치: `scripts/session_tools/` ✅
> 예정 위치: `scripts/session_tools/`
> 위험도: 🟢 저
> 대상: `.claude/projects/*.jsonl` 세션 메타 파싱 (Claude Code 산출물)
> 배경: 2026-04-11 재부팅 원인 분석 과정에서 `_tmp_*.py` 6개가 한 세션 내 2회 이상 재사용 발생 → 정식 카테고리로 승격. 접두사 제거 + `session_*` rename.
> 수명 규칙: **archive 이관 제외** (장기 재사용 전제)

| 상태 | 현 파일 | 원본 이름 | 설명 |
|:-:|---|---|---|
| ✅ | `session_dump.py` | `_tmp_dump_session.py` | 세션 jsonl 전체 덤프 |
| ✅ | `session_get_line.py` | `_tmp_get_line.py` | 특정 라인 번호 덤프 |
| ✅ | `session_search.py` | `_tmp_search_sessions.py` | 키워드 기반 세션 검색 |
| ✅ | `session_find_by_file.py` | `_tmp_find_archive_db_session.py` | 파일명(archive db 등) 기반 세션 역추적 |
| ✅ | `session_find_by_topic.py` | `_tmp_find_scripts_session.py` | 주제(scripts 등) 기반 세션 역추적 |
| ✅ | `session_scan_by_time.py` | `_tmp_scan_all_bsod.py` | 시간 범위(BSOD 주변) 세션 스캔 |

---

## cleanup/

> 현재 위치: `scripts/cleanup/` (`kill-orphan-procs.ps1` 제외)
> 위험도: **🟡 중** — 수동 실행 + 일부 daily_maintenance 연동
> 제외: `kill-orphan-procs.ps1` — `.claude/skills/implement/SKILL.md`, `.claude/skills/done/SKILL.md`, `.claude/agents/auto-impl.md`, `.claude/agents/auto-done.md`에서 절대경로 `scripts/kill-orphan-procs.ps1` 참조. monitor-page에서 `.claude/*` 직접 수정 금지 규칙에 따라 wtools 스킬 업데이트 선행 필요. 현재 `scripts/` 루트 유지. (추가: `scripts/port-utils.ps1` 포함, 포트 정리 유틸)

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `cleanup_chrome.ps1` | Chrome 잔여 프로세스 정리 |
| ✅ | `cleanup_invisible_recent_runners.py` | invisible runner DB 정리 |
| ✅ | `cleanup_old_branches.py` | 오래된 impl/* 브랜치 정리 |
| ✅ | `cleanup_test_runners.py` | 테스트용 runner DB 정리 |
| ✅ | `cleanup-stale-worktrees.ps1` | stale 워크트리 정리 |
| ✅ | `clear_death_log.py` | death log 초기화 |
| ✅ | `kill_all.ps1` | 전체 프로세스 강제 종료 (start/stop 이후 정리용) |
| ✅ | `port-utils.ps1` | 좀비 포트 탐지/정리 공용 모듈 |
| ⏳ | `kill-orphan-procs.ps1` | 고아 pytest 프로세스 정리 (`/implement` 선제 정리) — wtools 스킬 경로 수정 후 이관 |

---

## tests_scripts/

> 현재 위치: `scripts/tests_scripts/` ✅
> 위험도: 🟢 저
> 참고: `tests/` 는 pytest 본체, `tests_scripts/`는 **수동/보조 테스트 스크립트**
> 주요 외부 참조자: `tests/dev_runner/README.md`, `tests/integration/__init__.py`, `tests/integration/test_api_integration.py`, `docs/dev-guide/troubleshooting.md` (경로 갱신됨)
> pytest 수집 제외: `pytest.ini`의 `testpaths = tests`로 `scripts/tests_scripts/`는 자동 수집 안 됨 — 수동 실행 전용

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `test.ps1` | `run.ps1` 기반 수동 테스트 실행 |
| ✅ | `coverage.ps1` | 커버리지 측정 래퍼 |
| ✅ | `run-e2e-tests.ps1` | E2E 테스트 배치 실행 |
| ✅ | `recovery-process-watch-smoke.ps1` | 복구 프로세스 watch 스모크 |
| ✅ | `test-dev-runner-batch.ps1` | dev-runner 배치 스모크 |
| ✅ | `test_browser_profile.py` | 브라우저 프로필 수동 테스트 |
| ✅ | `test_classify.py` | 분류 수동 테스트 |
| ✅ | `test_classify_direct.py` | 분류 직접 호출 테스트 |
| ✅ | `test_phase4.py` | phase4 테스트 스크립트 |
| ✅ | `test_phase4_check.py` | phase4 검증 |
| ✅ | `test_phase4_run.py` | phase4 실행 |

---

## probes/

> 현재 위치: `scripts/probes/` ✅
> 예정 위치: `scripts/probes/`
> 위험도: 🟢 저 — 모두 일회성 외부 서비스 탐사 스크립트
> Phase 2 참고: `coupang_travel_api_feasibility.py` 이동 시 `tests/utils/test_coupang_travel_api_feasibility.py` import 경로 함께 수정

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `coupang_browser_profile_runner.py` | 쿠팡 브라우저 프로필 runner 탐사 |
| ✅ | `coupang_cdp_session_probe.py` | 쿠팡 CDP 세션 탐사 |
| ✅ | `coupang_credentials_probe.py` | 쿠팡 로그인 자격증명 탐사 |
| ✅ | `coupang_login_access_matrix.py` | 쿠팡 로그인 접근 매트릭스 |
| ✅ | `coupang_network_probe.py` | 쿠팡 네트워크 요청 탐사 |
| ✅ | `coupang_proxy_manager_probe.py` | 쿠팡 proxy manager 탐사 |
| ✅ | `coupang_travel_api_feasibility.py` | 쿠팡 travel API 가능성 조사 (test import 갱신됨) |
| ✅ | `naver_popup_ssr_probe.py` | 네이버 popup SSR 탐사 |

---

## logs/

> 현재 위치: `scripts/logs/` ✅ (_todo-4 완료 2026-04-12, listener_noise_filter.py → plan_runner/)
> 위험도: **🔴 고** — `CLAUDE.md`, `docs/dev-guide/logs-ps1.md`, `docs/dev-guide/troubleshooting.md`, 다수 archive 문서에서 `.\scripts\logs.ps1 -Follow -Admin` 직접 호출
> 주요 외부 참조자: `CLAUDE.md`, `docs/dev-guide/troubleshooting.md`, `docs/dev-guide/logs-ps1.md`, `tests/logs_follow_fallback.Tests.ps1`, `scripts/start.ps1`

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `logs.ps1` | 핵심 로그 뷰어 (`-Follow`, `-Admin`, `-Public`, `-TailLines`) |
| ✅ | `startup-logs.ps1` | 부팅 시 로그 로테이션/초기화 |
| ✅ | `split-cloudflared-log.ps1` | cloudflared 로그 분할 |
| ✅ | `setup-log-cleanup-task.ps1` | 로그 정리 작업 등록 (Task Scheduler) |
| ✅ | `cleanup-logs.ps1` | 로그 정리 스크립트 |
| ⏳ | `listener_noise_filter.py` | listener 로그 노이즈 필터 |
| ⏳ | `Send-TelegramAlert.ps1` | 텔레그램 알림 전송 (운영 알림) |

---

## fixes/

> 현재 위치: `scripts/fixes/` ✅ (_todo-6 완료 2026-04-12)
> 예정 위치: `scripts/fixes/`
> 위험도: 🟢 저 — 일회성 픽스, 수명 후 archive/로 이동
> 수명 규칙: 작업 완료 후 30일 내 `scripts/archive/`로 이관 (→ [일회성 스크립트 수명 규칙](#일회성-스크립트-수명-규칙))
> 재분류: `frontend_placeholder.py` → `scripts/fixes/` (service_run.py 참조이나 service_run 자체가 services/에 있어 함께 이관)

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `_fix_dev_runner.ps1` | dev-runner 일회성 픽스 |
| ✅ | `_fix_plan_header.py` | plan 헤더 일괄 수정 |
| ✅ | `_fix_planlist.ps1` | plan 목록 일괄 수정 v1 |
| ✅ | `_fix_planlist2.ps1` | plan 목록 일괄 수정 v2 |
| ✅ | `_fix_tabs.ps1` | 탭 정렬 일괄 수정 |
| ✅ | `_fix_tracking.ps1` | tracking 상태 일괄 수정 v1 |
| ✅ | `_fix_tracking2.ps1` | tracking 상태 일괄 수정 v2 |
| ✅ | `fix_event_dates.py` | 이벤트 날짜 일회성 보정 |
| ✅ | `fix-button-case.py` | 버튼 케이스 일괄 수정 |
| ✅ | `fix-button-mismatch-final.py` | 버튼 불일치 최종 수정 |
| ✅ | `fix-button-tags.py` | 버튼 태그 일괄 수정 |
| ✅ | `fix-event-modifiers.py` | 이벤트 modifier 일괄 수정 |
| ✅ | `fix-variant-size.py` | variant size 일괄 수정 |
| ✅ | `migrate-colors-phase1.py` | 프론트 색상 마이그레이션 Phase 1 |
| ✅ | `migrate-colors-phase2.py` | 프론트 색상 마이그레이션 Phase 2 |
| ✅ | `migrate-colors-phase3.py` | 프론트 색상 마이그레이션 Phase 3 |
| ✅ | `create_icons.py` | 아이콘 생성 일회성 유틸 |
| ✅ | `extract_keywords.py` | 키워드 추출 일회성 유틸 |
| ✅ | `frontend_placeholder.py` | 프론트엔드 placeholder 서버 — service_run.py 참조, _todo-6에서 fixes/로 이관 완료 |
| ✅ | `disable_duplicate_events.py` | 중복 이벤트 비활성화 일회성 수정 |

---

## dumptruck/

> 현재 위치: `scripts/` + `scripts/dumptruck_templates/` (**이관 보류**)
> 예정 위치: `scripts/dumptruck/` (templates 포함)
> 위험도: 🟢 저
> 외부 참조자: `.claude/skills/dumptruck/SKILL.md`에서 `scripts/dumptruck_run.ps1`, `scripts/dumptruck_builder.py` 절대경로 참조
> 🔴 이관 보류: monitor-page에서 `.claude/skills/*` 직접 수정 금지 규칙에 따라 wtools 레포의 dumptruck 스킬 경로 업데이트가 선행되어야 한다. wtools 스킬 수정 + pull-sync 이후 별도 이관.

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ⏳ | `dumptruck_run.ps1` | Gemini Pro oneshot 실행 래퍼 — wtools 스킬 업데이트 후 이관 |
| ⏳ | `dumptruck_builder.py` | dumptruck 프롬프트 빌더 — wtools 스킬 업데이트 후 이관 |
| ⏳ | `dumptruck_templates/architecture.md` | 아키텍처 분석 템플릿 |
| ⏳ | `dumptruck_templates/conflict.md` | 충돌 분석 템플릿 |
| ⏳ | `dumptruck_templates/logdump.md` | 로그 덤프 템플릿 |
| ⏳ | `dumptruck_templates/refactor.md` | 리팩토링 템플릿 |

---

## setup/

> 현재 위치: `scripts/setup/` ✅
> 위험도: **🟡 중** — 시작 프로그램/작업 스케줄러에 등록됨
> 주요 외부 참조자: `CLAUDE.md`(없음 — 간접), `CHANGELOG.md`, `GEMINI.md`, `docs/dev-guide/process-structure.md`, `docs/dev-guide/watchdog-architecture.md` (경로 갱신됨)
> 비고: NSSM 서비스 경로는 변경 없음 (`setup/` 아래로 이동된 파일 중 NSSM 등록 대상은 없음). `startup-install.ps1`/`startup-browser-workers.ps1`는 시작 프로그램 바로가기 — `-Action status`로 Browser Workers stale path를 확인하고, 재설치 필요 시 `.\scripts\setup\startup-install.ps1 -Action install -IncludeWorkers` 재실행.

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ✅ | `_build_worktree.ps1` | 워크트리 빌드 (venv/node_modules) 헬퍼 |
| ✅ | `_setup_worktree_build.ps1` | 워크트리 빌드 환경 셋업 |
| ✅ | `setup-exe-aliases.ps1` | PowerShell exe alias 설치 |
| ✅ | `startup-install.ps1` | 사용자 시작 프로그램 등록 |
| ✅ | `startup-browser-workers.ps1` | 부팅 시 통합 워커 기동 |
| ✅ | `daily_maintenance.ps1` | 일일 유지보수 작업 (cleanup 연동) |
| ✅ | `claude-session-manager.ps1` | Claude Code 세션 관리 헬퍼 |
| ✅ | `auto-update.ps1` | 자동 업데이트 훅 |
| ✅ | `Send-TelegramAlert.ps1` | 텔레그램 알림 함수 (watchdog crash-loop 감지 등에서 dot-source) |

---

## archive/ (기존)

> 현재 위치: `scripts/archive/`
> 예정 위치: `scripts/archive/` (유지)
> 설명: 이전 재구성 산물. 본 plan에서 **폐기된 스크립트 이관 대상지**로 계속 사용.

| 상태 | 파일 | 설명 |
|:-:|---|---|
| (기존) | `archive/_copy_dev_to_admin.ps1` | dev → admin 복사 일회성 스크립트 (과거) |
| (기존) | `archive/_rename_dev_to_admin.ps1` | dev → admin rename 일회성 스크립트 (과거) |
| ✅ | `archive/commit.ps1` | 레거시 — `D:\work\project\tools\common\commit.ps1`로 대체. _todo-5에서 archive/로 이관 완료 |
| ⏳(이관 검토) | `service-run.ps1.bak` | 백업본 — archive/ 또는 삭제 검토 (_todo-4) |

---

## _deprecated/ (기존)

> 현재 위치: `scripts/_deprecated/`
> 예정 위치: `scripts/_deprecated/` (유지)

| 상태 | 파일 | 설명 |
|:-:|---|---|
| (기존) | `_deprecated/merge_workflow.py` | 이전 merge_workflow 구현본 (현재 `scripts/merge_workflow.py`와 별개) |

---

## 루트 유지

| 파일 | 설명 |
|---|---|
| `README_브라우저_프로필.md` | 브라우저 프로필 사용 가이드 — 루트 유지 (문서) |
| `INDEX.md` | 본 파일 — scripts/ 인덱스 |

### 이관 보류 (wtools 선행 필요)

아래 파일은 `.claude/skills/dumptruck/SKILL.md`가 절대경로로 참조하므로, wtools 레포에서 스킬 경로 업데이트 + pull-sync 이후에만 이관 가능.

| 상태 | 파일 | 설명 |
|:-:|---|---|
| ⏳ | `dumptruck_run.ps1` | → `scripts/dumptruck/` 예정 |
| ⏳ | `dumptruck_builder.py` | → `scripts/dumptruck/` 예정 |
| ⏳ | `kill-orphan-procs.ps1` | → `scripts/cleanup/` 예정 (wtools kill-orphan 스킬 참조) |

---

## 미분류

현재 없음. Phase 2~5 진행 중 분류 애매 파일 발견 시 이 섹션에 기록.

---

## 새 스크립트 추가 시 규칙

1. **신규 파일은 반드시 카테고리 폴더에 생성** — `scripts/` 루트 직접 생성 금지
2. **파일명 접두사 → 카테고리 폴더** 매핑 표를 참조해 적합한 폴더에 생성

| 접두사 / 패턴 | 카테고리 폴더 | 예시 |
|---|---|---|
| `_dr_*.py` | `plan_runner/` | `_dr_plan_runner.py` |
| `*-watchdog.ps1` | `watchdogs/` | `api-watchdog.ps1` |
| `migrate_*.py`, `migrate-*.py`, `*.sql` | `migrations/` | `migrate_sqlite_to_pg.py` |
| `cleanup*`, `kill*`, `clear_*` | `cleanup/` | `cleanup-zombie-processes.ps1` |
| `test_*.py`, `test-*.ps1`, `*-e2e-*` | `tests_scripts/` | `run-e2e-tests.ps1` |
| `coupang_*`, `naver_*` | `probes/` | `coupang_network_probe.py` |
| `_diag_*`, `debug_*`, `_check_*`, `diagnose-*`, `analyze-*`, `show-*`, `ps-*` | `diagnostics/` | `_diag_reboot.ps1` |
| `session_*.py` (`.claude/projects/*.jsonl` 파싱) | `session_tools/` | `session_dump.py` |
| `_fix_*`, `fix-*`, `fix_*` (일회성) | `fixes/` | `_fix_plan_header.py` |
| `dumptruck_*` | `dumptruck/` | `dumptruck_run.ps1` |
| `setup-*`, `startup-*`, `daily_*`, `auto-update*`, `_build_*`, `_setup_*` | `setup/` | `setup-exe-aliases.ps1` |
| 서비스 런타임 (`start/stop/run/service*/browser_workers`) | `services/` | `browser_workers.py` |
| 로그 도구 (`logs*`, `*-log*.ps1`, `*noise_filter*`) | `logs/` | `logs.ps1` |

3. **`_tmp_` 접두사 사용 금지**
   - 배경: 2026-04-11 사고 — "일회성"이라 생각한 7개 `_tmp_*.py`가 한 세션 내 2회 이상 재사용되며 루트를 오염시킴
   - 대신: 2회 이상 재사용 가능성이 있으면 **즉시 카테고리 폴더에 의미 있는 이름**으로 생성
   - 정말로 단발 실행 후 버릴 예정이면 `scripts/scratch/`(gitignore 대상) 또는 `/tmp`에 작성 — 저장소에 커밋 금지
4. **INDEX.md에 한 줄 설명과 참조자(있다면) 등재 후 커밋**

---

## 일회성 스크립트 수명 규칙

`fixes/`, `diagnostics/` 하위의 `_fix_*`, `_diag_*` 파일에 적용:

1. 작업 완료 후 **30일 내 `scripts/archive/`로 이동**
2. 이동 시 INDEX.md 해당 라인 삭제
3. `scripts/archive/`의 파일은 복구 목적으로만 존재, 정기 실행 금지
4. 새 `_fix_*`/`_diag_*` 생성 시 파일 상단 주석에 **"생성일 + 목적 + 예상 수명"** 기재
5. **`session_tools/`는 수명 규칙 적용 제외** — 세션 메타 도구는 장기 재사용 전제, archive 이동 금지

---

*상태: Phase 1~6 완료 | 작성: 2026-04-11 | 마지막 갱신: 2026-04-12 (_todo-6)*
