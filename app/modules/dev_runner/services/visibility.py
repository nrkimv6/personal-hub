"""runner UI 가시성 판별 — 단일 진실 원천 (Single Source of Truth)

runner가 dev-runner UI에 표시되어야 하는지 판별하는 유일한 함수.

설계 원칙:
- 화이트리스트 방식: "표시"가 명시된 트리거만 visible (fail-closed)
- executor_service.py (REST) 와 event_service.py (SSE) 모두 이 함수를 호출
- 이 파일을 수정하면 두 경로가 동시에 반영됨
"""


def is_visible_runner(trigger: str | None, runner_id: str) -> bool:
    """runner가 UI에 표시되어야 하는지 판별한다.

    화이트리스트 + 이중 방어 방식:
    1. runner_id가 "tc-pytest-" 접두사면 → 항상 False (pytest 러너 이중 방어)
    2. trigger가 "user" 또는 "user:all"이면 → True
    3. 그 외 (None, "", "api", "tc:*", "manual" 등) → False

    Args:
        trigger: Redis에서 읽은 trigger 값 (None 허용)
        runner_id: Redis runner ID

    Returns:
        True면 UI 탭에 표시, False면 숨김
    """
    if runner_id.startswith("tc-pytest-"):
        return False
    return bool(trigger and trigger in ("user", "user:all"))
