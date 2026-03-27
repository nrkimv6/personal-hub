# 사이드바 메뉴 재편 + 스케줄러 독립 페이지

> 작성일: 2026-03-07
> 대상 프로젝트: monitor-page
> 상태: 구현완료
> branch: plan/2026-03-07_sidebar-menu-reorganize
> worktree: .worktrees/2026-03-07_sidebar-menu-reorganize
> 진행률: 32/32 (100%)
> 요약: 스케줄설정이 더이상 크롤링 전용이 아니므로 수집관리에서 분리하여 독립 페이지로 승격하고, 자동화 메뉴를 개발 파이프라인으로 리네이밍, Sleep Now를 시스템/설정으로 이동하는 사이드바 구조 개편.

> 완료일: 2026-03-27
> 아카이브됨

---

## 개요

현재 "수집 관리 > 스케줄 설정" 탭이 Instagram/Google 크롤링뿐 아니라 pytest, Plan 분석, 요구사항 동기화 등 시스템 자동화 작업까지 포함하고 있어 "수집"이라는 맥락에 맞지 않음. 또한 "자동화" 메뉴에 Dev Runner/계획서/Git 관리(개발 파이프라인)와 Sleep Now(시스템 제어)가 혼재되어 있음.

### 변경 후 사이드바 구조

```
대시보드
모니터링        → 네이버 예약, 문화/체육센터, 이벤트
수집 및 콘텐츠   → 수집 관리, AI/글쓰기, 메모
도구 및 파일     → 이미지 분류, 파일 검색, 파일 분류기
개발 파이프라인   → Dev Runner, 계획서, Git 관리      (구 "자동화")
시스템 관리      → 작업 스케줄러, LLM 관리, 시스템/설정  (Sleep Now 흡수)
```

## 기술적 고려사항

- 스케줄 설정 페이지(`collect/schedule/+page.svelte`)는 **1,412줄** 단일 파일 → 그대로 이동 (리팩토링은 별도)
- SleepNowTab(`automation/SleepNowTab.svelte`, 760줄)은 독립 컴포넌트 → 시스템 페이지에 8번째 탭으로 추가
- 시스템 페이지는 이미 7개 탭(서비스 상태, 에러 로그, 데이터 정합성, 브라우저/프록시, 설정, 메모리, 진단) → 1개 추가는 허용 범위
- 자동화 페이지는 4개 탭(Dev Runner, Sleep Now, Git 관리, 계획서) → Sleep Now 제거 후 3개
- 자동화 페이지의 URL 쿼리 기반 탭 관리(`?tab=sleep-now`)에서 `sleep-now` 제거 필요
- 현재 navigation.ts 구조: Dashboard / Monitoring / Content Collection(수집 관리,AI/글쓰기,메모) / Tools / System Management(자동화,LLM 관리,시스템/설정)
- navigation.ts의 "System Management" 그룹을 분할: "개발 파이프라인"(자동화 리네이밍) + "시스템 관리"(LLM 관리, 시스템/설정, 작업 스케줄러)
- collect layout의 navTabs: posts, rules, history, **schedule**, google → schedule 제거 필요
- 기존 `/collect/schedule` 북마크/링크 → `/scheduler`로 리다이렉트 제공

---

## TODO

### Phase 1: 사이드바 메뉴 재편

1. [x] **navigation.ts 메뉴 구조 변경**
   - [x] `frontend/src/lib/navigation.ts`: 현재 "System Management" 그룹(자동화, LLM 관리, 시스템/설정) → 2개 그룹으로 분할
   - [x] `frontend/src/lib/navigation.ts`: 새 그룹 "개발 파이프라인" 생성 — 기존 "자동화" 항목을 이동 + label "개발 파이프라인"으로 변경 (href: `/automation` 유지)
   - [x] `frontend/src/lib/navigation.ts`: "시스템 관리" 그룹에 `{ href: '/scheduler', label: '작업 스케줄러' }` 추가 (LLM 관리 앞, 첫 번째 위치)
   - [x] `frontend/src/lib/navigation.ts`: 그룹 아이콘 — 개발 파이프라인: `Code` 또는 `GitBranch`, 시스템 관리: 기존 아이콘 유지
   - [x] `frontend/src/lib/navigation.ts`: "수집 관리" 항목이 있는 "Content Collection" 그룹명 → "수집 및 콘텐츠"로 변경 (사이드바 구조도와 일치시킴)

