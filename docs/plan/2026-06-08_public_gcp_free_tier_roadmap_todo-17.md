# nrkimv6 Public Repo GCP Free-Tier 적용 로드맵 — TODO 17

> 계획서: [plan](./2026-06-08_public_gcp_free_tier_roadmap.md)
> 대상 프로젝트: personal-hub
> 실행순서: 17
> 선행조건: ./2026-06-15_cloud-run-poc-design-contract.md + ../archive/2026-06-08_public_gcp_free_tier_roadmap_todo-2.md
> branch:
> worktree:
> worktree-owner:
> 상태: 구현완료
> 머지커밋: 8e61b5fb
> 테스트명령: Python 변경 시 pytest T1~T3 로컬 실행, T4/T5 live 검증은 배포 후 todo-16 위임
> 진행률: 27/27 (100%)
> 요약: 설계 계약서 Option A 기반으로 app/main_cloudrun.py slim entrypoint와 Dockerfile.cloudrun을 작성하고 Cloud Run 배포 command를 문서화한다.

## 배경

`2026-06-15_cloud-run-poc-design-contract.md`에서 확정된 Option A 구현 단계다.

**현재 차단 사항**:
- `app/router_registry.py`: personal-hub에 없음 (monitor-page에만 존재) — `app/main_admin.py` line 88에서 import하여 main_admin.py 기동 불가
- `app/main_cloudrun.py`: 미존재 (이 todo에서 신규 작성)
- `Dockerfile.cloudrun`: 미존재 (이 todo에서 신규 작성)

## Cloud Run 배포 커맨드 (Phase 3 확정값)

```bash
# 이미지 빌드 및 푸시
docker build -f Dockerfile.cloudrun -t gcr.io/<PROJECT_ID>/personal-hub-poc:latest .
docker push gcr.io/<PROJECT_ID>/personal-hub-poc:latest

# Cloud Run 배포
gcloud run deploy personal-hub-poc \
  --image gcr.io/<PROJECT_ID>/personal-hub-poc:latest \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --min-instances=0 \
  --port=8080
```

| 결정 항목 | 값 |
|----------|-----|
| service name | `personal-hub-poc` |
| region | `asia-northeast3` (서울) |
| unauthenticated | `--allow-unauthenticated` |
| min instances | `--min-instances=0` (idle 과금 없음) |
| cold start timeout | 60초 |
| max concurrency | 80 (Cloud Run default) |
| IMAGE_URL | `gcr.io/<PROJECT_ID>/personal-hub-poc:latest` |
| 배포 후 URL | `https://personal-hub-poc-<hash>-an.a.run.app` (placeholder) |

> todo-16 선행조건: 배포 URL `https://personal-hub-poc-<hash>-an.a.run.app` 확정 후 T4/T5 live 검증 수행

**확인된 참조처**:
- `app/main_admin.py:88` — `from app.router_registry import register_routers` (기동 blocker)
- `app/core/runtime_fingerprint.py:21` — `"app/router_registry.py"` 경로 참조 (존재 체크)

todo-16 live T4/T5 검증은 이 todo의 배포 완료 후 실행된다.

## TODO

### Phase 0: Worktree 준비

0. - [x] **worktree 생성 또는 재개**
   - [x] `git worktree add .worktrees/impl/gcp-todo-17-cloudrun-impl -b impl/gcp-todo-17-cloudrun-impl` 실행
   - [x] 이 plan 헤더 `> branch: impl/gcp-todo-17-cloudrun-impl` / `> worktree: .worktrees/impl/gcp-todo-17-cloudrun-impl` / `> worktree-owner: <절대경로>` 기록
   - [x] `2026-06-15_cloud-run-poc-design-contract.md` 상태 필드를 `초안` → `확정`으로 업데이트 (todo-2 archive 구현완료로 선행조건 충족)

### Phase 1: app/main_cloudrun.py 작성

1. - [x] **slim entrypoint 구현**
   - [x] `app/main_cloudrun.py` 신규 작성 — `from fastapi import FastAPI` 단 1개 import
   - [x] `app = FastAPI(title="personal-hub Cloud Run PoC")` 설정
   - [x] `@app.get("/")` → `return {"status": "ok", "version": "poc"}`
   - [x] `@app.get("/healthz")` → `return {"healthy": True}`
   - [x] `grep -n "router_registry\|lifespan\|database\|redis" app/main_cloudrun.py` 결과 0건 확인
   - [x] `app/core/runtime_fingerprint.py` `DEFAULT_SOURCE_FILES`에 `main_cloudrun.py` 추가 없음 확인 (독립 유지)

### Phase 2: Dockerfile.cloudrun + requirements-cloudrun.txt 작성

2. - [x] **slim 컨테이너 정의**
   - [x] `requirements-cloudrun.txt` 신규 작성 — `fastapi==0.104.1` + `uvicorn==0.24.0` 2줄만 (requirements.txt 전체 COPY 금지)
   - [x] `Dockerfile.cloudrun` 신규 작성 — base image `python:3.11-slim`
   - [x] `WORKDIR /app`, `COPY requirements-cloudrun.txt .`, `RUN pip install --no-cache-dir -r requirements-cloudrun.txt`
   - [x] `COPY app/ app/` (app 패키지만, playwright·browser·psycopg2 미포함 확인)
   - [x] `CMD ["sh", "-c", "uvicorn app.main_cloudrun:app --host 0.0.0.0 --port ${PORT:-8080}"]` 설정

