# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 7

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 7
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-1.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: storage policy 문서 검증
> 진행률: 0/7 (0%)
> 요약: report/export/screenshot artifact를 민감정보 제거 샘플 버킷으로 저장하는 PoC를 설계한다.

## TODO

### Phase 1: Artifact Boundary

1. - [ ] **artifact source 후보 확인** — 민감정보 제거
   - [ ] `app/modules/reports`: export 가능한 sample report artifact 후보를 확인한다
   - [ ] `app/modules/slide_scanner`: 공개 가능한 synthetic artifact 후보를 확인한다

2. - [ ] **Cloud Storage 정책 작성** — 비용/권한 제한
   - [ ] `docs/plan`: bucket location, lifecycle retention, public access prevention 기준을 작성한다
   - [ ] `docs/plan`: personal data artifact 업로드 금지 조건을 작성한다
   - [ ] `docs/plan`: GCS export는 옵션 플래그(`ENABLE_GCS_ARTIFACTS`, 기본값 `false`)로 gate하고, 기본 disable·명시적 opt-in 시에만 활성화하는 기준을 작성한다 (non-US 리전 또는 5GB 초과 시 과금)

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: export 가능한 sample report/synthetic artifact 후보가 정의된다.
- **B**oundary: bucket location, lifecycle retention, public access prevention 기준과 5GB·non-US 리전 경계가 명시된다.
- **I**nverse: personal data artifact가 0건 업로드됨을 역검증한다.
- **C**ross-check: artifact source(reports/slide_scanner)와 민감정보 부재를 교차 확인한다.
- **E**rror: 민감 artifact 업로드 시도 시 차단한다.
- **P**erformance/cost: `ENABLE_GCS_ARTIFACTS=false` 기본값에서 생성 객체 0개 → 과금 0.

---

*진행률: 0/7 (0%)*
