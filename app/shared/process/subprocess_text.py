"""Shared text-mode subprocess defaults for Windows service/runtime paths."""

from __future__ import annotations

from typing import Any

DEFAULT_TEXT_SUBPROCESS_ENCODING = "utf-8"
DEFAULT_TEXT_SUBPROCESS_ERRORS = "replace"


def with_text_subprocess_defaults(**kwargs: Any) -> dict[str, Any]:
    """Apply UTF-8 + replacement defaults to text-mode subprocess kwargs.

    Windows services often inherit a locale default such as cp949. When a child
    process emits UTF-8 multibyte output, ``text=True`` without an explicit
    encoding can crash inside ``subprocess._readerthread``. This helper keeps
    text-mode subprocess readers on a stable UTF-8 contract.
    """

    if _uses_text_mode(kwargs):
        kwargs.setdefault("encoding", DEFAULT_TEXT_SUBPROCESS_ENCODING)
        kwargs.setdefault("errors", DEFAULT_TEXT_SUBPROCESS_ERRORS)
    return kwargs


def _uses_text_mode(kwargs: dict[str, Any]) -> bool:
    return bool(
        kwargs.get("text")
        or kwargs.get("universal_newlines")
        or "encoding" in kwargs
        or "errors" in kwargs
    )
