"""에러 처리 유틸리티."""


def format_error_message(e: Exception) -> str:
    """예외를 에러 메시지 문자열로 변환.

    빈 메시지인 경우 예외 타입명을 반환합니다.
    asyncio.CancelledError 등 빈 메시지 예외에 유용합니다.

    Args:
        e: 발생한 예외

    Returns:
        에러 메시지 문자열 (예: "ValueError: invalid value" 또는 "CancelledError")
    """
    msg = str(e).strip()
    if msg:
        return f"{type(e).__name__}: {msg}"
    return type(e).__name__
