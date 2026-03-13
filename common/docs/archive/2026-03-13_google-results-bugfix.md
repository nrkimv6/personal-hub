# Google 검색결과 관리 탭 버그픽스 (3건)

> 작성일: 2026-03-13
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-13_google-results-bugfix
> worktree: .worktrees/2026-03-13_google-results-bugfix
> 진행률: 25/25 (100%)
> 요약: Google 검색결과 관리(results) 탭의 3가지 버그 수정 — 탭 아이콘이 wrapper 함수 텍스트로 렌더링, 모달 X 닫기 미동작, 새로고침 시 필터 초기화

> 완료일: 2026-03-13
> 아카이브됨

---

## 개요

`/collect/google?tab=results` 페이지에서 3가지 버그가 발견됨:

### Bug 1: 탭에 Svelte internal wrapper 함수가 텍스트로 표시됨

**원인**: `+page.svelte:627-628`에서 탭 정의 시 `icon` 속성에 lucide-svelte 컴포넌트(`Search`, `ClipboardList`)를 전달하지만, `TabNav.svelte:131,161`에서 `{tab.icon}`으로 텍스트 보간 → Svelte 5에서 컴포넌트 객체가 내부 wrapper 함수의 toString()으로 렌더링됨.

**영향 범위**: TabNav를 사용하는 모든 페이지에서 icon에 컴포넌트를 전달하는 경우 동일 증상 가능.

### Bug 2: 상세 모달 X 버튼 닫기 미동작

**원인**: `Modal.svelte`이 Svelte 4 문법(`createEventDispatcher`, `on:click={close}`, `dispatch('close')`)으로 작성됨. 하지만 `SearchResultDetailModal.svelte:46`에서 Svelte 5 방식으로 `onClose` prop을 전달 → Modal은 이벤트 디스패치만 하고 prop 콜백은 호출하지 않아 닫기 동작 실패.

### Bug 3: 새로고침 시 검색 필터 초기화

**원인**: `GoogleResultsTab.svelte`에서 필터 상태(`activeTab`, `query`, `search`, `dateFrom`, `dateTo`, `isRead`, `sortBy`, `sortOrder`, `page`)를 로컬 `$state`로만 관리. URL searchParams 읽기/쓰기 없음. `onMount`에서 `loadResults()`만 호출하여 기본값으로 로드.

## 기술적 고려사항

- Modal.svelte는 다른 곳에서도 사용될 수 있으므로 Svelte 5 마이그레이션 시 기존 사용처 확인 필요
- TabNav의 icon 렌더링은 `{@render}` 또는 `svelte:component`를 사용해야 함
- 필터 URL 동기화는 `$effect`로 필터 변경 → URL 업데이트, `onMount`에서 URL → 필터 복원

---

## TODO

### Phase 1: TabNav 아이콘 렌더링 수정

1. - [x] **TabNav icon 타입 및 렌더링 변경**
   - [x] `frontend/src/lib/components/layout/TabNav.svelte`: `Tab` 타입의 `icon` 필드를 `icon?: string | typeof import('svelte').Component`로 변경 (L19)
   - [x] `frontend/src/lib/components/layout/TabNav.svelte`: 4곳의 icon 렌더링을 조건 분기로 수정 — `typeof tab.icon === 'string'`이면 기존 `{tab.icon}` 텍스트, 아니면 `<svelte:component this={tab.icon} size={16} />`로 렌더링. 대상: L131 (secondary urlBased), L142 (secondary button), L161 (primary urlBased), L172 (primary button)

### Phase 2: Modal Svelte 5 마이그레이션

2. - [x] **Modal.svelte script를 Svelte 5 문법으로 전환**
   - [x] `frontend/src/lib/components/ui/Modal.svelte`: `export let open/title/size` → `$props()`로 변환. `interface Props { open: boolean; title: string; size?: 'sm'|'md'|'lg'|'xl'; onClose: () => void; children: Snippet; footer?: Snippet; }` 정의
   - [x] `frontend/src/lib/components/ui/Modal.svelte`: `createEventDispatcher` + `dispatch('close')` 제거 → `props.onClose()` 직접 호출로 변경 (close 함수를 `const close = () => onClose()`로)
   - [x] `frontend/src/lib/components/ui/Modal.svelte`: `$: if (open)` 반응문 → `$effect(() => { document.body.style.overflow = open ? 'hidden' : ''; })`로 변경
   - [x] `frontend/src/lib/components/ui/Modal.svelte`: `onMount`/`onDestroy`의 keydown 리스너 → `$effect`로 통합 (setup/cleanup 패턴)
3. - [x] **Modal.svelte 템플릿을 Svelte 5 문법으로 전환**
   - [x] `frontend/src/lib/components/ui/Modal.svelte`: `on:click={handleBackdropClick}` → `onclick={handleBackdropClick}`, `on:keydown` → `onkeydown`
   - [x] `frontend/src/lib/components/ui/Modal.svelte`: `on:click={close}` (X 버튼) → `onclick={close}`
   - [x] `frontend/src/lib/components/ui/Modal.svelte`: `<slot />` → `{@render children()}`, `{#if $$slots.footer}` → `{#if footer}`, `<slot name="footer" />` → `{@render footer()}`
   - [x] 사용처 전수 확인 — 11개 파일 모두 이미 `onClose` prop 방식 사용 확인 완료, 추가 수정 불필요

### Phase 3: 필터 상태 URL 동기화

4. - [x] **onMount에서 URL → 필터 상태 복원**
   - [x] `frontend/src/routes/collect/google/GoogleResultsTab.svelte`: `onMount` 내에서 `window.location.search`의 URLSearchParams를 파싱하여 `activeTab`, `query`, `search`, `dateFrom`, `dateTo`, `isRead`, `sortBy`, `sortOrder`, `page`, `pageSize` 각각 복원 (값이 있을 때만 덮어쓰기, 없으면 기본값 유지)
5. - [x] **필터 변경 시 URL params 동기화**
   - [x] `frontend/src/routes/collect/google/GoogleResultsTab.svelte`: `syncFiltersToUrl()` 함수 추가 — 현재 필터 상태를 `URLSearchParams`로 구성하고 `window.history.replaceState`로 URL 업데이트. 기본값과 동일한 파라미터는 URL에서 제거 (깔끔한 URL 유지)
   - [x] `frontend/src/routes/collect/google/GoogleResultsTab.svelte`: `loadResults()` 함수 시작 부분에서 `syncFiltersToUrl()` 호출 (모든 필터 변경이 `loadResults()`를 거치므로 한 곳에서 동기화)
   - [x] `frontend/src/routes/collect/google/GoogleResultsTab.svelte`: `handleReset()` 함수에서 URL params 전체 제거 (`window.history.replaceState(null, '', window.location.pathname + '?tab=results')`)

### Phase 4: 빌드 검증

6. - [x] **프론트엔드 빌드 확인**
   - [x] `cd frontend && npm run build` — TypeScript 타입 오류 없이 빌드 성공 확인
   - [x] 빌드 성공 후 `/collect/google?tab=results` 접속하여 3가지 버그 수정 확인
     - [x] Bug 1: 탭 아이콘이 컴포넌트 wrapper 텍스트 대신 아이콘으로 정상 렌더링
     - [x] Bug 2: 상세 모달 X 버튼 클릭 시 모달 정상 닫힘
     - [x] Bug 3: 새로고침 후 필터 상태(query, dateFrom, dateTo 등) URL에서 복원 확인

---

*상태: 구현완료 | 진행률: 25/25 (100%)*
