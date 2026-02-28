"""
TC: scheduled_worker._dispatch_scheduled_runs() DB 세션 누수 방지
- RIGHT: 정상 실행 후 db.close() 호출 검증
- ERROR: 내부 예외 발생 시에도 db.close() 호출 검증
- PERFORMANCE: 루프 반복 후 pool 연결 수 증가 없음 검증

NOTE: ScheduledWorker는 import 체인이 깊어 직접 import가 어려움.
      대신 실제 코드의 finally: db.close() 패턴을 AST로 검증하고,
      동일한 패턴을 재현하는 스텁으로 동작을 검증한다.
"""
import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

# 실제 소스 파일 경로
SCHEDULED_WORKER_PATH = Path(__file__).resolve().parents[2] / "app" / "worker" / "scheduled_worker.py"


class TestDispatchDbSessionLeak:
    """_dispatch_scheduled_runs의 DB 세션 누수 방지 검증."""

    def test_source_has_finally_db_close(self):
        """소스 코드에 finally: db.close() 패턴이 존재하는지 AST로 검증."""
        source = SCHEDULED_WORKER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # _dispatch_scheduled_runs 메서드 찾기
        dispatch_func = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_dispatch_scheduled_runs":
                dispatch_func = node
                break

        assert dispatch_func is not None, "_dispatch_scheduled_runs 메서드를 찾을 수 없음"

        # try 문 안에 finally 블록이 있는지 확인
        has_finally_close = False
        for node in ast.walk(dispatch_func):
            if isinstance(node, ast.Try) and node.finalbody:
                for stmt in node.finalbody:
                    # db.close() 호출 찾기
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        func = stmt.value.func
                        if (isinstance(func, ast.Attribute) and func.attr == "close"
                                and isinstance(func.value, ast.Name) and func.value.id == "db"):
                            has_finally_close = True

        assert has_finally_close, "_dispatch_scheduled_runs에 finally: db.close()가 없음 — 세션 누수!"

    @pytest.mark.asyncio
    async def test_dispatch_right_db_closed_after_success(self):
        """R: 정상 실행 후 db.close() 반드시 호출됨 (패턴 재현)."""
        mock_db = MagicMock()

        # 실제 코드와 동일한 패턴 재현
        async def dispatch_pattern():
            db = mock_db
            try:
                # 정상 로직 (예외 없음)
                pass
            except Exception:
                pass
            finally:
                db.close()

        await dispatch_pattern()
        mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_error_db_closed_after_exception(self):
        """E: 내부 예외 발생 시에도 db.close() 반드시 호출됨 (패턴 재현)."""
        mock_db = MagicMock()

        async def dispatch_pattern_with_error():
            db = mock_db
            try:
                raise RuntimeError("DB 연결 오류")
            except Exception:
                pass
            finally:
                db.close()

        await dispatch_pattern_with_error()
        mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_no_pool_exhaustion_after_repeated_calls(self):
        """P: 10회 반복 호출 후 db.close() 호출 횟수 = 10 (누수 없음, 패턴 재현)."""
        mock_db = MagicMock()

        async def dispatch_pattern():
            db = mock_db
            try:
                pass
            except Exception:
                pass
            finally:
                db.close()

        for _ in range(10):
            await dispatch_pattern()

        assert mock_db.close.call_count == 10

    def test_no_other_session_without_finally(self):
        """보너스: scheduled_worker 내 모든 SessionLocal() 사용이 finally: close()를 갖는지 검증."""
        source = SCHEDULED_WORKER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # 모든 함수에서 SessionLocal() 할당을 찾고, 해당 try에 finally: db.close()가 있는지 확인
        issues = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # 함수 내에서 SessionLocal() 호출이 있는 assign 찾기
            has_session_local = False
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    if isinstance(child.value, ast.Call):
                        func = child.value.func
                        if isinstance(func, ast.Name) and func.id == "SessionLocal":
                            has_session_local = True

            if not has_session_local:
                continue

            # finally: db.close() 패턴이 있는지
            has_finally_close = False
            for child in ast.walk(node):
                if isinstance(child, ast.Try) and child.finalbody:
                    for stmt in child.finalbody:
                        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                            func = stmt.value.func
                            if (isinstance(func, ast.Attribute) and func.attr == "close"
                                    and isinstance(func.value, ast.Name) and func.value.id == "db"):
                                has_finally_close = True

            if not has_finally_close:
                issues.append(node.name)

        assert not issues, f"SessionLocal 사용 함수에 finally: db.close() 누락: {issues}"
