"""
워커 관련 커스텀 예외 클래스.

이 모듈은 워커 시스템에서 사용되는 예외 클래스들을 정의합니다.
예외는 계층 구조로 설계되어 세밀한 에러 핸들링이 가능합니다.

예외 계층:
    WorkerError
    ├── WorkerCriticalError     # 워커 중단 필요
    ├── WorkerRecoverableError  # 재시도 가능
    └── WorkerShutdownError     # 정상 종료

    BrowserError
    ├── TabOperationTimeout     # 탭 작업 타임아웃
    ├── BrowserOperationError   # 브라우저 작업 실패
    └── BrowserRecoveryFailed   # 브라우저 복구 실패
"""


class WorkerError(Exception):
    """워커 기본 예외 클래스.

    모든 워커 관련 예외의 부모 클래스입니다.
    """

    def __init__(self, message: str, worker_name: str = None):
        self.worker_name = worker_name
        super().__init__(message)


class WorkerCriticalError(WorkerError):
    """워커 치명적 에러.

    이 예외가 발생하면 워커를 중단해야 합니다.
    Orchestrator가 이 예외를 감지하면 워커를 재시작하거나
    프로세스를 종료합니다.

    발생 조건:
    - 연속 에러 횟수 초과
    - 필수 리소스 초기화 실패
    - 복구 불가능한 상태
    """

    def __init__(
        self,
        message: str,
        worker_name: str = None,
        consecutive_errors: int = 0
    ):
        self.consecutive_errors = consecutive_errors
        super().__init__(message, worker_name)


class WorkerRecoverableError(WorkerError):
    """복구 가능한 워커 에러.

    이 예외는 재시도로 복구할 수 있습니다.
    워커가 이 예외를 캐치하면 백오프 후 재시도합니다.
    """

    def __init__(
        self,
        message: str,
        worker_name: str = None,
        retry_after: float = 5.0
    ):
        self.retry_after = retry_after
        super().__init__(message, worker_name)


class WorkerShutdownError(WorkerError):
    """워커 정상 종료 신호.

    이 예외는 정상적인 종료 상황에서 발생합니다.
    에러가 아닌 제어 흐름용으로 사용됩니다.
    """
    pass


class BrowserError(Exception):
    """브라우저 기본 예외 클래스.

    모든 브라우저 관련 예외의 부모 클래스입니다.
    """
    pass


class TabOperationTimeout(BrowserError):
    """탭 작업 타임아웃.

    탭에서 수행하는 작업이 지정된 시간 내에 완료되지 않았습니다.

    발생 조건:
    - 페이지 로드 타임아웃
    - 요소 대기 타임아웃
    - 네트워크 요청 타임아웃
    """

    def __init__(self, message: str, timeout: float = 60.0):
        self.timeout = timeout
        super().__init__(f"{message} (timeout: {timeout}s)")


class BrowserOperationError(BrowserError):
    """브라우저 작업 에러.

    브라우저에서 수행하는 작업이 실패했습니다.

    발생 조건:
    - 탭 생성 실패
    - 컨텍스트 생성 실패
    - 페이지 크래시
    """

    def __init__(self, message: str, original_error: Exception = None):
        self.original_error = original_error
        super().__init__(message)


class BrowserRecoveryFailed(BrowserError):
    """브라우저 복구 실패.

    브라우저 복구 시도가 실패했습니다.
    이 예외가 발생하면 전체 프로세스 재시작이 필요합니다.

    발생 조건:
    - 컨텍스트 재생성 실패
    - 브라우저 프로세스 응답 없음
    - 프로필 손상
    """

    def __init__(self, message: str, attempts: int = 0):
        self.attempts = attempts
        super().__init__(f"{message} (attempts: {attempts})")


class TabPoolExhausted(BrowserError):
    """탭 풀 고갈.

    사용 가능한 탭이 없습니다.

    발생 조건:
    - 모든 탭이 사용 중
    - 탭 생성 제한 도달
    """

    def __init__(self, message: str = "No available tabs in pool"):
        super().__init__(message)
