# Dev Runner 페이지 리디자인 — Design Prompt

## 현재 상태 요약

### 컴포넌트 구조 (monitor-page 프로젝트)
```
routes/automation/
├── +page.svelte          # 메인 탭: Dev Runner | Sleep Now | Git 관리 | 계획서
├── DevRunnerTab.svelte   # Dev Runner 메인 (685줄, 상태관리 + SSE + 레이아웃)

lib/components/dev-runner/
├── RunControl.svelte         # 실행 컨트롤 (engine/plan 선택, 시작/중지/동기화 버튼)
├── RunnerInstanceTab.svelte  # 개별 runner 탭 (헤더 + LogViewer)
├── LogViewer.svelte          # SSE 기반 실시간 로그 (dark theme, 468줄)
├── TaskList.svelte           # plan 체크박스 항목 표시
├── PlanList.svelte           # plan 목록 + 완료처리/일괄완료
├── PlanDetailView.svelte     # plan 상세 뷰
├── CurrentTrackingCard.svelte # 현재 추적 태스크
├── MergeQueuePanel.svelte    # 머지 큐
├── UnifiedLogsView.svelte    # 통합 로그
└── ...

routes/plans/
├── PlanListTab.svelte    # 계획서 탭의 plan 목록 (그룹핑, 실행 버튼)
├── PlanViewer.svelte     # plan 마크다운 렌더링
└── ...
```

### 현재 레이아웃
```
┌─────────────────────────────────────────────┐
│ 시스템 자동화 [Dev Runner] [Sleep Now] [Git] [계획서] │
├─────────────────────────────────────────────┤
│ [▼ 접힘패널] 상태 표시 (실행중/대기)              │
│  └─ RunControl: [중지][시작][동기화][초기화]      │
│     Mode: [단일/전체] Engine: [Claude/Gemini]   │
│     AI Settings (접힘): plan/impl/done 모델     │
│     Plan dropdown, MaxCycles, EndTime, DryRun  │
├─────────────────────────────────────────────┤
│ [Runner탭바] [plan-a.md ×] [plan-b.md ×] [📋Logs] │
├──────────────────────┬──────────────────────┤
│ LogViewer (좌)       │ Runner Panel (우)     │
│ - dark bg            │ [Tasks][Plans][Merge] │
│ - SSE 실시간          │ - TaskList           │
│ - 500줄 버퍼          │ - PlanList           │
│                      │ - MergeQueuePanel    │
└──────────────────────┴──────────────────────┘
```

모바일: 좌/우 → 상/하 스택, Runner Panel 접힘 가능

## 문제점 (사용자 피드백)

### 1. Engine/Provider 설정 제한
- **현상**: runner 실행 중이면 engine 선택 disabled → 추가 runner 시작 시 engine 변경 불가
- **원인**: `anyRunning` 변수로 모든 드롭다운 disabled 처리
- **원하는 동작**: 각 runner마다 다른 engine/model 조합 가능 (예: gemini-3-pro 계획 + sonnet 구현)
- **핵심**: 현재 engine 단위(claude/gemini)로만 선택 가능 → plan/impl/done 각각 다른 provider의 모델 지정 가능해야 함

### 2. Plan dropdown 불편
- **현상**: `<select>` 드롭다운에 파일명+진행률만 표시 → 어떤 plan인지 구별 어려움
- **실제 사용 패턴**: 사용자는 "계획서" 탭의 PlanListTab에서 plan을 선택 → 실행 버튼 클릭
- **원하는 동작**: plan dropdown 제거, plan 선택은 PlanList에서 직접

### 3. Plan 팝업 ↔ TaskList 기능 중복
- **현상**: PlanListTab에서 plan 클릭 → PlanViewer 팝업 (마크다운 렌더링)
  - DevRunnerTab의 Runner Panel > Tasks 탭: TaskList (체크박스 항목)
  - 두 뷰가 거의 같은 정보를 다른 형태로 보여줌
- **원하는 동작**: plan 선택 시 팝업에서 "계획 실행" 컴포넌트가 보이는 게 자연스러움

### 4. 모바일 로그 뷰 높이
- **요구**: 로그 뷰는 최소 5줄 이상 표시
- **실행 중일 때**: 다른 영역(RunControl 등) 자동 접힘 → 로그에 최대 공간 할당

## 리디자인 방향

### A. 레이아웃 재구성

```
┌─────────────────────────────────────────────┐
│ [Dev Runner] [Sleep Now] [Git] [계획서]        │
├─────────────────────────────────────────────┤
│ 상태바: ● 실행중 2개 | 00:12:34 | [전체중지]    │
├──────────────────────┬──────────────────────┤
│ [Plan 목록]          │ [실행 영역]            │
│                      │                      │
│ 카드형 plan 리스트     │ ┌─ 실행 설정 (접힘)──┐ │
│ - 제목, 상태, 진행률   │ │ Model 설정        │ │
│ - 클릭 → 우측에 상세   │ │ MaxCycles, Until  │ │
│ - [▶ 실행] 버튼       │ └──────────────────┘ │
│                      │                      │
│                      │ [Runner탭] [tab] [Logs]│
│                      │ ┌── LogViewer ──────┐ │
│                      │ │                   │ │
│                      │ │                   │ │
│                      │ └───────────────────┘ │
│                      │                      │
│                      │ ┌── Tasks ──────────┐ │
│                      │ │ 체크박스 항목       │ │
│                      │ └───────────────────┘ │
└──────────────────────┴──────────────────────┘
```

