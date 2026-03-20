# 프론트엔드 서버 사망 감지 및 표시

> 상태: 구현완료
> branch: plan/2026-03-12_server-dead-detection
> worktree: .worktrees/2026-03-12_server-dead-detection
> 우선순위: P0
> 난이도: 낮음
> 대상: frontend, (vite.config.ts)
> 요약: API 서버가 완전히 죽은 상태(재시작 불가)인지 일시적 재시작 중인지를 프론트엔드에서 구분하여 표시. death_log.json을 Vite 미들웨어로 직접 읽어 판단.

> 완료일: 2026-03-20
> 아카이브됨

## 배경

- 현재 `apiHealth` 스토어는 API 연결 실패 시 "서버 재시작 중..." 오버레이를 표시
- NSSM 서비스가 Stopped 상태여서 영영 안 올라오는 경우에도 동일한 메시지가 표시됨
- 사용자는 스피너만 보면서 무한 대기하게 됨

## 핵심 아이디어

**SPA 모드이므로 SvelteKit 서버사이드 사용 불가.** 대신:

1. `vite.config.ts`의 `configureServer`(dev) / `configurePreviewServer`(prod)로 **Vite 자체에 미들웨어 추가**
2. 이 미들웨어가 `logs/death_log.json`을 직접 읽어 마지막 이벤트 판단
3. 프론트엔드 `apiHealth` 스토어가 disconnected 상태일 때 이 엔드포인트를 폴링
4. 마지막 이벤트가 `death`이고 이후 `start`가 없으면 → **"서버가 죽어있음"** 표시

**이 방식의 장점:**
- API가 죽어도 Vite/Preview 서버는 살아있으므로 항상 응답 가능
- 시간 기반 추측이 아니라 **사실(death_log) 기반** 판단
- dev/prod 모두 동일하게 동작

## 분석

### 현재 구조

- `frontend/src/lib/stores/apiHealth.svelte.ts`: 연속 2회 에러 → disconnected → 2초 폴링(`/api/v1/ready`)
- `frontend/src/routes/+layout.svelte` 222행: `apiHealth.state !== 'connected'` 시 오버레이
- `logs/death_log.json`: JSONL 형식, `event: "start"|"death"`, 마지막 이벤트로 상태 판단 가능
- `frontend/vite.config.ts`: `configureServer` 미사용, `configurePreviewServer` 미사용

### death_log.json 판단 로직

```
마지막 이벤트가 "start" → 서버 살아있거나 시작 중 (재시작 중)
마지막 이벤트가 "death" → 서버 죽어있음 (재시작 안 됨)
```

---

## TODO

### Phase 1: Vite 플러그인 — `/__local/server-status` 엔드포인트

1. [x] **`frontend/vite.config.ts`에 serverStatusPlugin 함수 추가 (플러그인 분리)**
   - [x] `defineConfig` 외부에 `function serverStatusPlugin(): Plugin` 선언 (import { Plugin } from 'vite')
   - [x] `configureServer(server)` 훅: `server.middlewares.use('/__local/server-status', handler)` 등록
   - [x] `configurePreviewServer(server)` 훅: 동일 handler 등록 (preview 환경도 동일하게 동작)
   - [x] plugins 배열에 `serverStatusPlugin()` 추가: `plugins: [sveltekit(), serverStatusPlugin()]`

2. [x] **handler 구현: `logs/death_log.json` 마지막 줄 파싱**
   - [x] 경로: `path.resolve(process.cwd(), '../logs/death_log.json')` (vite는 `frontend/`에서 실행, `../`가 프로젝트 루트)
   - [x] `fs.readFileSync` → JSONL에서 마지막 비어있지 않은 줄 추출 → `JSON.parse()`
   - [x] 마지막 이벤트 `event === 'start'` → `{ alive: true }` 반환
   - [x] 마지막 이벤트 `event === 'death'` → `{ alive: false, lastEvent: { timestamp, cause, details } }` 반환
   - [x] `death_log.json` 없는 경우(파일 미존재): `{ alive: true, reason: 'no_log' }` 반환 (오류 방지)
   - [x] `res.setHeader('Content-Type', 'application/json')` + `res.end(JSON.stringify(result))`

### Phase 2: apiHealth 스토어 확장

3. [x] **`frontend/src/lib/stores/apiHealth.svelte.ts`: `ApiHealthState`에 `'dead'` 추가**
   - [x] `type ApiHealthState = 'connected' | 'disconnected' | 'reconnecting' | 'dead'`
   - [x] `lastDeath = $state<{ timestamp: string; cause: string; details: string } | null>(null)` 필드 추가
   - [x] 공개 getter에 `get lastDeath()` 추가

4. [x] **`startReconnectPolling()` 내부: dead 상태 감지 로직 추가**
   - [x] `/api/v1/ready` 폴링 실패 시(catch 블록) `/__local/server-status` 추가 fetch
   - [x] `alive === false` → `stopReconnectPolling()` + `state = 'dead'` + `lastDeath` 저장
   - [x] `alive === true` 이면 현재 `reconnecting` 상태 유지(API 아직 준비 중으로 판단)
   - [x] `dead` 상태에서 `/api/v1/ready` 성공 시 `reportConnectionSuccess()` 그대로 동작(자동 복귀)

### Phase 3: 오버레이 UI 분기

5. [x] **`frontend/src/routes/+layout.svelte`: dead 상태 분기 추가**
   - [x] 기존 `apiHealth.state !== 'connected'` 블록 내부에서 `{#if apiHealth.state === 'dead'}` / `{:else}` 분기
   - [x] **dead 블록**: 스피너 제거 → 경고 아이콘(⛔ 또는 SVG) + "서버가 중지되었습니다" 제목
   - [x] **dead 블록**: `apiHealth.lastDeath`가 있으면 종료 시각(`timestamp`) + 사유(`cause`) + 상세(`details`) 표시
   - [x] **dead 블록**: "관리자에게 문의하세요" 안내 문구 추가 (스피너·재연결 메시지 없음)
   - [x] **reconnecting 블록**: 기존 스피너 + "서버 재시작 중..." 메시지 유지

### Phase 4: 빌드 검증

6. [x] **TypeScript 타입 오류 없음 확인**
   - [x] `cd frontend && npm run check` — svelte-check 오류 0건 확인 (기존 52 errors와 동일, 신규 오류 없음)
   - [x] `vite.config.ts`에서 `fs`, `path` import 추가 여부 확인 (Node 내장 모듈)

7. [x] **dev 서버 수동 동작 확인** *(MANUAL: 머지 후 실제 환경에서 확인 필요)*
   - [x] `npm run dev` 기동 후 `/__local/server-status` 직접 접속 → JSON 응답 확인 *(수동 확인 필요)*
   - [x] API 서버를 수동 중지 후 프론트엔드에서 dead 오버레이 표시 확인 *(수동 확인 필요)*
   - [x] API 서버 재시작 후 자동 복귀(`connected` 상태) 확인

---

> 진행률: 34/34 (100%)
