# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 1

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 1
> 선행조건: 없음
> branch:
> worktree:
> worktree-owner:
> 테스트명령: 문서/설정 plan, 구현 전 secret scan evidence
> 진행률: 0/10 (0%)
> 요약: `personal-hub`의 backend/frontend env boundary를 확인하고 Secret Manager PoC 기준을 문서화한다.

## TODO

### Phase 1: Secret Boundary 확인

1. - [ ] **public sanitization evidence 고정** — 공개 repo 상태 확인
   - [ ] `README.md`: public sanitization 설명과 removed content 범위를 인용 없이 요약한다
   - [ ] `.env.example`: 실제 secret 값이 없는 placeholder인지 확인한다
   - [ ] `frontend/.env.example`: public frontend key와 secret 후보를 분리한다

2. - [ ] **Secret Manager 후보 분류** — backend 설정 키 분류
   - [ ] `app/core/config.py`: Secret Manager로 옮길 backend secret key 목록을 작성한다
   - [ ] `app/core/config.py`: public demo에서 빈 값 허용 가능한 key를 별도 목록으로 작성한다

### Phase 2: 완료 기준

3. - [ ] **문서화 기준 작성** — 후속 TODO 선행조건
   - [ ] `docs/plan`: secret source-of-truth를 GCP Secret Manager 또는 기존 hosting secret으로 분류하는 표를 둔다
   - [ ] `docs/plan`: Secret Manager는 옵션 플래그(`ENABLE_SECRET_MANAGER`, 기본값 `false`)로 gate하고, 기본 disable·명시적 opt-in 시에만 활성화하는 기준을 작성한다 (활성 버전 6개 초과 시 과금)

### 검증 기준 (RIGHT-BICEP TC)

- **R**ight: backend secret key 목록과 public 허용(빈 값 가능) key 목록이 상호 배타적이고, 합집합이 `config.py` 전체 설정 키를 덮는다.
- **B**oundary: public 허용 key는 빈 문자열/누락 상태에서도 앱이 기동한다(필수 검증 통과).
- **I**nverse: `.env.example`/`frontend/.env.example`에 실제 secret 값이 0건이고 placeholder만 존재함을 역검증한다.
- **C**ross-check: secret scan(gitleaks 등) 결과가 분류표와 일치한다 — scan이 잡은 모든 secret이 Secret Manager 목록에 포함된다.
- **E**rror: public 허용 목록에 실제 secret이 섞이면 분류 실패로 표시한다.
- **P**erformance/cost: `ENABLE_SECRET_MANAGER=false` 기본값에서 활성 secret 버전 0개 → 과금 0.

---

*진행률: 0/10 (0%)*
