# Log Viewer 스크롤 동작 개선

> 상태: 구현완료
> branch: plan/2026-03-26_log-viewer-scroll-fix
> worktree: .worktrees/2026-03-26_log-viewer-scroll-fix
> 우선순위: P0
> 난이도: 낮음
> 요약: 러너 탭 전환 시 스크롤이 맨 위로 리셋되는 버그 수정 + pause 시 로그가 안 보이는 문제를 autoScroll만 제어하도록 변경
> 진행률: 19/19 (100%)

> 완료일: 2026-03-28
> 아카이브됨

## 배경

### 문제 1: 탭 전환 시 스크롤 리셋
- `DevRunnerTab.svelte`에서 러너 탭을 `hidden` 클래스로 토글
- `hidden` 상태에서 `scrollHeight=0`이므로, 탭이 다시 보일 때 스크롤 위치가 맨 위
- 기대 동작: 탭 전환 후에도 스크롤이 맨 아래 유지

### 문제 2: 하단고정 해제 시 로그가 안 보임
- 현재: `paused=true`이면 `addLine()`이 `pauseBuffer`에만 넣고 `return` → 화면에 로그 미표시
- 기대 동작: autoScroll만 끄고, 로그는 계속 화면에 추가. 사용자가 과거 로그를 읽는 동안에도 새 로그가 하단에 쌓임

## 수정 대상

- `frontend/src/lib/components/dev-runner/LogViewer.svelte`

---

## TODO

### Phase 1: pauseBuffer 제거 — autoScroll만 제어

1. - [x] **상태 변수 정리**
   - [x] `LogViewer.svelte:50`: `let paused = $state(false);` 삭제
   - [x] `LogViewer.svelte:51`: `let pauseBuffer = $state<ParsedLine[]>([]);` 삭제

2. - [x] **addLine() 내 pause 분기 삭제**
   - [x] `LogViewer.svelte:225-228`: `if (paused && !isStale) { pauseBuffer.push(parsed); return; }` 블록 삭제. 이후 RESULT 큐 분기와 pushLine 호출만 남김

3. - [x] **resumeLog() 단순화**
   - [x] `LogViewer.svelte:262-278`: 함수 본문을 `autoScroll = true; scrollToBottom();` 2줄로 교체. 기존 pauseBuffer flush·slice·rAF 로직 전부 제거

4. - [x] **핀 버튼 onclick 수정**
   - [x] `LogViewer.svelte:542-549`: pin 해제 시 `paused = true` 제거 → `autoScroll = false`만. unpin 시 `resumeLog(); scrollToBottom();` → `autoScroll = true; scrollToBottom();`

5. - [x] **pauseBuffer 뱃지 제거**
   - [x] `LogViewer.svelte:558-562`: `{#if pauseBuffer.length > 0}` ~ `{/if}` 블록 삭제 (PinOff 아이콘 옆 버퍼 카운트 뱃지)

### Phase 2: 탭 전환 시 스크롤 맨 아래 유지

6. - [x] **visibility 전환 감지 → scrollToBottom**
   - [x] `LogViewer.svelte`: `$effect`에서 `logContainer`의 `offsetParent !== null` (visible 판별) 감지. `autoScroll=true`이면 `scrollToBottom()` 호출. 탭 전환으로 `hidden`→visible 될 때 스크롤 맨 아래로 복원

### Phase 3: 수동 스크롤 맨 아래 도달 시 autoScroll 복귀

7. - [x] **handleScroll에 맨 아래 감지 로직 추가**
   - [x] `LogViewer.svelte:287-289`: 빈 `handleScroll()` 본문에 로직 추가: `const { scrollTop, clientHeight, scrollHeight } = logContainer; const atBottom = scrollHeight - scrollTop - clientHeight < 30; if (atBottom && !autoScroll) { autoScroll = true; }`

### Phase 4: 빌드 확인

8. - [x] **타입 에러 없이 빌드 통과 확인**
   - [x] main 머지 후 (`/merge-test`) `npm run check` 통과 확인 — 워크트리에는 node_modules 없어 실행 불가, 반드시 main에서

### Phase 5: E2E / HTTP 테스트 (T4/T5)

- [x] **T4 E2E**: 프론트엔드 전용 변경 — 프론트엔드 서버 재시작 후 러너 탭에서 스크롤 동작 수동 확인으로 대체 (자동 E2E 스크립트 없음)
- [x] **T5 HTTP**: 백엔드 변경 없음 — 스킵 (API 엔드포인트 무변경)

---

> 진행률: 19/19 (100%)
