# Playwright Dummy Plan

> 작성일시: 2026-05-21 18:15
> 대상 프로젝트: monitor-page
> 상태: 구현중
> 요약: dev-runner lifecycle tests use this disposable plan only inside temp repositories.

## Contract

- This fixture is for `test_source` runner automation only.
- It must not modify production paths or the main monitor-page worktree.
- Test harnesses may copy it into a temp directory and create only temp marker files.
- Runner logs must include `DUMMY_PLAN_PLAYWRIGHT_SENTINEL` so API/UI assertions can read back execution output.

## TODO

1. [ ] Create temp marker file `dummy-plan-playwright-marker.txt`.
2. [ ] Emit `DUMMY_PLAN_PLAYWRIGHT_SENTINEL`.
3. [ ] Let the isolated test harness merge the marker from its temp branch.
