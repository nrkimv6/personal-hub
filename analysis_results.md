# `.claude` 대비 `.gemini` 및 `.agent` 이식 검토 보고서

`D:\work\project\service\wtools` 내의 `.claude`, `.gemini`, `.agent` 디렉토리를 비교 및 분석하여, 과거 Claude 환경에서 사용되었으나 현재 Gemini/Agent 환경으로 아직 이식되지 않은 유용한 기능과 문서들을 조사했습니다.

## 🚀 워크플로우 (Skills / Commands) 이식 후보

현재 `.agent/workflows` 및 `.gemini/commands`에는 없지만, `.claude/skills`에는 존재하는 주요 기능들입니다. 파이프라인의 완성도를 높이기 위해 이식이 권장됩니다.

### 1. merge-test (`/merge-test`)
- **역할**: `/implement` 완료 후, worktree 브랜치를 main에 자동 병합하고 T4(E2E) / T5(HTTP) 통합 테스트를 실행한 뒤 일괄 완료 처리(`/done`)하는 워크플로우.
- **이식 필요성**: **높음**. v2 파이프라인에서 단위 테스트(T1/T2)와 통합 테스트/머지가 분리되었는데, 머지와 후속 테스트 자동화를 담당하는 핵심 단계입니다.

### 2. reflect & review-plan (`/reflect`, `/review-plan`)
- **역할**:
  - `/reflect`: 구현 완료 후 대화 컨텍스트를 분석하여 우려점, 유사 문제, 리팩토링 필요성, 미발견 오류 등을 추출해 새 계획서로 자동 생성.
  - `/review-plan`: 생성된 계획서를 재검토하고 오류를 걸러낸 뒤 `/expand-todo`를 통해 체크리스트를 구체화.
- **이식 필요성**: **중간**. 자생적인 코드 품질 향상과 후속 작업 발굴을 자동화하는 데 유용합니다.

### 3. batch-done (`/batch-done`)
- **역할**: LLM의 판단(`archive-sweep`)에 의존하지 않고, 체크박스가 100% 완료된 `_todo.md` 파일들을 기계적으로 탐색하여 일괄적으로 완료 처리(TODO→DONE 이동, 아카이브, 커밋)를 수행.
- **이식 필요성**: **중간**. 다수의 소규모 작업이 완료되었을 때 이를 한 번에 정리하기 위한 효율적인 도구입니다.

### 4. debug-parallel (`/debug-parallel`)
- **역할**: 버그 조사 시 코드를 즉시 변경하지 않고, 백엔드 경로/프론트 상태/Git 이력/테스트 결과를 병렬 Task로 조사하여 근본 원인을 교차 검증하는 워크플로우.
- **이식 필요성**: **높음**. Gemini의 기능(Agentic Mode)과 결합 시, 환각(Hallucination)에 의한 섣부른 코드 수정을 막는 매우 효과적인 디버깅 패턴입니다.

### 5. design-prompt & report (`/design-prompt`, `/report`)
- **역할**:
  - `/design-prompt`: AI가 UI를 설계할 때 기술 종속성을 피하고 "보이는 것과 할 수 있는 것" 위주로 선언적 프롬프트를 작성해 주는 가이드.
  - `/report`: 계획서(`docs/plan/`) 없이 진행된 즉석 분석이나 장애 조사의 결과를 채팅에만 남기지 않고 반드시 파일(`docs/reports/`)로 기록하도록 강제하는 워크플로우.
- **이식 필요성**: **선택적**. 작업 이력의 형상화에 도움이 됩니다.

---

## 📚 컨벤션 및 가이드 문서 이식 후보

### recurring-patterns (`.claude/skills/recurring-patterns/`)
- **구성**:
  - `SKILL.md` (Svelte 5 룰 등 프론트/백엔드 공통)
  - `backend-patterns.md` (백엔드 전용)
  - `pagination.md`, `user-feedback.md`
- **역할**: Svelte 5 문법 강제(예: `on:click` 대신 `onclick` 사용), `createSelection()` 유틸리티 사용, 백엔드 폴링 로직 등 코드베이스의 확립된 관례 모음. 다른 스킬 구현 시 참조됨.
- **이식 필요성**: **매우 높음**. Gemini 에이전트가 코드를 작성할 때 일관된 프로젝트 컨벤션을 따르게 하려면 `.agent/rules/` 디렉토리 하위로 반드시 편입해야 할 내용입니다.

---

## 🤖 에이전트 페르소나 (Agents) 관련

### `.claude/agents/` 디렉토리
- **구성**: `auto-impl.md`, `auto-verify.md`, `auto-done.md`, `auto-test-e2e.md` 등.
- **분석**: 이 파일들은 과거 Claude CLI가 개별 Task를 수행할 때 주입받던 시스템 프롬프트(I/O Contract, 실행 흐름, 파이프라인 호환 규칙 등)입니다.
- **의견**: 현재 Gemini 환경(특히 Plan Runner v2)에서 Python 기반의 `executor.py` 및 도구(Tools) 기반 에이전트 체제로 개편되었다면, 이 Markdown 문서들의 내용 중 **에이전트 제약 사항 및 예외 처리 로직**을 추출하여 `.agent/workflows` 내의 해당 md 파일로 병합하거나, `GEMINI.md`에 추가하는 방식으로 녹여내는 적응형 이식이 필요해 보입니다.

---

## 📝 결론 및 제안
가장 시급하게 검토할 만한 이식 대상은 다음 세 가지입니다:
1. 에이전트의 코드 일관성을 위한 **`recurring-patterns`의 `.agent/rules/`로의 편입**
2. 워크트리 구현 후 통합 플로우인 **`merge-test` 워크플로우 신설**
3. 섣부른 수정을 막기 위한 **`debug-parallel` 기반의 디버깅 규칙 적용**
