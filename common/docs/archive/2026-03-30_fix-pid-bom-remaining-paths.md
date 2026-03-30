# fix: PID BOM 파싱 미처리 경로 2곳 추가 수정

> 상태: 구현완료
> branch: plan/2026-03-30_fix-pid-bom-remaining-paths
> worktree: .worktrees/2026-03-30_fix-pid-bom-remaining-paths
> 우선순위: P1
> 난이도: 낮음
> 요약: _read_pid_status BOM 수정 후 발견된 동일 패턴 2곳 — _kill_pid_file(system_service.py:323)와 health_monitor_service.py:138도 utf-8-sig로 통일
> 진행률: 22/22 (100%)
> 출처: /reflect에서 자동 생성

> 완료일: 2026-03-30
> 아카이브됨

## 배경

`_read_pid_status`의 BOM 수정(`utf-8-sig`) 이후 `/reflect`에서 동일 패턴 2곳 추가 발견:

| 위치 | 코드 | 영향 |
|------|------|------|
| `system_service.py:323` (`_kill_pid_file`) | `pid_file.read_text().strip()` | 워커 재시작 시 BOM PID 파일이면 kill 실패 |
| `health_monitor_service.py:138` | `pid_file.read_text().strip()` | 상태 모니터에서 BOM PID 파일이면 None 반환 → 헬스체크 오탐 |

두 경로 모두 외부 프로젝트(sleep-now 등)의 PID 파일을 읽을 수 있으면 동일하게 영향받음.

## 수정 대상

| 파일 | 변경 |
|------|------|
| `app/modules/system/services/system_service.py:323` | `read_text()` → `read_text(encoding='utf-8-sig')` |
| `app/services/health_monitor_service.py:138` | `read_text()` → `read_text(encoding='utf-8-sig')` |

---

## TODO

### Phase 1: BOM 미처리 경로 수정

1. - [x] **`_kill_pid_file` BOM 수정**
   - [x] `app/modules/system/services/system_service.py:323`: `pid_file.read_text().strip()` → `pid_file.read_text(encoding='utf-8-sig').strip()`

2. - [x] **`health_monitor_service` BOM 수정**
   - [x] `app/services/health_monitor_service.py:138`: `pid_file.read_text().strip()` → `pid_file.read_text(encoding='utf-8-sig').strip()`

### Phase R: 재발 경로 분석 (fix: plan 필수)

3. - [x] **`read_text()` + PID 파싱 패턴 전수 조사**
   - [x] Grep으로 프로젝트 전체 `read_text()` + 정수 변환 패턴 검색 — 추가 누락 없는지 확인
   - [x] 모든 경로 방어됨 확인 후 표 작성 (경로 | 방어여부 | 근거)

4. - [x] **미방어 경로 수정**
   - [x] 추가 미방어 경로 발견 시 동일하게 `utf-8-sig` 적용
   - [x] 전체 방어 완료 확인

### Phase T1: TC 작성

5. - [x] **`_kill_pid_file` BOM TC** (`tests/test_system_service_pid.py`에 추가)
   - [x] `test_kill_pid_file_with_bom()` — R(Right): BOM 포함 PID 파일에서 `_kill_pid_file` 호출 → 파싱 성공 (taskkill subprocess는 mock)
   - [x] `test_kill_pid_file_garbage()` — E(Error): 숫자 아닌 내용 → `(False, "...")`

6. - [x] **`health_monitor_service` BOM TC** (`tests/test_health_monitor_pid_bom.py` 신규)
   - [x] `test_read_pid_bom()` — R(Right): BOM 포함 PID 파일 → 정수 반환
   - [x] `test_read_pid_normal()` — R(Right): 정상 PID 파일 → 정수 반환
   - [x] `test_read_pid_missing()` — B(Boundary): 파일 없음 → None 반환

### Phase T2: TC 검증 및 수정

7. - [x] **TC 실행 및 통과 확인**
   - [x] `pytest tests/test_system_service_pid.py tests/test_health_monitor_pid_bom.py -v` → 전부 passed (14 passed)
   - [x] 기존 system 관련 회귀 확인: `pytest tests/test_system_config.py tests/test_system_service_nssm.py -v` → 16 passed

### Phase T3: 재현/통합 TC

8. - [x] **BOM PID 재현 통합 — _kill_pid_file** (`tests/test_system_service_pid.py`에 추가)
   - [x] `test_kill_pid_file_bom_real()` — 실제 tmp 파일에 BOM PID 기록 → `_kill_pid_file` 호출 → 파싱 성공 확인 (mock 없이 파일 I/O 실물)

> T4 E2E 해당 없음: 상태 조회 엔드포인트는 기존 `test_system_status_http.py`가 커버. 이번 수정은 내부 kill/읽기 로직만 변경, HTTP 응답 형식 변경 없음
> T5 HTTP 통합 해당 없음: API 엔드포인트 변경 없음

---

> 진행률: 22/22 (100%)
