"""JSON 파일 read/write 공통 유틸."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any) -> Any:
    """JSON 파일을 읽고 실패 시 default 반환."""
    file_path = Path(path)
    if not file_path.exists():
        return default

    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    """JSON 파일을 원자적으로 저장."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(file_path.parent),
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(serialized)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        tmp_path.replace(file_path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
        raise
