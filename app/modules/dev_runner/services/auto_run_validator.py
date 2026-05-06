"""auto_run scope vs plan 변경 대상 불일치 검증.

scope=tc  : 변경 대상이 tests/, *test*.py, frontend/**/*.test.* 에 한정되어야 함
scope=docs: 변경 대상이 *.md, docs/, 주석/메모 수준이어야 함
scope=safe-fix: 검증 없음 (사용자 책임)

plan 문서에서 변경 대상 파일 경로/심볼을 추출하여 scope와 대조한다.
위반 시 의심 메시지 리스트 반환.
"""

import re
from pathlib import Path
from typing import Sequence

from app.modules.dev_runner.services.plan_frontmatter import AUTO_RUN_SCOPES

# scope별 허용 경로 패턴
_TC_ALLOWED = re.compile(
    r"(?:^|/)(tests?/|test_[^/]+\.py|[^/]+\.test\.[jt]sx?|[^/]+\.spec\.[jt]sx?)",
    re.IGNORECASE,
)
_DOCS_ALLOWED = re.compile(
    r"(?:^|/)(docs?/|[^/]+\.md|CHANGELOG|README|REQUIREMENTS|TODO|DONE|memory/)",
    re.IGNORECASE,
)

# plan 본문에서 파일 경로 힌트 추출 패턴 (backtick + .py/.ts/.svelte/.md 등 확장자)
_FILE_PATH_RE = re.compile(
    r"`([^`\s]+\.[a-zA-Z0-9]{1,10})`",
)


def _extract_file_hints(content: str) -> list[str]:
    """plan 본문의 backtick으로 감싼 파일 경로 힌트 추출."""
    return _FILE_PATH_RE.findall(content)


def validate_scope(plan_path: Path, scope: str) -> list[str]:
    """plan의 변경 대상과 scope 불일치 여부를 검사.

    Returns:
        list[str]: 의심 메시지 목록 (빈 리스트 = 이상 없음)
    """
    if scope not in AUTO_RUN_SCOPES:
        return [f"scope '{scope}'는 허용 값({', '.join(sorted(AUTO_RUN_SCOPES))}) 중 하나가 아닙니다."]

    if scope == "safe-fix":
        return []  # 사용자 책임

    try:
        content = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [f"plan 파일을 읽을 수 없습니다: {plan_path}"]

    hints = _extract_file_hints(content)
    if not hints:
        return []

    suspicions: list[str] = []
    check_fn = _TC_ALLOWED if scope == "tc" else _DOCS_ALLOWED

    for hint in hints:
        if not check_fn.search(hint):
            suspicions.append(
                f"scope={scope} 이지만 '{hint}'는 허용 경로 패턴에 해당하지 않습니다 "
                f"— 운영 영향 가능성 있음"
            )

    return suspicions
