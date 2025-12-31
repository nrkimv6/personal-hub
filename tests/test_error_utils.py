"""
에러 유틸리티 테스트

RIGHT-BICEP 원칙 적용:
- Right: 올바른 형식으로 에러 메시지가 반환되는가?
- Boundary: 빈 메시지, None 등 경계 조건 처리
- Error: 다양한 예외 타입에서 동작

CORRECT 조건 적용:
- Conformance: 예상된 형식(타입: 메시지)으로 반환되는가?
- Existence: 빈 메시지일 때도 타입명이 반환되는가?
"""

import asyncio
import pytest
import sys
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.error_utils import format_error_message


class TestFormatErrorMessage:
    """format_error_message() 함수 테스트"""

    def test_format_with_message(self):
        """[Right] 메시지가 있는 예외는 '타입: 메시지' 형식으로 반환"""
        error = ValueError("invalid value")
        result = format_error_message(error)
        assert result == "ValueError: invalid value"

    def test_format_cancelled_error_empty(self):
        """[Boundary] CancelledError(빈 메시지)는 타입명만 반환"""
        error = asyncio.CancelledError()
        result = format_error_message(error)
        assert result == "CancelledError"

    def test_format_cancelled_error_with_message(self):
        """[Right] CancelledError(메시지 있음)는 '타입: 메시지' 형식으로 반환"""
        error = asyncio.CancelledError("task was cancelled")
        result = format_error_message(error)
        assert result == "CancelledError: task was cancelled"

    def test_format_exception_with_empty_message(self):
        """[Boundary] 빈 메시지 Exception은 타입명만 반환"""
        error = RuntimeError("")
        result = format_error_message(error)
        assert result == "RuntimeError"

    def test_format_exception_with_whitespace_only(self):
        """[Boundary] 공백만 있는 메시지는 타입명만 반환"""
        error = RuntimeError("   ")
        result = format_error_message(error)
        assert result == "RuntimeError"

    def test_format_timeout_error(self):
        """[Error] TimeoutError 처리"""
        error = TimeoutError("connection timed out")
        result = format_error_message(error)
        assert result == "TimeoutError: connection timed out"

    def test_format_keyboard_interrupt(self):
        """[Error] KeyboardInterrupt 처리"""
        error = KeyboardInterrupt()
        result = format_error_message(error)
        assert result == "KeyboardInterrupt"

    def test_format_custom_exception(self):
        """[Right] 커스텀 예외 처리"""
        class CustomError(Exception):
            pass
        error = CustomError("custom error message")
        result = format_error_message(error)
        assert result == "CustomError: custom error message"

    def test_format_os_error(self):
        """[Error] OSError 처리"""
        error = OSError(2, "No such file or directory")
        result = format_error_message(error)
        # Python에서 OSError(2, ...)는 FileNotFoundError로 변환됨
        assert "Error" in result
        assert "No such file" in result

    def test_format_connection_error(self):
        """[Error] ConnectionError 처리"""
        error = ConnectionError("Connection refused")
        result = format_error_message(error)
        assert result == "ConnectionError: Connection refused"