### Phase 3: Cloud Run 배포 command 문서화

3. - [x] **배포 절차 기록** (이 plan 파일 `## 배경` 섹션 하단 또는 inline 노트로 추가)
   - [x] service name `personal-hub-poc`, region `asia-northeast3`(서울), `--allow-unauthenticated`, `--min-instances=0` 결정값 기록
   - [x] `gcloud run deploy personal-hub-poc --image <IMAGE_URL> --region asia-northeast3 --allow-unauthenticated --min-instances=0 --port=8080` 샘플 기록
   - [x] IMAGE_URL placeholder: `gcr.io/<PROJECT_ID>/personal-hub-poc:latest` 형식 명시
   - [x] `todo-16` 선행조건 필드에 `배포 URL: https://personal-hub-poc-<hash>-an.a.run.app` placeholder 기재

### Phase T1: pytest 단위 TC (RIGHT-BICEP)

4. - [x] **단위 테스트 작성** (`tests/test_main_cloudrun.py` 신규)
   - [x] `test_root_returns_200_with_status_ok()` — R: TestClient `GET /` → 200 + `{"status": "ok", "version": "poc"}`
   - [x] `test_healthz_returns_200_with_healthy_true()` — R: TestClient `GET /healthz` → 200 + `{"healthy": True}`
   - [x] `test_app_title_is_poc()` — C: `from app.main_cloudrun import app; assert app.title == "personal-hub Cloud Run PoC"`
   - [x] `test_no_router_registry_import()` — I: `pathlib.Path("app/main_cloudrun.py").read_text()` 에서 `router_registry` 0건 assert
   - [x] `test_no_lifespan_import()` — I: 동일 소스에서 `lifespan` 0건 assert
   - [x] `test_root_no_db_dependency()` — E: DB/Redis env 미설정 상태에서 `GET /` 200 확인 (TESTING env 불필요, slim entrypoint는 DB 의존 없음)

### Phase T2: local pytest 실행

5. - [x] **단위 테스트 실행** (worktree cwd에서)
   - [x] `TESTING=1 pytest tests/test_main_cloudrun.py -v` 실행 + 6개 PASSED 확인
   - [x] 기존 테스트 회귀 확인: `TESTING=1 pytest tests/test_api_ready_http.py -v` — pre-existing 실패 (app.main 없음, main branch에서도 동일), 이 todo 변경에 의한 회귀 아님

### Phase T3: import smoke

6. - [x] **import smoke** (worktree cwd에서)
   - [x] `python -c "from app.main_cloudrun import app; print(app.title)"` → `personal-hub Cloud Run PoC` 출력 확인
   - [x] `python -c "import pathlib; src=pathlib.Path('app/main_cloudrun.py').read_text(); assert 'router_registry' not in src and 'lifespan' not in src; print('clean')"` → `clean` 출력 확인

### Phase T4: E2E

> T4 해당 없음: health endpoint 2개만 노출하는 slim entrypoint. Playwright E2E 불필요. GCP Cloud Run URL live 검증은 todo-16 위임.

### Phase T5: HTTP 통합 테스트

7. - [x] **TestClient HTTP 통합** (`tests/test_main_cloudrun_http.py` 신규 — 프로젝트 `*_http.py` 패턴 준수)
   - [x] `test_root_http_200()` — TestClient `GET /` → 200 + `{"status": "ok", "version": "poc"}` body assert
   - [x] `test_healthz_http_200()` — TestClient `GET /healthz` → 200 + `{"healthy": True}` body assert
   - [x] `TESTING=1 pytest tests/test_main_cloudrun_http.py -v` 실행 + PASSED 확인

> T5 live (GCP Cloud Run URL): todo-16에서 배포 후 수행. 이 단계에서 live URL 호출 금지.

### Phase M: Merge Handoff

> T4/T5 live (GCP 배포 URL): 배포 owner 또는 todo-16에서 수행. 이 phase에서는 live GCP URL 호출 금지.

### Phase Z: Post-Merge Cleanup

Z. - [ ] **post-merge 정리**
   - [ ] `git worktree remove .worktrees/impl/gcp-todo-17-cloudrun-impl`
   - [ ] `git branch -d impl/gcp-todo-17-cloudrun-impl`
   - [ ] 이 plan 헤더 `> branch:` / `> worktree:` / `> worktree-owner:` 값 제거

### 검증 기준 (RIGHT-BICEP)

- **R**ight: `GET /`와 `GET /healthz`가 pytest T1/T5에서 200 반환.
- **B**oundary: cold start 60초·concurrency 80·min-instances 0 Phase 3 문서화.
- **I**nverse: `router_registry`·`lifespan` import 0건 — T1 + T3 확인.
- **C**ross-check: 선행조건이 todo-2 설계 계약서를 참조, Phase 0에서 `확정` 상태 업데이트.
- **E**rror: `router_registry.py` 미생성 상태에서 `main_cloudrun.py`가 정상 기동됨 — T3 import smoke.
- **P**erformance/cost: min-instances 0 + unauthenticated 접근 free-tier 범위 — Phase 3 문서화.

---

*진행률: 27/27 (100%) | 상태: 머지대기*
