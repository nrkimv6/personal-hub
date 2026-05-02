"""Windows process session helpers."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def is_session_0() -> bool:
    """Return True when the current process runs in Windows Session 0."""
    if os.name != "nt":
        return False

    try:
        import ctypes

        session_id = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.ProcessIdToSessionId(
            ctypes.windll.kernel32.GetCurrentProcessId(),
            ctypes.byref(session_id),
        )
        return bool(ok) and session_id.value == 0
    except Exception as exc:
        logger.debug("Session 0 detection failed: %s", exc)
        return False
