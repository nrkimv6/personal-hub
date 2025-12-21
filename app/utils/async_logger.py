# app/utils/async_logger.py
"""
비동기 로깅 시스템

QueueHandler를 사용하여 로그 쓰기를 별도 스레드에서 처리합니다.
메인 스레드/이벤트 루프의 블로킹을 방지하여 밀리초 단위 응답이 필요한
선착순 예약 시스템에서 성능을 최적화합니다.
"""

import logging
import logging.handlers
import queue
import atexit
import sys
import io
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


class SafeStreamHandler(logging.StreamHandler):
    """
    Windows cp949 인코딩에서 이모지 등 유니코드 문자를 안전하게 처리하는 핸들러.
    인코딩 에러 발생 시 문자를 대체하여 로그 출력 실패를 방지합니다.
    """

    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            # Windows 콘솔에서 인코딩 문제 처리
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                # 이모지를 ASCII로 대체
                safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
                stream.write(safe_msg + self.terminator)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


class AsyncLoggerManager:
    """
    QueueHandler 기반 비동기 로깅 관리자

    사용법:
        # 로거 설정
        logger = AsyncLoggerManager.setup_logger(
            "my_logger",
            log_file=Path("logs/app.log"),
            level=logging.DEBUG
        )

        # 일반적인 logging 사용
        logger.info("메시지")
        logger.error("오류", exc_info=True)

        # 프로세스 종료 시 자동 정리 (atexit 등록됨)
        # 또는 수동 정리
        AsyncLoggerManager.shutdown()
    """

    _listeners: List[logging.handlers.QueueListener] = []
    _queues: Dict[str, queue.Queue] = {}
    _initialized: bool = False

    @classmethod
    def setup_logger(
        cls,
        logger_name: str,
        log_file: Optional[Path] = None,
        level: int = logging.DEBUG,
        log_format: Optional[str] = None,
        console_output: bool = True,
        console_level: int = logging.INFO
    ) -> logging.Logger:
        """
        비동기 로거 설정

        Args:
            logger_name: 로거 이름
            log_file: 로그 파일 경로 (None이면 파일 출력 안함)
            level: 로그 레벨
            log_format: 로그 포맷 문자열 (None이면 기본 포맷)
            console_output: 콘솔 출력 여부
            console_level: 콘솔 출력 레벨

        Returns:
            설정된 Logger 인스턴스
        """
        # atexit 등록 (최초 1회)
        if not cls._initialized:
            atexit.register(cls.shutdown)
            cls._initialized = True

        # 로거 가져오기
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)

        # 기존 핸들러 제거 (중복 방지)
        if logger.handlers:
            logger.handlers.clear()

        # 기본 포맷
        if log_format is None:
            log_format = '%(asctime)s - [%(name)s] %(levelname)s - %(message)s'

        formatter = logging.Formatter(log_format)

        # 로그 큐 생성 (무제한)
        log_queue: queue.Queue = queue.Queue(-1)
        cls._queues[logger_name] = log_queue

        # QueueHandler 생성 (메인 스레드에서 사용)
        queue_handler = logging.handlers.QueueHandler(log_queue)
        logger.addHandler(queue_handler)

        # 실제 핸들러들 (별도 스레드에서 실행)
        handlers: List[logging.Handler] = []

        # 파일 핸들러
        if log_file is not None:
            # 디렉토리 생성
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(
                str(log_file),
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)

        # 콘솔 핸들러 (Windows cp949 인코딩 문제 방지)
        if console_output:
            console_handler = SafeStreamHandler(sys.stdout)
            console_handler.setLevel(console_level)
            console_handler.setFormatter(formatter)
            handlers.append(console_handler)

        # QueueListener 생성 및 시작 (별도 스레드에서 로그 처리)
        if handlers:
            listener = logging.handlers.QueueListener(
                log_queue,
                *handlers,
                respect_handler_level=True
            )
            listener.start()
            cls._listeners.append(listener)

        # 로거에 메타데이터 저장
        logger.log_file = str(log_file) if log_file else None
        logger.is_async = True

        return logger

    @classmethod
    def setup_worker_logger(
        cls,
        log_prefix: str = "worker",
        log_dir: Path = Path("logs"),
        level: int = logging.DEBUG
    ) -> logging.Logger:
        """
        워커용 비동기 로거 설정 (타임스탬프 포함 파일명)

        Args:
            log_prefix: 로그 파일 접두사
            log_dir: 로그 디렉토리
            level: 로그 레벨

        Returns:
            설정된 Logger 인스턴스
        """
        start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"{log_prefix}_{start_time}.log"

        logger = cls.setup_logger(
            logger_name=f"{log_prefix}_logger",
            log_file=log_file,
            level=level,
            log_format=f'%(asctime)s - [{log_prefix.upper()}] %(levelname)s - %(message)s',
            console_output=True
        )

        # 추가 메타데이터
        logger.start_time = start_time
        logger.log_prefix = log_prefix

        return logger

    @classmethod
    def setup_api_logger(
        cls,
        log_prefix: str = "api",
        log_dir: Path = Path("logs"),
        level: int = logging.DEBUG
    ) -> logging.Logger:
        """
        API 서버용 비동기 로거 설정

        Args:
            log_prefix: 로그 파일 접두사
            log_dir: 로그 디렉토리
            level: 로그 레벨

        Returns:
            설정된 Logger 인스턴스
        """
        start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"{log_prefix}_{start_time}.log"

        logger = cls.setup_logger(
            logger_name=f"{log_prefix}_server",
            log_file=log_file,
            level=level,
            log_format=f'%(asctime)s - [{log_prefix.upper()}] %(levelname)s - %(message)s',
            console_output=True
        )

        logger.start_time = start_time
        logger.log_prefix = log_prefix

        return logger

    @classmethod
    def get_queue_sizes(cls) -> Dict[str, int]:
        """모든 로그 큐의 크기 반환"""
        return {name: q.qsize() for name, q in cls._queues.items()}

    @classmethod
    def shutdown(cls):
        """
        모든 리스너 종료 및 남은 로그 flush

        프로세스 종료 시 자동으로 호출됨 (atexit 등록)
        """
        for listener in cls._listeners:
            try:
                listener.stop()
            except Exception:
                pass

        cls._listeners.clear()
        cls._queues.clear()
        cls._initialized = False


def setup_async_logging(
    logger_name: str,
    log_prefix: str = "app",
    log_dir: Path = Path("logs"),
    level: int = logging.DEBUG,
    console_output: bool = True
) -> logging.Logger:
    """
    비동기 로깅 설정 편의 함수

    Args:
        logger_name: 로거 이름
        log_prefix: 로그 파일 접두사
        log_dir: 로그 디렉토리
        level: 로그 레벨
        console_output: 콘솔 출력 여부

    Returns:
        설정된 Logger 인스턴스
    """
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{log_prefix}_{start_time}.log"

    return AsyncLoggerManager.setup_logger(
        logger_name=logger_name,
        log_file=log_file,
        level=level,
        log_format=f'%(asctime)s - [{log_prefix.upper()}] %(levelname)s - %(message)s',
        console_output=console_output
    )
