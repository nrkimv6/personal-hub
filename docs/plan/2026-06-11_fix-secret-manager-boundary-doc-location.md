# fix: secret-manager-boundary.md docs/plan/ → docs/gcp/ 경로 수정

> 작성일시: 2026-06-11 04:15
> 기준커밋: 24902ec4
> 대상 프로젝트: personal-hub
> 상태: 초안
> surface 분류: 해당 없음
> branch:
> worktree:
> worktree-owner:
> 진행률: 0/7 (0%)
> 요약: fix: todo-1에서 잘못 지정된 경로로 커밋된 참고문서를 올바른 위치로 이동한다 — `docs/plan/` 은 계획서 전용이므로 GCP 참고문서는 `docs/gcp/` 하위로 이동.

---

## 개요

todo-1 계획서가 `docs/plan/secret-manager-boundary.md` 경로를 명시했으나,
`docs/plan/` 은 계획서 파일 전용 디렉토리다. Secret Manager 후보 분류표는
계획서가 아니라 참고 문서(reference doc)이므로 `docs/gcp/` 하위가 올바르다.

커밋 `24902ec4` 에 잘못된 경로로 포함됨.

## 기술적 고려사항

- personal-hub의 `.gitignore` 에 `.worktrees/` 가 포함되어 있어
  `git worktree add .worktrees/<name>` 이 실패한다.
  impl 워크트리는 repo 외부 경로(`../ph-impl-fix-doc-loc`)에 생성한다.
- 참조 경로 수정 대상:
  - `.worktrees/plans/docs/archive/2026-06-08_public_gcp_free_tier_roadmap_todo-1.md` — Phase 1-2 및 Phase 2-1 체크박스에 `docs/plan/secret-manager-boundary.md` 경로가 언급됨

## 기존 데이터 영향

- 계약 변경 여부: N/A
- 기존 active/enabled 데이터 영향: N/A
- invalidated 데이터 처리: N/A
- 완료 evidence: `docs/gcp/secret-manager-boundary.md` 파일 존재 + `docs/plan/` 에 해당 파일 부재 read-back

## 상태 머신 6축 TC matrix

N/A: 상태 머신 detector seed 없음

---

## TODO

### Phase 0: Worktree 준비

0. ☐ **worktree 준비 상태를 문서에 고정** — `/implement` 진입 게이트
   - ☐ `이 plan`: `> branch:`, `> worktree:`, `> worktree-owner:` 슬롯을 유지한다
   - ☐ `이 plan`: blank 슬롯은 신규 초기 상태이며 다른 `impl/*` 잔여와 무관하다
   - ☐ `이 plan`: personal-hub `.gitignore` 에 `.worktrees/` 가 포함되어 있으므로 impl 워크트리는 `../ph-impl-fix-doc-loc` 경로에 생성한다: `git worktree add ../ph-impl-fix-doc-loc -b impl/fix-doc-location`
   - ☐ `이 plan`: worktree cwd = `../ph-impl-fix-doc-loc` 로 고정한다

### Phase 1: 파일 이동

1. ☐ **docs/gcp/ 디렉토리 생성 및 파일 이동** — 올바른 참고문서 위치로
   - ☐ impl worktree cwd에서 `git mv docs/plan/secret-manager-boundary.md docs/gcp/secret-manager-boundary.md` 실행
   - ☐ `docs/plan/secret-manager-boundary.md` 부재 확인 (Glob으로 검증)
   - ☐ `docs/gcp/secret-manager-boundary.md` 존재 확인 (Read 첫 줄 검증)

### Phase 2: 참조 경로 업데이트

2. ☐ **아카이브된 todo-1 계획서 경로 수정** — 참조 일관성
   - ☐ `.worktrees/plans/docs/archive/2026-06-08_public_gcp_free_tier_roadmap_todo-1.md`: `docs/plan/secret-manager-boundary.md` 문자열을 `docs/gcp/secret-manager-boundary.md` 로 전체 교체 (replace_all)
   - ☐ 수정 후 Read로 교체 결과 확인 — `docs/plan/secret-manager-boundary.md` 잔류 없음

### Phase Z: Post-Merge Cleanup (/merge-test owner)

Z. ☐ **post-merge 정리 확인** — `/merge-test` owner
   - ☐ `이 plan`: main merge 시도를 owner step으로 적는다
   - ☐ `이 plan`: T4/T5 해당 없음 — 문서 이동만, Python/API 코드 변경 없음
   - ☐ `이 plan`: worktree remove (`../ph-impl-fix-doc-loc`), branch remove, header meta 제거를 분리해 적는다

> T4 해당 없음: 문서 파일 이동만이며 백엔드/API/프론트엔드 코드 변경 없음
> T5 해당 없음: 동일 사유

---

*상태: 초안 | 진행률: 0/7 (0%)*
