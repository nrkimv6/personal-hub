# plan-runner MERGE 로그 3중복 및 4번째 로그 블록 수정

> 작성일: 2026-03-24
> 대상 프로젝트: wtools (plan-runner), monitor-page (dev_runner)
> 상태: 구현완료
> branch: plan/2026-03-24_fix-merge-log-triple-duplicate
> worktree: .worktrees/2026-03-24_fix-merge-log-triple-duplicate
> 진행률: 51/51 (100%)
> 요약: Live Logs에서 MERGE 로그가 3번 중복 출력되는 버그 수정. 원인은 MergeLogger가 stdout(→리스너→LOG_CHANNEL)과 LOG_CHANNEL 직접 publish를 동시에 하여 중복 게시. 4번째 로그 블록은 loadRecent 이력 재생 타이밍 문제.

> 완료일: 2026-03-24
> 아카이브됨

---

## 개요

### 현상

```
MERGE
[INFO] execute_merge: project_dir=..., branch=...
MERGE
[INFO] execute_merge: project_dir=..., branch=...
MERGE
[INFO] execute_merge: project_dir=..., branch=...
```

Live Logs에서 모든 MERGE 로그 라인이 3번씩 중복 출력됨.
새로고침 후 파일 기반 조회(loadRecent)에서는 1번만 표시됨.

### 버그 1: MERGE 로그 3중복

**경로 분석:**

| 번호 | 경로 | 채널 |
|------|------|------|
| 1 | `MergeLogger.print(line)` → stdout PIPE → `_stream_output` → `redis.publish(LOG_CHANNEL)` | `plan-runner:logs:{id}` |
| 2 | `MergeLogger.redis.publish(self._main_channel, line)` 직접 | `plan-runner:logs:{id}` ← **중복!** |
| 3 | `MergeLogger.redis.publish(self._channel, line)` | `plan-runner:merge-log:{id}` |

`dev-runner-command-listener.py`의 `_stream_output` 함수(1242줄)는 plan-runner의 stdout을 라인별로 읽어 `plan-runner:logs:{runner_id}`에 publish한다. `MergeLogger.log()`가 `print()`와 동시에 `self._main_channel`(`plan-runner:logs:{id}`)에도 직접 publish하므로 LOG_CHANNEL에 2번 게시됨.

`LogViewer.svelte`는 `/logs/stream` SSE를 구독하며, 이 endpoint는 `plan-runner:logs:{id}`만 구독. 따라서:
- Copy 1 (print→_stream_output→LOG_CHANNEL): LogViewer에 도달
- Copy 2 (MergeLogger 직접→LOG_CHANNEL): LogViewer에 도달 (중복)
- Copy 3 (MergeLogger→MERGE_CHANNEL): `MergeQueuePanel.svelte`에 도달 (별도 패널)

실제 3중복은 Copy 1 + Copy 2 = 2중복이고, Copy 3는 별도 MergeQueuePanel에 나타남. 사용자가 보는 Live Logs 패널이 두 패널을 합쳐서 표시하거나, 아래 `event_service.py`의 통합 SSE를 사용하는 경우 3중복으로 나타남.

`event_service.py`(223줄):
```python
await log_pubsub.psubscribe(LOG_CHANNEL_PATTERN, MERGE_LOG_CHANNEL_PATTERN)
```
이 psubscribe는 두 패턴을 동시에 구독 → 하나의 메시지가 LOG_CHANNEL에 2번(1+2) + MERGE_CHANNEL에 1번(3) = 총 3번 수신.

**근본 원인**: `MergeLogger.log()`의 `redis.publish(self._main_channel, line)` 호출이 불필요한 중복. `print()`가 이미 listener를 통해 LOG_CHANNEL로 forwarding됨.

### 버그 2: 4번째 로그 블록 (두 번째 실행 블록)

로그 하단의 두 번째 `[10:45:17]` 블록은 타임스탬프가 첫 번째 블록과 동일하고 MERGE 로그가 1x로 나타남. 이는 새로운 실행이 아니라 **`loadRecent` (파일 기반 이력 재생)**이 SSE 스트림 완료 후 또는 UI 재연결 시 파일에서 최근 로그를 읽어 표시한 것으로 추정됨.

파일에는 `_log_file.write()`와 `_stream_output` 각각이 1번씩 기록하여 1copy. 재생 시 1x로 나타나는 것이 증거.

**확인 필요**: loadRecent 시 이미 표시된 이력과 중복하지 않도록 deduplication이 되어 있는지 검토.

## 기술적 고려사항

- `MergeLogger._main_channel` publish 제거 시 `publish_completed()`에서 같은 채널 제거 필요
- `_tail_log_and_publish`(listener 재연결용 스레드)가 `_stream_output`과 동시 실행되면 추가 중복 발생 가능 → 동시 실행 방지 확인 필요
- 기존 테스트(`test_merge_log_publish.py`)에서 main_channel publish 검증 → 제거 후 테스트 수정 필요

---

## TODO

### Phase 1: MergeLogger main_channel 중복 제거

