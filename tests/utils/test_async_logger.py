"""
tests/utils/test_async_logger.py

AsyncLoggerManager.setup_worker_logger() 변경 검증 테스트

변경 내용:
- console_output 파라미터 추가 (기본값 False)
- 하드코딩된 console_output=True 제거 → watchdog 기동 시 stdout 중복 방지
"""

import logging
import logging.handlers
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.async_logger import AsyncLoggerManager, SafeStreamHandler


def _get_listener_handlers(logger_name: str):
    """QueueListener의 핸들러 목록 반환"""
    return [
        h
        for listener in AsyncLoggerManager._listeners
        if any(
            isinstance(handler, logging.handlers.QueueHandler)
            for handler in logging.getLogger(logger_name).handlers
        )
        for h in listener.handlers
    ]


def _cleanup_logger(logger_name: str):
    """테스트 간 격리를 위해 로거 및 리스너 정리"""
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    # 관련 리스너만 정리
    AsyncLoggerManager._listeners.clear()
    AsyncLoggerManager._queues.pop(logger_name, None)


class TestSetupWorkerLogger:
    """setup_worker_logger() 파라미터 변경 검증"""

    def test_default_no_console_handler(self, tmp_path):
        """[TC-Right] 기본 호출 후 QueueListener 핸들러에 SafeStreamHandler가 없어야 함"""
        logger_name = "test_worker_default"
        _cleanup_logger(logger_name)

        try:
            logger = AsyncLoggerManager.setup_worker_logger(
                log_prefix="test_worker_default",
                log_dir=tmp_path,
            )

            # QueueListener 핸들러 목록에서 SafeStreamHandler 검색
            has_stream = any(
                isinstance(h, SafeStreamHandler)
                for listener in AsyncLoggerManager._listeners
                for h in listener.handlers
            )
            assert not has_stream, "기본값 console_output=False 시 SafeStreamHandler가 없어야 함"
        finally:
            _cleanup_logger(logger_name)

    def test_console_output_true_adds_handler(self, tmp_path):
        """[TC-Right] console_output=True 호출 후 SafeStreamHandler가 포함되어야 함"""
        logger_name = "test_worker_console_true"
        _cleanup_logger(logger_name)

        try:
            logger = AsyncLoggerManager.setup_worker_logger(
                log_prefix="test_worker_console_true",
                log_dir=tmp_path,
                console_output=True,
            )

            has_stream = any(
                isinstance(h, SafeStreamHandler)
                for listener in AsyncLoggerManager._listeners
                for h in listener.handlers
            )
            assert has_stream, "console_output=True 시 SafeStreamHandler가 포함되어야 함"
        finally:
            _cleanup_logger(logger_name)

    def test_file_created_when_console_false(self, tmp_path):
        """[TC-Boundary] console_output=False 시 로그 파일이 생성되고 메시지가 기록되어야 함"""
        logger_name = "test_worker_file"
        _cleanup_logger(logger_name)

        try:
            logger = AsyncLoggerManager.setup_worker_logger(
                log_prefix="test_worker_file",
                log_dir=tmp_path,
                console_output=False,
            )
            logger.info("boundary test message")

            # QueueListener가 비동기 처리할 시간 허용
            time.sleep(0.2)
            AsyncLoggerManager.shutdown()

            log_files = list(tmp_path.glob("test_worker_file_*.log"))
            assert len(log_files) >= 1, "로그 파일이 생성되어야 함"

            content = log_files[0].read_text(encoding="utf-8")
            assert "boundary test message" in content, "로그 파일에 메시지가 기록되어야 함"
        finally:
            _cleanup_logger(logger_name)

    def test_setup_logger_console_true_unchanged(self, tmp_path):
        """[TC-Cross] setup_logger(console_output=True) 직접 호출은 기존 동작 유지 (SafeStreamHandler 포함)"""
        logger_name = "test_base_logger_console"
        _cleanup_logger(logger_name)

        try:
            logger = AsyncLoggerManager.setup_logger(
                logger_name=logger_name,
                log_file=tmp_path / "base.log",
                console_output=True,
            )

            has_stream = any(
                isinstance(h, SafeStreamHandler)
                for listener in AsyncLoggerManager._listeners
                for h in listener.handlers
            )
            assert has_stream, "setup_logger(console_output=True)는 SafeStreamHandler를 포함해야 함"
        finally:
            _cleanup_logger(logger_name)


class TestWorkerLoggerE2E:
    """setup_worker_logger() 통합 흐름 확인"""

    def test_worker_logger_log_written_to_file(self, tmp_path):
        """[e2e] setup_worker_logger() → logger.info() → shutdown() → 파일에 기록 확인"""
        logger_name = "e2e_worker"
        _cleanup_logger(logger_name)

        try:
            logger = AsyncLoggerManager.setup_worker_logger(
                log_prefix="e2e_worker",
                log_dir=tmp_path,
            )
            logger.info("e2e test message")

            # 비동기 큐 처리 대기
            time.sleep(0.3)
            AsyncLoggerManager.shutdown()

            log_files = list(tmp_path.glob("e2e_worker_*.log"))
            assert len(log_files) >= 1, "워커 로그 파일이 생성되어야 함"

            content = log_files[0].read_text(encoding="utf-8")
            assert "e2e test message" in content, "로그 파일에 e2e 메시지가 기록되어야 함"
        finally:
            _cleanup_logger(logger_name)
