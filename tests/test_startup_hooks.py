"""
startup_hooks 모듈 단위 테스트

Phase T1 TC:
- test_install_hooks_registers_excepthook: install_hooks() 후 sys.excepthook이 커스텀 함수인지 확인 (RIGHT)
- test_death_logger_no_crash_on_import_error: record_death import 실패 시 예외 없이 통과 (ERROR)
"""
import sys
import pytest


def test_install_hooks_registers_excepthook():
    """install_hooks() 호출 후 sys.excepthook이 커스텀 _excepthook 함수로 교체된다."""
    original = sys.excepthook
    try:
        from app.startup_hooks import install_hooks, _excepthook
        install_hooks()
        assert sys.excepthook is _excepthook, (
            "install_hooks() 이후 sys.excepthook이 _excepthook 이어야 한다"
        )
    finally:
        sys.excepthook = original


def test_death_logger_no_crash_on_import_error(monkeypatch):
    """record_death import 실패 시 _death_logger가 예외 없이 조용히 통과해야 한다 (ERROR path)."""
    import app.startup_hooks as hooks

    # record_death import를 실패하게 만들기 위해 death_log 모듈을 monkeypatch
    import sys as _sys
    original_modules = dict(_sys.modules)

    # app.core.death_log 를 None 으로 설정 → import 시 ModuleNotFoundError
    _sys.modules["app.core.death_log"] = None  # type: ignore

    try:
        # 예외 없이 통과해야 한다
        hooks._death_logger()
    finally:
        # 복원
        if "app.core.death_log" in original_modules:
            _sys.modules["app.core.death_log"] = original_modules["app.core.death_log"]
        else:
            _sys.modules.pop("app.core.death_log", None)
