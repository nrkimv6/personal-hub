"""event_sse — SSE 직렬화 순수 함수

C 도메인: sse_format, build_log_line_payload
상태 없음. 외부 의존성 없음. 입출력 검증만으로 테스트 가능.
"""
import json
import hashlib
import re


_LOG_TAG_PATTERN = re.compile(r"^\s*(?:\[(?P<time>\d{2}:\d{2}:\d{2})\]\s*)?\[(?P<tag>[A-Z_]+)\]\s*(?P<message>.*)", re.DOTALL)
_STRUCTURED_TAGS = {"TOOL", "RESULT", "PHASE", "FAILURE", "HOLD"}
_ARTIFACT_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?[\\/\.]?(?:[\w.-]+[\\/])+[\w .()-]+\.(?:png|jpe?g|webp|gif|jsonl?|log|txt|md))",
    re.IGNORECASE,
)
_ALLOWED_ARTIFACT_PREFIXES = (
    ".tmp/codex/",
    ".tmp/codex-browser-artifacts/",
    "logs/",
)

_FAILURE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("approval_required", ("approval_required", "approval required", "manual approval", "explicit approval")),
    ("retryable", ("rate_limited", "rate limit", "timeout", "timed out", "connection reset", "temporarily unavailable", "429", "redis disconnected")),
    ("environment", ("not recognized", "positional parameter", "permission denied", "no such file", "enoent", "file in use", "build lock", "port already")),
    ("product", ("traceback", "assertionerror", "test failed", "failed test", "[error]", "exception", "os error")),
)


def sse_format(event: str, data: object) -> str:
    """SSE 포맷 직렬화."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _event_id(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"log_{digest}"


def _line_count(text: str) -> int:
    return text.count("\n") + 1 if text else 1


def classify_failure(text: str, tag: str | None = None) -> str | None:
    """Return the minimal failure class used by dev-runner compact rendering."""
    lowered = str(text or "").lower()
    if tag == "FAILURE":
        for classification, tokens in _FAILURE_KEYWORDS:
            if any(token in lowered for token in tokens):
                return classification
        return "product"
    if tag == "HOLD":
        return "approval_required"
    for classification, tokens in _FAILURE_KEYWORDS:
        if any(token in lowered for token in tokens):
            return classification
    return None


def _classify_result_status(message: str, failure_classification: str | None) -> str | None:
    lowered = message.lower()
    if re.search(r"\b(?:exit|code|status)\s*[:=]\s*0\b", lowered) or "success" in lowered:
        return "success"
    if failure_classification or re.search(r"\b(?:exit|code|status)\s*[:=]\s*[1-9]\d*\b", lowered):
        return "failure"
    return None


def _artifact_display_path(normalized: str) -> str:
    lower = normalized.lower()
    for marker in _ALLOWED_ARTIFACT_PREFIXES:
        idx = lower.find(marker)
        if idx >= 0:
            return normalized[idx:]
    return normalized


def normalize_artifact_path(path: str | None) -> dict[str, object] | None:
    """Apply the repo artifact display policy without making filesystem links."""
    if not path:
        return None
    raw_path = str(path).strip().strip("`\"'<>").rstrip(",;)")
    if not raw_path:
        return None
    normalized = raw_path.replace("\\", "/")
    lower = normalized.lower()
    allowed = lower.startswith(_ALLOWED_ARTIFACT_PREFIXES) or any(
        f"/{prefix}" in lower for prefix in _ALLOWED_ARTIFACT_PREFIXES
    )
    reason = "allowed_evidence_root" if allowed else "disallowed_artifact_root"
    return {
        "path": raw_path,
        "display_path": _artifact_display_path(normalized) if allowed else normalized.split("/")[-1],
        "allowed": allowed,
        "reason": reason,
    }


def _extract_artifacts(text: str) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in _ARTIFACT_PATTERN.finditer(text):
        artifact = normalize_artifact_path(match.group("path"))
        if not artifact:
            continue
        key = str(artifact["path"]).lower()
        if key in seen:
            continue
        seen.add(key)
        artifacts.append(artifact)
    return artifacts


def _extract_tool_name_and_args(message: str) -> tuple[str | None, str | None]:
    trimmed = message.strip()
    if not trimmed:
        return None, None
    parts = re.split(r"[:\s]", trimmed, maxsplit=1)
    name = parts[0] if parts else None
    args = parts[1].strip() if len(parts) > 1 else None
    if args and len(args) > 180:
        args = f"{args[:180]}..."
    return name, args or None


def build_structured_log_event(text: str) -> dict[str, object] | None:
    """TOOL/RESULT 로그를 안정적인 schema envelope로 보강한다."""
    match = _LOG_TAG_PATTERN.match(text)
    if not match:
        return None
    tag = match.group("tag")
    if tag not in _STRUCTURED_TAGS:
        return None

    message = match.group("message").strip()
    failure_classification = classify_failure(message, tag)
    result_status = _classify_result_status(message, failure_classification) if tag == "RESULT" else None
    artifacts = _extract_artifacts(text)
    event: dict[str, object] = {
        "schema_version": 1,
        "event_id": _event_id(text),
        "kind": {
            "TOOL": "tool_call",
            "RESULT": "tool_result",
            "PHASE": "phase",
            "FAILURE": "failure",
            "HOLD": "failure",
        }.get(tag, "tagged_log"),
        "source": "dev_runner_log",
        "severity": "error" if failure_classification or result_status == "failure" else "info",
        "tag": tag,
        "message": message,
        "raw": text,
        "line_count": _line_count(text),
        "artifact": artifacts[0] if artifacts else None,
        "artifacts": artifacts,
        "display": {"compact": True},
        "replay": {"eligible": False, "reason": "ui_log_event"},
    }
    timestamp = match.group("time")
    if timestamp:
        event["timestamp"] = timestamp
    if tag == "TOOL":
        name, args_summary = _extract_tool_name_and_args(message)
        if name:
            event["name"] = name
        if args_summary:
            event["args_summary"] = args_summary
    if tag == "RESULT":
        event["result"] = {
            "status": result_status or "unknown",
            "output_schema": {
                "format": "text",
                "line_count": _line_count(message),
                "empty": len(message.strip()) == 0,
            },
        }
    if failure_classification:
        event["failure"] = {"classification": failure_classification}
    return event


def build_log_line_payload(data: str) -> object:
    """로그 payload 직렬화.

    하위호환: 단일 라인은 기존처럼 string.
    확장: 멀티라인 또는 structured 로그는 {text, meta, structured_event} 객체로 보낸다.
    """
    text = str(data or "")
    structured_event = build_structured_log_event(text)
    if "\n" not in text and structured_event is None:
        return text
    line_count = text.count("\n") + 1
    payload: dict[str, object] = {
        "text": text,
        "meta": {
            "multiline": "\n" in text,
            "line_count": line_count,
        },
    }
    if structured_event is not None:
        payload["structured_event"] = structured_event
    return payload
