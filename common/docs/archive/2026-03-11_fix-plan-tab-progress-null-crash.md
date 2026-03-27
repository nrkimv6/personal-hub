# 계획서 탭 progress null 런타임 에러 수정

> 작성일: 2026-03-11
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-11_fix-plan-tab-progress-null-crash
> worktree: .worktrees/2026-03-11_fix-plan-tab-progress-null-crash
> 진행률: 6/6 (100%)
> 요약: 계획서 탭에서 plan의 progress가 null일 때 `plan.progress.done` 등에 접근하여 런타임 에러가 발생. null 체크를 추가하여 0/0 (0%)으로 표시하도록 수정.

> 완료일: 2026-03-13
> 아카이브됨

---

## 개요

시스템 자동화 > 계획서 탭 선택 시, API가 반환하는 `PlanFileResponse.progress`가 `null`인 plan이 존재한다.
`PlanListTab.svelte`에서 `plan.progress.done`, `plan.progress.total`, `plan.progress.percent`를 null 체크 없이 직접 접근하여 `Cannot read properties of null` 런타임 에러가 발생한다.

**타입 정의** (`dev-runner.ts:62`): `progress: PlanProgressResponse | null`로 null 허용이 명시되어 있으나, 템플릿에서 무방비로 접근 중.

## 기술적 고려사항

- 데스크톱 뷰 (테이블, line 368-371)와 모바일 뷰 (카드, line 439-441) 양쪽 모두 수정 필요
- optional chaining + nullish coalescing으로 간단히 해결 가능: `plan.progress?.done ?? 0`

---

## TODO

### Phase 1: progress null 방어 처리

1. [x] **PlanListTab 데스크톱/모바일 뷰 progress null 방어** — optional chaining 추가
   - [x] `frontend/src/routes/plans/PlanListTab.svelte` (line 368-371): 데스크톱 테이블 `plan.progress.done` → `plan.progress?.done ?? 0`, `.total`, `.percent` 동일 처리
   - [x] `frontend/src/routes/plans/PlanListTab.svelte` (line 439-441): 모바일 카드 동일 처리
     - `{plan.progress.done}/{plan.progress.total}` → `{plan.progress?.done ?? 0}/{plan.progress?.total ?? 0}`
     - `({plan.progress.percent}%)` → `({plan.progress?.percent ?? 0}%)`

### Phase 2: 빌드 확인

2. [x] **프론트엔드 빌드 확인** — 타입 오류 없는지 검증
   - [x] `cd frontend && npm run check` — TypeScript/Svelte 타입 체크 통과 확인
   - [x] 브라우저에서 계획서 탭 열어 런타임 에러 없이 목록 렌더링 확인 (progress=null 항목 포함)

---

*상태: 구현완료 | 진행률: 6/6 (100%)*