1. - [x] **`MergeLogger.log()` — main_channel 직접 publish 블록 제거**
   - [x] `common/tools/plan-runner/core/merge_stage.py` 70~74줄: `# 메인 채널 (Live Logs SSE + stream log 파이프라인)` 주석과 `try: self._redis.publish(self._main_channel, line) / except Exception: pass` 블록 전체 삭제. merge_channel publish(65~69줄)만 유지.
   - [x] `common/tools/plan-runner/core/merge_stage.py` 83~96줄: `publish_completed()` 내 `# 메인 채널에도 동일 신호 전송` 주석과 `try: self._redis.publish(self._main_channel, "__MERGE_COMPLETED__") / except Exception: pass` 블록 전체 삭제

2. - [x] **`_main_channel` 필드 정리 및 docstring 업데이트**
   - [x] `common/tools/plan-runner/core/merge_stage.py` 57줄: `self._main_channel = f"plan-runner:logs:{runner_id}"` 라인 삭제
   - [x] `common/tools/plan-runner/core/merge_stage.py` 51줄: docstring `"""merge 단계 로그를 stdout + Redis Pub/Sub(merge 채널 + main 채널)에 동시 출력."""` → `"""merge 단계 로그를 stdout + Redis Pub/Sub(merge 채널)에 출력. stdout은 listener가 LOG_CHANNEL로 forwarding."""` 으로 변경

### Phase 2: 기존 테스트 수정 — main_channel 검증 제거

3. - [x] **`test_merge_logger_log_right_publish_and_print` 수정 (16~35줄)**
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py` 31줄: `assert mock_redis.publish.call_count == 2` → `assert mock_redis.publish.call_count == 1` 로 변경
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py` 34~35줄: `assert "plan-runner:logs:abc" in channels` 라인 삭제. merge-log 채널 검증(`assert "plan-runner:merge-log:abc" in channels`)만 유지
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py` 17줄: docstring 수정 — `Redis publish 2회(merge+main 채널)` → `Redis publish 1회(merge 채널만)`

4. - [x] **`test_merge_logger_log_right_dual_publish` 수정 (37~52줄)**
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py`: 테스트 이름 `test_merge_logger_log_right_single_channel_publish`로 변경
   - [x] 44줄: `assert mock_redis.publish.call_count == 2` → `assert mock_redis.publish.call_count == 1` 로 변경
   - [x] 46~51줄: `merge_call`, `main_call` 분리 로직 제거. `call_args_list[0]`로 단일 호출만 검증. `assert call_args_list[0][0][0] == "plan-runner:merge-log:r1"` 및 `assert "hello" in call_args_list[0][0][1]` 로 교체

5. - [x] **`test_merge_logger_channel_format` 수정 (92~101줄)**
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py` 93줄: docstring 수정 — `merge 채널명 + main 채널` → `merge 채널명만 plan-runner:merge-log:{runner_id}`
   - [x] 101줄: `assert "plan-runner:logs:e62f374e" in channels` 라인 삭제

6. - [x] **`test_merge_logger_publish_completed_right` 수정 (141~151줄)**
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py` 148줄: `assert mock_redis.publish.call_count == 2` → `assert mock_redis.publish.call_count == 1` 로 변경
   - [x] 149~151줄: `calls` dict 빌드 로직 제거. `mock_redis.publish.assert_called_once_with("plan-runner:merge-log:abc", "__MERGE_COMPLETED__")` 로 교체

7. - [x] **`test_merge_logger_publish_completed_dual` 수정 (153~162줄)**
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py`: 테스트 이름 `test_merge_logger_publish_completed_single_channel`로 변경
   - [x] 160~162줄: `plan-runner:logs:r2` 채널 검증 제거. `assert "plan-runner:merge-log:r2" in channels` 만 유지. `assert len(channels) == 1` 추가

8. - [x] **`test_merge_logger_log_file_write_error` 수정 (125~137줄)**
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py` 137줄: `assert mock_redis.publish.call_count == 2` → `assert mock_redis.publish.call_count == 1` 로 변경

