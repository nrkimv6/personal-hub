"""Provider-specific prompt policy for Plan Archive analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


DEFAULT_CATEGORIES = [
    "naver-booking",
    "instagram",
    "google-search",
    "activity",
    "claude-worker",
    "video",
    "infra",
    "writing",
    "common",
]

POLICY_VERSION = "2026-05-06.1"


@dataclass(frozen=True)
class PromptPolicyContext:
    caller_type: str
    provider: str
    model: str
    filename: str
    existing_categories: list[str]


@dataclass(frozen=True)
class Policy:
    id: str
    version: str
    provider: str
    model_match: Optional[Callable[[str], bool]]
    instructions: str

    def matches(self, provider: str, model: str) -> bool:
        if self.provider != _normalize(provider):
            return False
        if self.model_match is None:
            return True
        return self.model_match(model or "")


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _contains(*needles: str) -> Callable[[str], bool]:
    lowered = tuple(needle.lower() for needle in needles)

    def match(model: str) -> bool:
        value = (model or "").lower()
        return all(needle in value for needle in lowered)

    return match


COMMON_SCHEMA_RULES = """**정규화 규칙:**
- trigger 판정 규칙: 실제 결함, 데이터 손실, 회귀 방어, 장애 재발 방지가 핵심이면 `bug_recurrence`; 사용성/화면 흐름/표시 개선이 핵심이면 `ux_improvement`; 새 능력이나 새 화면이 핵심이면 `new_feature`; 구조 정리만 핵심이면 `refactor`; 운영/배포/테스트 인프라가 핵심이면 `infra`; 근거가 부족하면 `unknown`.
- tags는 1~2개만 고릅니다. `refactor`는 구조 변경이 주목적일 때만 사용하고, 모든 수정에 관성적으로 붙이지 않습니다.
- scope 우선순위는 변경 파일 경로 > 모듈명 > 기능명입니다. 3~8개를 권장하며, 증상 문자열, 라우트 URL, 내부 함수명, UI 컴포넌트 세부명은 계획서가 강하게 지정할 때만 포함합니다.
- category는 기존 카테고리를 우선 재사용하되, 명백히 맞지 않을 때만 새 카테고리를 제안합니다.
- JSON 스키마의 키를 추가하거나 삭제하지 않습니다.
"""


CLAUDE_INSTRUCTIONS = """**Claude 보정:**
- category를 너무 넓게 `common`으로 뭉치지 말고, 기존 카테고리에 맞는 모듈 단위가 있으면 그 값을 우선합니다.
- summary는 구현 상태보다 plan이 해결하려는 문제와 최종 의도를 중심으로 압축합니다.
"""


GEMINI_INSTRUCTIONS = """**Gemini 보정:**
- 화면/UX 문장이 있어도 결함 재발 방지, 데이터 정합성, 401/500류 오류 처리, 회귀 테스트가 핵심이면 trigger는 `bug_recurrence`를 우선합니다.
- `ux_improvement`는 결함 방어가 아니라 사용성 개선 자체가 주목적인 계획서에만 사용합니다.
"""


CODEX_INSTRUCTIONS = """**Codex 보정:**
- scope를 과다 확장하지 않습니다. 라우트명, 이벤트명, 상태 변수명, 내부 helper명은 변경 파일 경로나 모듈명보다 낮은 우선순위입니다.
- scope는 검색 재현성을 위한 색인어입니다. 상세 증상 설명은 summary/intent에 두고 scope에는 안정적인 파일/모듈/기능명만 남깁니다.
"""


POLICIES: tuple[Policy, ...] = (
    Policy(
        id="plan_archive.claude.default",
        version=POLICY_VERSION,
        provider="claude",
        model_match=None,
        instructions=CLAUDE_INSTRUCTIONS,
    ),
    Policy(
        id="plan_archive.gemini.pro_preview",
        version=POLICY_VERSION,
        provider="gemini",
        model_match=_contains("pro", "preview"),
        instructions=GEMINI_INSTRUCTIONS,
    ),
    Policy(
        id="plan_archive.gemini.flash_preview",
        version=POLICY_VERSION,
        provider="gemini",
        model_match=_contains("flash", "preview"),
        instructions=GEMINI_INSTRUCTIONS,
    ),
    Policy(
        id="plan_archive.gemini.default",
        version=POLICY_VERSION,
        provider="gemini",
        model_match=None,
        instructions=GEMINI_INSTRUCTIONS,
    ),
    Policy(
        id="plan_archive.codex.default",
        version=POLICY_VERSION,
        provider="codex",
        model_match=None,
        instructions=CODEX_INSTRUCTIONS,
    ),
)


def resolve_policy(provider: str, model: str | None = None) -> Policy:
    """Resolve the most specific Plan Archive prompt policy."""
    normalized_provider = _normalize(provider) or "claude"
    normalized_model = model or ""
    provider_policies = [policy for policy in POLICIES if policy.provider == normalized_provider]
    for policy in provider_policies:
        if policy.model_match is not None and policy.matches(normalized_provider, normalized_model):
            return policy
    for policy in provider_policies:
        if policy.model_match is None:
            return policy
    return next(policy for policy in POLICIES if policy.id == "plan_archive.claude.default")


def build_plan_archive_prompt(ctx: PromptPolicyContext, file_content: str) -> tuple[str, str, str]:
    """Build the Plan Archive analyze prompt and return policy metadata."""
    categories = ctx.existing_categories or DEFAULT_CATEGORIES
    categories_str = ", ".join(categories)
    policy = resolve_policy(ctx.provider, ctx.model)

    prompt = f"""다음은 개발 프로젝트의 plan 파일입니다. 파일명: {ctx.filename}

아래 내용을 분석하여 JSON 형식으로 결과를 반환해주세요.

**파일 내용:**
{file_content[:3000]}

**출력 JSON 스키마:**
{{
  "category": "모듈 카테고리 (다음 중 하나: {categories_str}, 또는 적절한 새 카테고리)",
  "tags": ["feat", "fix", "refactor", "chore", "docs", "test"] 중 해당하는 것들,
  "summary": "이 plan의 핵심 내용을 2-3문장으로 요약",
  "superseded_by": "이 plan을 대체하는 더 최신 plan 파일명 (없으면 null)",
  "intent": "이 plan이 해결하려는 핵심 문제 (1-2문장)",
  "trigger": "bug_recurrence|new_feature|refactor|ux_improvement|infra|unknown 중 하나",
  "scope": ["영향받는 모듈/파일/기능을 배열로 추출, 예: \"naver-booking\", \"plan_service.py\""]
}}

{COMMON_SCHEMA_RULES}
{policy.instructions}
JSON만 출력하세요. 다른 설명은 불필요합니다."""
    return prompt, policy.id, policy.version
