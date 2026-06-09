# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 16

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub, tool-pdf-to-img (배포된 Cloud Run 및 연계 GCP 리소스)
> 실행순서: 16
> 선행조건: todo-1~15 완료 + 각 Phase M deployment 승인
> branch:
> worktree:
> worktree-owner:
> 테스트명령: 배포된 GCP 환경에서 pytest -m http_live (T5) + pytest -m e2e (T4). **monitor-page worktree에서 실행 금지** — 대상 repo CI 또는 배포 owner에서 실행
> 진행률: 0/11 (0%)
> 요약: 15개 child 산출물이 실제 배포됐을 때 end-to-end로 동작하는지 검증하는 live 통합 테스트(T4/T5)를 정의한다. design-doc 검증이 아니라 deployed GCP 리소스 대상 live 검증이며, cost-guard 기본 disable이 실제로 과금 리소스를 만들지 않는지까지 확인한다.

## TODO

### Phase 1: T5 — HTTP live (배포된 endpoint)

1. - [ ] **Cloud Run live HTTP 검증** — mock/TestClient 금지
   - [ ] personal-hub Cloud Run read-only/health endpoint가 배포 URL 대상 live 200 응답 (DB 의존 route는 503 명시 응답)
   - [ ] tool-pdf-to-img Cloud Run 변환 endpoint가 샘플 PDF 업로드 → 이미지 200 반환
   - [ ] 테스트는 배포 URL 대상 `requests.get`/`httpx.get` live 호출로 작성한다 (`page.route("**/*")` 전체 mock, `TestClient` 단독 금지)

### Phase 2: T4 — E2E live pipeline

2. - [ ] **데이터 파이프라인 end-to-end** — read-back 검증
   - [ ] 이벤트 1건 발생 → Cloud Logging 엔트리 적재 → BigQuery export row 존재를 쿼리로 read-back 확인
   - [ ] Pub/Sub publish → Cloud Tasks dispatch → task accepted/status 전이를 read-back 확인 (활성화 시)
   - [ ] Cloud Scheduler 트리거 → 대상 job 1회 실행 로그 확인 (활성화 시)

3. - [ ] **cost-guard 기본 disable live 검증** — 과금 0 보장
   - [ ] 기본값(`ENABLE_*=false`)에서 gcloud read-back으로 과금 리소스 0개 확인 (Artifact Registry repo 0, Cloud Scheduler job 0, Secret 활성 버전 0, 생성 GCS 객체 0)
   - [ ] 플래그를 명시적으로 enable했을 때만 해당 리소스가 생성됨을 역검증한다

### Phase M: Merge/Deploy Handoff

> live 통합 테스트는 monitor-page worktree가 아니라 배포된 GCP 환경(대상 repo CI 또는 배포 owner)에서 실행한다. deployment 승인 전에는 test spec만 확정하고 실행하지 않는다. 실행 없이 "통과"로 체크하지 않는다.

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: 배포된 모든 endpoint가 정의된 계약(read-only 200 / DB 의존 503 / 변환 200)대로 응답한다.
- **B**oundary: 통합 테스트 1회 완주가 free-tier 소비 한도 내에서 끝난다.
- **I**nverse: cost-guard 기본 disable 상태에서 과금 리소스가 0개임을 gcloud read-back으로 역검증한다.
- **C**ross-check: BigQuery row ↔ 발생 이벤트, Cloud Logging 엔트리 ↔ 요청을 교차 확인한다.
- **E**rror: DB 의존 route는 503, 손상/대용량 PDF는 에러, server-side proxy 부재 시 Gemini assist는 비활성임을 live로 확인한다.
- **P**erformance/cost: 통합 테스트 실행이 free-tier 한도를 넘지 않고, 실행 후 생성된 일시 리소스를 정리한다.

---

*진행률: 0/11 (0%)*
