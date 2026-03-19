# sync_plans() archive 불필요 스캔 제거

> 작성일: 2026-03-13
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-13_fix-sync-plans-archive-scan
> worktree: .worktrees/2026-03-13_fix-sync-plans-archive-scan
> 진행률: 16/16 (100%)
> 반영일: 2026-03-13 00:46
> 머지커밋: 5e2d80ed
> 요약: sync_plans()가 include_ignored=True로 archive 포함 1302개 파일을 2번 스캔하여 30초 타임아웃 발생. archive는 sync 대상이 아니므로 제거.

> 완료일: 2026-03-19
> 아카이브됨

---

## 개요

### 문제

`POST /api/v1/dev-runner/plans/sync` 호출 시 `plan_service.sync_plans()`가 `list_plans(include_ignored=True)`를 **2회** 호출한다. `include_ignored=True`는 archive 경로까지 전체 스캔하므로 1302개 `.md` 파일을 읽고 체크박스를 파싱한다.

- 정상 시 약 2초, 부하 시 30초 타임아웃 발생
- archive는 완료된 plan이므로 sync(변경 감지) 대상이 아님

### 근본 원인

`plan_service.py:1223, 1230` — `sync_plans()`가 `include_ignored=True`로 호출하여 archive 파일까지 스캔.

## 기술적 고려사항

- `include_ignored=True` → `False`로 변경하면 archive 스캔 자체를 건너뜀 (`_scan_all_plans:228`)
- sync의 목적은 "활성 plan의 변경 감지"이므로 archive 포함은 불필요
- `_archive_cache.clear()`도 함께 제거 가능 (archive 스캔 안 하면 캐시도 불필요)
- 프론트엔드 `handleSync`의 30초 타임아웃은 유지 (정상이면 1초 이내 응답)

---

## TODO

### Phase 1: sync_plans archive 스캔 제거

1. - [x] **sync_plans()에서 include_ignored=True 제거** — archive 포함 스캔을 활성 plan만 스캔으로 변경
   - [x] `app/modules/dev_runner/services/plan_service.py:1223`: `self.list_plans(include_ignored=True)` → `self.list_plans()` 변경 (old snapshot)
   - [x] `app/modules/dev_runner/services/plan_service.py:1230`: `self.list_plans(include_ignored=True)` → `self.list_plans()` 변경 (new snapshot)
   - [x] `app/modules/dev_runner/services/plan_service.py:1229`: `self._archive_cache.clear()` 행 삭제 (archive 스캔 안 하므로 캐시 무효화 불필요)

### Phase T1: TC 작성

2. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_sync_plans_right_excludes_archive()` — R(정상): plan_dir에 plan 2개 + archive_dir에 archive 3개 등록 → `sync_plans()` 호출 → `synced` 수가 plan만 포함(archive 제외) 확인
3. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_sync_plans_right_detects_added_plan()` — R(정상): sync 전 plan 1개 → 디스크에 plan 추가 → 캐시 무효화 → 재 sync → `added=1` 확인
4. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_sync_plans_right_detects_updated_status()` — R(정상): plan 파일의 `> 상태:` 변경 후 sync → `updated=1` 확인
5. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_sync_plans_boundary_empty_plan_dir()` — B(경계): 등록 경로에 .md 파일 없음 → `synced=0, added=0, removed=0, updated=0` 반환
6. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_sync_plans_error_nonexistent_path()` — E(에러): 존재하지 않는 경로 등록 상태에서 sync → 에러 없이 정상 반환

### Phase T2: TC 검증 및 수정

7. - [x] `python -m pytest tests/dev_runner/test_plan_service_sync.py -v` 실행 → 6 passed 확인
8. - [x] 실패 TC 수정 후 재실행 (보류→초안 상태 변경으로 1건 수정)
9. - [x] `python -m pytest tests/dev_runner/ --ignore=tests/dev_runner/test_plan_service_sync.py` 회귀 확인 (기존 실패 test_auto_resolve_abort_bug.py는 main에서도 동일 실패 — 무관)

### Phase T3: 재현/통합 TC

10. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_sync_plans_integration_real_filesystem()` — 실제 tmp 디렉토리에 plan_dir + archive_dir 생성, `.md` 파일 배치, plan_service 인스턴스 생성 → `sync_plans()` 호출 → archive 파일이 synced에 포함되지 않음을 검증 (mock 없이 실제 파일시스템 사용)

### Phase T4: E2E 테스트

- [x] T4 E2E — 스킵: `tests/e2e/` 탐색 결과 dev-runner sync 관련 E2E 없음. 내부 서비스 로직만 변경, API 인터페이스 동일

### Phase T5: HTTP 통합

11. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_http_post_sync_plans_response_structure()` — `POST /api/v1/dev-runner/plans/sync` → 200 응답, `synced`/`added`/`removed`/`updated` 키 존재 확인
12. - [x] `tests/dev_runner/test_plan_service_sync.py`: `test_http_post_sync_plans_excludes_archive_count()` — `POST /api/v1/dev-runner/plans/sync` → `synced` 값이 활성 plan 수와 일치 (archive 포함 수보다 작음)

---

## 검증 (Python 코드 수정 시 참고 정보)

### 테스트 실행

```powershell
python -m pytest tests/test_plan_service_sync.py -v --timeout=30
```

- 기대 결과: 8 passed

### 회귀 확인

```powershell
python -m pytest tests/ -v --timeout=30 --ignore=tests/test_plan_service_sync.py
```

---

*상태: 구현완료 | 진행률: 16/16 (100%)*
