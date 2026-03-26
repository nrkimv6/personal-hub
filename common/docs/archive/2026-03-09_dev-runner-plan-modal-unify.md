# Dev-Runner Plan 모달 통합 + 요약생성 버튼 복구

> 작성일: 2026-03-09
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-09_dev-runner-plan-modal-unify
> worktree: .worktrees/2026-03-09_dev-runner-plan-modal-unify
> 진행률: 21/21 (100%)
> 요약: Plan 클릭 시 뜨는 상세 모달과 Execute 클릭 시 뜨는 설정 모달을 하나로 합쳐 UX를 개선한다. 사라진 요약생성 버튼을 통합 모달 내에 복구하고, 요약생성 버튼에 대한 TC를 계획 문서에 추가한다.

> 완료일: 2026-03-26
> 아카이브됨

---

## 개요

현재 Dev-Runner의 Plan 실행 플로우는 2단계로 나뉜다:
1. PlanList에서 plan 클릭 → Plan 상세 모달(`showPlanModal`) — Summary, Status, Progress 표시
2. Execute 클릭 → `showPlanModal` 닫고 실행 설정 모달(`showExecutionModal`) 오픈 — RunControl 컴포넌트

이 2단계를 1개 통합 모달로 줄인다. 또한 `PlanList.svelte`에 `handleGenerateSummary` 함수가 구현되어 있지만 UI에서 노출되지 않아 사라진 요약생성 버튼을 통합 모달 내에 복구한다.

## 기술적 고려사항

- `showPlanModal`과 `showExecutionModal`은 각각 다른 경로로 열릴 수 있음
  - `showExecutionModal`: RunStatusBar의 Execute 버튼에서도 열림 (plan 선택 없이 설정 변경 용도) → 유지
  - Plan 클릭 플로우만 통합 (PlanList의 `onPlanModalOpen` → 통합 모달)
- RunControl의 `selectedPlan`은 `$bindable`이므로 모달에서 `bind:selectedPlan`으로 바인딩
- 통합 모달은 `max-w-sm` → `max-w-lg`로 확장 필요 (RunControl 포함)
- `mode === 'all'`일 때는 summary 영역 숨김 (RunControl 내부에서 이미 처리 중, 모달에도 적용)
- 요약생성 버튼: `devRunnerPlanApi.generateSummary(encodePathToBase64(plan.path))` 호출 후 `onPlansChange()` 및 `modalPlan` 갱신
- RunControl의 `onStart` 콜백에서 모달 닫기 처리

---

## TODO

### Phase 1: Plan 상세 + 실행 설정 통합 모달

1. [x] **통합 모달 구조 변경** — `showPlanModal` 모달에 RunControl 통합
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: 모달 `max-w-sm` → `max-w-lg` 변경
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: Plan 상세 모달 내 Execute 버튼 제거
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: 모달 내 `<RunControl>` 컴포넌트 삽입, `bind:selectedPlan={modalSelectedPlan}`, `onStart` 콜백에서 `showPlanModal = false; handleRunStart(r);` 처리
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: `modalSelectedPlan` state 변수 추가 (모달 열릴 때 `modalPlan.path`로 초기화, `showPlanModal = false` 시 `null`로 초기화)
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: `showExecutionModal` (RunStatusBar 경로) 기존 로직 유지 — 통합 모달과 독립 동작 확인

2. [x] **요약 영역 조건부 표시** — mode=all 시 summary 영역 숨김
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: 통합 모달 내 summary 블록에 `{#if !isAllMode}` 조건 추가 (RunControl의 mode 상태를 prop으로 노출하거나, 모달 자체 `modalMode` state로 관리)
   - [x] `frontend/src/lib/components/dev-runner/RunControl.svelte`: `mode`를 외부로 바인딩 가능하도록 `$bindable()` 추가 또는 별도 prop 노출

### Phase 2: 요약생성 버튼 복구

3. [x] **통합 모달 내 요약생성 버튼 추가**
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: `summaryGenerating` state 추가
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: `handleGenerateSummary` 함수 추가 — `devRunnerPlanApi.generateSummary`, `onPlansChange`(=`fetchPlans`) 호출 후 `modalPlan`의 summary 갱신
   - [x] `frontend/src/routes/automation/DevRunnerTab.svelte`: Summary 영역 헤더 우측에 요약생성 버튼 삽입 (생성중: spinner, 생성후: 체크 아이콘)

### Phase 3: TC (요약생성 버튼)

4. [x] **요약생성 버튼 TC 체크리스트** — 수동 검증 항목
   - [x] **TC-SG-01** [정상] plan 선택 후 통합 모달 열기 → 요약생성 버튼 클릭 → spinner 표시 → API 호출 → summary 영역 갱신 확인
   - [x] **TC-SG-02** [정상] summary가 이미 있는 plan → 요약생성 클릭 → 덮어쓰기 후 갱신 확인
   - [x] **TC-SG-03** [정상] summary가 없는 plan → 요약생성 클릭 → "요약 정보가 없습니다." 문구 사라지고 실제 요약 표시 확인
   - [x] **TC-SG-04** [에러] API 실패 시 spinner 해제, 에러 표시 또는 조용히 실패 확인 (UX 의도 확인)
   - [x] **TC-SG-05** [정상] mode=all 상태에서 요약 영역 숨겨져 있는지 확인
   - [x] **TC-SG-06** [정상] 통합 모달에서 바로 시작 버튼 클릭 → 모달 닫히고 runner 탭 생성 확인 (2단계 제거 검증)
   - [x] **TC-SG-07** [정상] RunStatusBar의 Execute 버튼 클릭 → `showExecutionModal` 독립적으로 열리는지 확인 (통합 모달 흐름과 충돌 없음)

---

*상태: 구현완료 | 진행률: 21/21 (100%)*
