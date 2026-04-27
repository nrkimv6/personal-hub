"""tests 공용 subprocess 헬퍼 — Windows cp949/UTF-8 decode drift 방어."""
from __future__ import annotations

import subprocess
from typing import Sequence


def run_proc(
    cmd: Sequence[str],
    *,
    cwd: str | None = None,
    timeout: float = 60,
    env: dict | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """subprocess.run 래퍼 — encoding='utf-8', errors='replace' 고정.

    Windows에서 Python 프로세스 출력이 cp949로 디코딩되는 drift를 방어한다.
    stdout/stderr는 항상 str로 반환되며, decode 예외는 '?' 대체로 삼킨다.
    """
    return subprocess.run(
        list(cmd),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        check=check,
    )