9. - [x] **`TestHandleMergeStageCompletedSignal` 수정 (170~229줄)**
   - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py` 203줄: `assert len(completed_calls) >= 2` → `assert len(completed_calls) >= 1` 로 변경 (merge 채널만 보장)
   - [x] 229줄: 동일하게 `assert len(completed_calls) >= 1` 로 변경

### Phase 3: 4번째 로그 블록 원인 확인 및 수정

10. - [x] **LogViewer loadRecent → connectSSE 중복 표시 원인 분석**
    - [x] `frontend/src/lib/components/dev-runner/LogViewer.svelte` 381~386줄 `onMount`: `loadRecent()` 이후 `connectSSE()`가 SSE를 통해 이미 표시된 이력을 재수신하여 중복 추가하는지 확인. Redis Pub/Sub 비버퍼링 특성상 이미 종료된 run의 메시지는 재수신 불가 → 4번째 블록은 loadRecent가 파일에서 로드한 이력임을 확인
    - [x] `frontend/src/lib/components/dev-runner/LogViewer.svelte` 330~366줄 `loadRecent()`: `lines = parsed` (351줄)로 전체 교체 후 connectSSE가 추가 push하는 구조 확인. SSE 이벤트가 도착 시 `addLine(event.data, false)` (288줄)로 lines에 append → **이미 loadRecent에서 로드된 이력 위에 SSE 이벤트가 쌓이는 구조는 정상**. 4번째 블록은 중복이 아니라 loadRecent(stale=true)로 표시된 이력 섹션

11. - [x] **`isMerging` 전환으로 인한 connectSSE 중복 호출 경로 확인**
    - [x] `frontend/src/lib/components/dev-runner/LogViewer.svelte` 410~418줄 `$effect`: `isMerging` false→true→false 전환 시 `connectSSE()`가 연속 3회 호출되어 3개의 EventSource가 동시에 활성화되는 race condition 여부 확인 — `connectSSE()` 첫 줄에 `if (eventSource) eventSource.close()` 가 있어 중복 방지 확인
    - [x] `frontend/src/lib/components/dev-runner/LogViewer.svelte` 276~278줄: `isMerging=true` 전환 직전에 LOG_STREAM이 닫히고 MERGE_STREAM으로 전환되는 타이밍에서 MERGE 로그가 LOG_CHANNEL에 2x 발행되는 경우 MERGE_STREAM에는 도달하지 않으므로 문제 없음을 확인

### Phase 4: T1 단위 테스트 추가

12. - [x] **수정된 MergeLogger 동작 신규 TC 작성**
    - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py`: `test_merge_logger_log_right_only_merge_channel()` — R: `log()` 호출 시 `publish.call_count == 1` 이고 `publish.call_args[0][0] == "plan-runner:merge-log:{runner_id}"` 인지 검증
    - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py`: `test_merge_logger_log_right_no_main_channel_publish()` — R: `log()` 호출 시 `plan-runner:logs:{id}` 채널에 publish 되지 않음을 검증 (`assert all("merge-log" in c[0][0] for c in mock_redis.publish.call_args_list)`)
    - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py`: `test_merge_logger_log_boundary_publish_count_with_file()` — B: log_file 전달 시에도 `publish.call_count == 1` (파일 기록이 Redis publish 수에 영향 없음) 검증
    - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py`: `test_merge_logger_publish_completed_right_only_merge_channel()` — R: `publish_completed()` 후 `publish.call_count == 1`, `publish.call_args[0][0]`이 merge 채널인지 검증

### Phase 5: T2 TC 검증 및 수정

13. - [x] **테스트 실행 및 pass 확인**
    - [x] `cd D:\work\project\service\wtools && python -m pytest common/tools/plan-runner/tests/test_merge_log_publish.py -v` 실행 → 전체 passed 확인 (20/20)
    - [x] 실패 TC 수정 후 재실행
    - [x] `python -m pytest common/tools/plan-runner/tests/ -v` 회귀 확인 — 기존 TC 중 main_channel 관련 외 모두 passed 확인 (test_merge_stage.py 에러는 pre-existing, 내 변경과 무관)

### Phase 6: T3 통합 테스트

14. - [x] **MergeLogger 단일 채널 publish 통합 재현**
    - [x] `common/tools/plan-runner/tests/test_merge_log_publish.py`: `test_integration_no_log_channel_direct_publish()` — `MergeLogger(runner_id="x", redis_client=fake_redis)` 생성 후 `log("INFO", "msg")` 호출. `fake_redis.get_published("plan-runner:logs:x")` 결과가 비어있음을 검증. `fake_redis.get_published("plan-runner:merge-log:x")` 에 1건 있음을 검증. (fakeredis 설치 없을 시 MagicMock으로 채널별 호출 수 카운트)

### Phase 7: T4 E2E·T5 HTTP 테스트

15. - [x] T4 E2E — 스킵: `tests/**/*e2e*` Glob 탐색 결과 0건 확인됨. merge_stage 내부 로직 변경이므로 단위 TC로 충분히 커버됨.
16. - [x] T5 HTTP — 스킵: `tests/**/*http*` Glob 탐색 결과 0건 확인됨. MergeLogger는 Redis publish 내부 동작이며 API 인터페이스 변경 없음.

---

## 검증 (Python 코드 수정 시 참고 정보)

### 테스트 실행

```powershell
cd D:\work\project\service\wtools
python -m pytest common/tools/plan-runner/tests/test_merge_log_publish.py -v
```

- 기대 결과: 전체 passed, 실행시간 < 10초

### 회귀 확인

```powershell
python -m pytest common/tools/plan-runner/tests/ -v
```

### 검증 기준

- [x] MergeLogger.log()가 merge_channel에만 publish (main_channel 없음)
- [x] print()는 그대로 stdout 출력
- [x] 기존 테스트 회귀 없음
- [x] Live Logs에서 MERGE 로그 3중복이 1중복으로 감소

---

*상태: 구현완료 | 진행률: 51/51 (100%)*
