"""Plan checkbox marker and task identity helpers."""

from __future__ import annotations

import hashlib
import re


CHECKBOX_MARKER_PATTERN = r"(x|X| |/|→[^\]]*)"
ACTIVE_TASK_CLAIM_STATES = {"queued", "active", "running"}


def normalize_checkbox_marker(marker: str | None) -> str:
    if marker is None:
        return " "
    return marker


def is_done_marker(marker: str | None) -> bool:
    return normalize_checkbox_marker(marker).lower() == "x"


def is_running_marker(marker: str | None) -> bool:
    return normalize_checkbox_marker(marker) == "/"


def checkbox_state(marker: str | None, *, has_active_claims: bool = False) -> str:
    normalized = normalize_checkbox_marker(marker)
    if is_done_marker(normalized):
        return "done"
    if is_running_marker(normalized) or has_active_claims:
        return "running"
    if normalized.startswith("→"):
        return "claimed"
    return "pending"


def normalize_task_text(text: str) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return re.sub(r"[*_~`]+", "", compact).lower()


def task_text_hash(text: str) -> str:
    return hashlib.sha1(normalize_task_text(text).encode("utf-8")).hexdigest()[:12]


def task_key(phase_name: str, item_ordinal: str, text: str) -> str:
    phase = re.sub(r"\s+", " ", phase_name or "기타").strip()
    return f"{phase}#{item_ordinal}#{task_text_hash(text)}"