### Phase 2: 작업 스케줄러 독립 페이지 생성

2. [x] **라우트 생성 및 코드 이동**
   - [x] `frontend/src/routes/scheduler/+page.svelte`: 신규 생성 — TabNav로 "스케줄 목록" | "실행 이력" 탭 구성
   - [x] `frontend/src/routes/scheduler/ScheduleListTab.svelte`: `collect/schedule/+page.svelte` 코드를 컴포넌트로 이동
   - [x] `frontend/src/routes/scheduler/RunHistoryTab.svelte`: 실행 이력 탭 (TaskScheduleRun 기반, 기존 collect/history와 별도)

3. [x] **기존 스케줄 페이지 리다이렉트**
   - [x] `frontend/src/routes/collect/schedule/+page.svelte`: `/scheduler`로 리다이렉트 처리 (또는 삭제 후 +page.server.ts에서 redirect)

### Phase 3: 수집 관리 탭 정리

4. [x] **수집 관리 레이아웃에서 스케줄 탭 제거 + 리네이밍**
   - [x] `frontend/src/routes/collect/+layout.svelte`: `schedule` 탭 항목 제거
   - [x] `frontend/src/routes/collect/+layout.svelte`: "크롤링 이력" → "수집 이력" 리네이밍

### Phase 4: 자동화 → 개발 파이프라인

5. [x] **자동화 페이지에서 Sleep Now 제거 + 리네이밍**
   - [x] `frontend/src/routes/automation/+page.svelte`: `autoTabs` 배열에서 `sleep-now` 탭 객체 제거 (4탭→3탭: Dev Runner, Git 관리, 계획서)
   - [x] `frontend/src/routes/automation/+page.svelte`: `MainTab` 타입에서 `'sleep-now'` 리터럴 제거
   - [x] `frontend/src/routes/automation/+page.svelte`: URL 파라미터 파싱(`?tab=sleep-now`) 분기 제거
   - [x] `frontend/src/routes/automation/+page.svelte`: `SleepNowTab` import 문 제거
   - [x] `frontend/src/routes/automation/+page.svelte`: 페이지 타이틀/메타 "자동화" → "개발 파이프라인" 변경

### Phase 5: 시스템/설정에 Sleep Now 흡수

6. [x] **시스템 페이지에 Sleep Now 탭 추가**
   - [x] `frontend/src/routes/system/+page.svelte`: SleepNowTab import 추가 + 탭 배열에 "Sleep Now" 항목 추가
   - [x] `frontend/src/routes/automation/SleepNowTab.svelte` → `frontend/src/routes/system/SleepNowTab.svelte`: 파일 이동
   - [x] `frontend/src/routes/system/+page.svelte`: Sleep Now 탭 선택 시 SleepNowTab 컴포넌트 렌더링

### Phase 6: 검증

7. [x] **동작 검증**
   - [x] 사이드바 메뉴 5개 그룹(대시보드, 모니터링, 수집 및 콘텐츠, 도구 및 파일, 개발 파이프라인, 시스템 관리) 정상 렌더링 확인
   - [x] `/scheduler` 페이지 접근 및 탭(스케줄 목록/실행 이력) 전환 확인
   - [x] `/collect/schedule` → `/scheduler` 리다이렉트 동작 확인
   - [x] `/automation` 페이지에서 Sleep Now 탭 사라짐 확인, 타이틀 "개발 파이프라인" 확인
   - [x] `/system` 페이지에서 Sleep Now 탭 추가 및 동작 확인 (8번째 탭)
   - [x] 수집 관리 탭에서 "스케줄" 탭 사라짐, "수집 이력" 리네이밍 확인

---

*상태: 구현완료 | 진행률: 32/32 (100%)*
