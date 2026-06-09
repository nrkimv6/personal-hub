# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 15

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 15
> 선행조건: ./2026-06-08_public_gcp_free_tier_roadmap_todo-2.md
> branch:
> worktree:
> worktree-owner:
> 테스트명령: CI spec 문서 검증
> 진행률: 0/7 (0%)
> 요약: `personal-hub` Cloud Run PoC에만 Cloud Build와 Artifact Registry 기준을 붙인다.

## TODO

### Phase 1: CI 대상 결정

1. - [ ] **container build 대상 고정** — 중복 CI 방지
   - [ ] `personal-hub`: TODO 2가 유지되면 FastAPI demo image를 1순위로 둔다
   - [ ] `tool-pdf-to-img`는 TODO 14 완료 후 별도 후속 plan으로 분리한다고 기록한다

2. - [ ] **Cloud Build/Artifact Registry 기준 작성** — 비용 상한
   - [ ] `docs/plan`: image retention, tag policy, build minute 상한을 작성한다
   - [ ] `docs/plan`: Cloudflare/Svelte static repo에는 Artifact Registry를 붙이지 않는다고 명시한다
   - [ ] `docs/plan`: Cloud Build·Artifact Registry는 옵션 플래그(`ENABLE_CLOUD_BUILD`, `ENABLE_ARTIFACT_REGISTRY`, 기본값 `false`)로 gate하고, 기본 disable·명시적 opt-in 시에만 활성화하는 기준을 작성한다 (Artifact Registry 0.5GB·Cloud Build 120 build-min/day 초과 시 과금)

### Phase M: Merge Handoff

> 실제 Cloud Build trigger 생성과 push 권한 설정은 선택된 repo의 post-merge/deploy owner에서 수행한다.

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: build 대상이 FastAPI demo image 1순위로 고정되고 TODO 2 유지 조건과 일치한다.
- **B**oundary: image retention, tag policy, build minute 상한과 Artifact Registry 0.5GB·Cloud Build 120 build-min/day 경계가 명시된다.
- **I**nverse: Cloudflare/Svelte static repo에 Artifact Registry를 붙이지 않음을 역으로 확인한다.
- **C**ross-check: TODO 2 유지 여부와 build 대상 선정을 교차 확인한다(중복 CI 방지).
- **E**rror: build 실패 또는 이미지 저장 초과 시 처리 기준이 있다.
- **P**erformance/cost: `ENABLE_CLOUD_BUILD=false`·`ENABLE_ARTIFACT_REGISTRY=false` 기본값에서 build/저장 0 → 과금 0.

---

*진행률: 0/7 (0%)*
