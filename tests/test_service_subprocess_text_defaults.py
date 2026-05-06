"""Real subprocess reproduction for UTF-8 text-mode defaults."""

from __future__ import annotations

import subprocess
import sys

from app.shared.process.subprocess_text import with_text_subprocess_defaults


def test_utf8_child_stderr_survives_text_defaults():
    """T3: UTF-8 multibyte stderr child output is readable via shared defaults."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.buffer.write('한글'.encode('utf-8'))",
        ],
        **with_text_subprocess_defaults(
            capture_output=True,
            text=True,
            timeout=5,
        ),
    )

    assert result.returncode == 0
    assert result.stderr == "한글"


def test_binary_mode_remains_unmodified():
    """B: binary-mode subprocess kwargs are not forced into text decoding."""
    kwargs = with_text_subprocess_defaults(capture_output=True, timeout=5)

    assert "encoding" not in kwargs
    assert "errors" not in kwargs