모바일:
```
┌──────────────────────┐
│ 상태바: ● 실행중       │
├──────────────────────┤
│ [Plans] [Runner] 탭   │
│                      │
│ (Plans 탭 활성 시)     │
│ Plan 카드 리스트       │
│ → 클릭 시 실행 설정 팝업│
│                      │
│ (Runner 탭 활성 시)    │
│ [runner탭바]          │
│ LogViewer (최소 5줄)   │
│ [▼ Tasks 접힘]        │
└──────────────────────┘
```

### B. Engine/Model 설정 개선

**Before**: engine(claude/gemini) 선택 → 해당 engine의 모델만 사용
**After**: phase별 독립 모델 선택 (cross-provider 가능)

```
┌─ 모델 설정 ──────────────────────────┐
│ Plan:  [Claude Opus ▼]              │
│ Impl:  [Claude Sonnet ▼]           │
│ Done:  [Claude Haiku ▼]            │
│                                     │
│ 각 드롭다운에 모든 provider 모델 표시:   │
│  - Claude: opus, sonnet, haiku      │
│  - Gemini: 3.1-pro, 3-flash, ...   │
└─────────────────────────────────────┘
```

→ **프론트 변경만**: API에 `engine` + `models` 보내는 대신, phase별 `{provider}:{model}` 조합 전송
→ 또는 기존 API 호환: plan phase에 gemini 모델, impl에 claude 모델 → 백엔드가 engines.json에서 매핑

### C. Plan 선택 UX 개선

1. **dropdown 제거** → Plan 목록이 좌측 패널 (또는 모바일에서 별도 탭)
2. Plan 카드에 표시: 제목(파싱), 상태(상태: 필드), 진행률 바, 프로젝트명
3. Plan 클릭 → 우측에 상세 + 실행 설정 표시 (팝업 대신 인라인)
4. [▶ 실행] 버튼은 plan 카드 또는 상세 뷰에 직접 배치

### D. 실행 중 모바일 최적화

- 실행 시작 → 자동으로 Runner 탭 전환
- RunControl(설정 영역) 자동 접힘
- LogViewer `min-height: 5lh` (5줄 높이) 보장
- Tasks 패널은 하단에 접힘 상태로 표시

## 수정 대상 파일 (프론트엔드만)

| 파일 | 변경 내용 |
|------|----------|
| `DevRunnerTab.svelte` | 레이아웃 재구성, plan 선택 로직 변경 |
| `RunControl.svelte` | engine 단일 선택 → phase별 모델 선택, plan dropdown 제거 |
| `PlanList.svelte` | 좌측 패널용으로 리디자인, 실행 버튼 추가 |
| `LogViewer.svelte` | min-height 보장 |
| `RunnerInstanceTab.svelte` | 레이아웃 미세 조정 |
| `TaskList.svelte` | 접힘/펼침 개선 |

## 기존 API (변경 없음)

```typescript
// 실행 시작
devRunnerRunnerApi.start({
  plan_file: string | null,
  engine: string,        // "claude" | "gemini"
  max_cycles: number,
  until: string | null,
  dry_run: boolean,
  parallel: boolean,
  projects: string | null
})

// engine 설정 조회/수정
devRunnerEngineApi.list()    // → AllEnginesConfig
devRunnerEngineApi.update(engine, { models: { plan, impl, done } })

// plan 목록
devRunnerPlanApi.list()      // → PlanFileResponse[]
devRunnerPlanApi.items(path)  // → PlanDetailResponse (체크박스 항목)
devRunnerPlanApi.content(path) // → markdown 원문
```

### Cross-Provider 모델 지원 방안 (프론트만)
현재 `engines.json`에 claude/gemini 각각 models 설정이 있음.
**방안 1**: 실행 전 선택한 phase별 모델로 해당 engine의 `engines.json`을 업데이트 후 시작
  - 예: plan=gemini-3-pro → `devRunnerEngineApi.update("gemini", { models: { plan: "gemini-3-pro" } })`
  - 그리고 `start({ engine: "gemini" })` — 단, impl은 claude면 불가

**방안 2**: start API에 phase별 모델 직접 전달 (백엔드 수정 필요)
  - `start({ models: { plan: "gemini:gemini-3-pro", impl: "claude:sonnet", done: "claude:haiku" } })`

**방안 3 (현실적)**: 프론트에서 engine 선택 시 해당 engine의 models만 선택 가능하되, UI를 더 직관적으로 개선. Cross-provider는 향후 백엔드 지원 시 확장.

## 참고: 기존 "계획서" 탭과의 관계

`+page.svelte`에 4개 메인 탭:
1. **Dev Runner** — 실행 + 로그
2. Sleep Now
3. Git 관리
4. **계획서** — PlanListTab (plan 목록 + 상세 뷰 + 실행 버튼)

현재 "계획서" 탭에서도 plan 선택 → [실행] → Dev Runner로 이동 가능 (`goto` with `?plan=base64`)
→ 리디자인 후에도 이 흐름 유지하되, Dev Runner 내에서 plan 선택이 자연스럽게 가능하도록.
