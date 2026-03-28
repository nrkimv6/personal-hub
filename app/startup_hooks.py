"""
프로세스 수준 훅 — death logging, signal handler, excepthook

main.py 최상단에서 install_hooks()를 호출해 등록한다.
"""
import atexit
import os
import sys


def _death_logger():
    """프로세스 종료 시 구조화된 JSON 로그 기록 (logging 미사용 — flush 보장)"""
    try:
        from app.core.death_log import record_death
        record_death(cause="normal_shutdown", details="atexit 호출 (정상 종료 또는 SIGTERM)")
    except Exception:
        pass


def _signal_death_handler(signum, frame):
    """시그널 수신 시 사망 원인을 기록하고 기본 동작 수행."""
    import signal as _signal
    try:
        sig_name = _signal.Signals(signum).name
    except Exception:
        sig_name = str(signum)
    try:
        from app.core.death_log import record_death
        record_death(
            cause="signal",
            details=f"Signal {sig_name}({signum}) 수신",
        )
    except Exception:
        pass
    # 기본 핸들러 복원 후 재전달 (uvicorn 핸들러 체인 유지)
    _signal.signal(signum, _signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _excepthook(exc_type, exc_value, exc_tb):
    """처리되지 않은 예외 발생 시 traceback을 사망 로그에 기록."""
    import traceback as _tb
    try:
        tb_str = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        from app.core.death_log import record_death
        record_death(
            cause="python_exception",
            details=tb_str[:2000],  # 너무 길면 잘라냄
        )
    except Exception:
        pass
    # 원래 excepthook 호출 (stderr 출력 등)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def install_hooks() -> None:
    """death logging / signal handler / excepthook 을 프로세스에 등록한다."""
    # atexit 등록
    atexit.register(_death_logger)

    # 시그널 핸들러 등록 (SIGTERM은 Windows에서만 실질적으로 사용)
    try:
        import signal as _signal_mod
        for _sig in (getattr(_signal_mod, "SIGTERM", None), getattr(_signal_mod, "SIGBREAK", None)):
            if _sig is not None:
                try:
                    _signal_mod.signal(_sig, _signal_death_handler)
                except (OSError, ValueError):
                    pass
    except Exception:
        pass

    # 처리되지 않은 예외 훅 등록
    sys.excepthook = _excepthook
