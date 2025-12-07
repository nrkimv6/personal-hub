"""
공통 예외 클래스 정의

모든 도메인 예외의 기반 클래스를 제공합니다.
"""


class AppException(Exception):
    """애플리케이션 기본 예외"""

    def __init__(self, message: str, code: str = "APP_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class NotFoundError(AppException):
    """리소스를 찾을 수 없음"""

    def __init__(self, resource: str, id: any = None):
        message = f"{resource}를 찾을 수 없습니다"
        if id:
            message += f" (ID: {id})"
        super().__init__(message, "NOT_FOUND")
        self.resource = resource
        self.id = id


class ValidationError(AppException):
    """유효성 검증 실패"""

    def __init__(self, message: str, field: str = None):
        super().__init__(message, "VALIDATION_ERROR")
        self.field = field


class DatabaseError(AppException):
    """데이터베이스 오류"""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__(message, "DATABASE_ERROR")
        self.original_error = original_error


class BrowserError(AppException):
    """브라우저 관련 오류"""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__(message, "BROWSER_ERROR")
        self.original_error = original_error


class BookingError(AppException):
    """예약 관련 오류"""

    def __init__(self, message: str, slot: str = None, is_retryable: bool = True):
        super().__init__(message, "BOOKING_ERROR")
        self.slot = slot
        self.is_retryable = is_retryable


class SnipeError(AppException):
    """스나이핑 관련 오류"""

    def __init__(self, message: str, session_id: int = None, is_retryable: bool = True):
        super().__init__(message, "SNIPE_ERROR")
        self.session_id = session_id
        self.is_retryable = is_retryable
