"""Redis merge lifecycle persistence chokepoint."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from _dr_constants import LOG_CHANNEL_PREFIX, RUNNER_KEY_PREFIX
from _dr_merge_state import TERMINAL_STATUSES, is_transition_allowed, normalize_status
from _dr_runtime_utils import _publish_with_retry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergeState:
    merge_status: str = ""
    merge_reason: str = ""
    merge_message: str = ""
    merge_requested: bool = False


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    from_status: str
    to_status: str
    reason: str = ""


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


class MergePersistence:
    """Single writer for merge_status/reason/message/requested lifecycle keys."""

    def __init__(self, redis_client, runner_id: str):
        self.redis_client = redis_client
        self.runner_id = runner_id
        self.prefix = f"{RUNNER_KEY_PREFIX}:{runner_id}"

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}:{suffix}"

    def read(self) -> MergeState:
        status = _decode(self.redis_client.get(self._key("merge_status"))).strip().lower()
        reason = _decode(self.redis_client.get(self._key("merge_reason"))).strip()
        message = _decode(self.redis_client.get(self._key("merge_message"))).strip()
        requested_raw = self.redis_client.get(self._key("merge_requested"))
        return MergeState(
            merge_status=status,
            merge_reason=reason,
            merge_message=message,
            merge_requested=bool(requested_raw),
        )

    def transition(
        self,
        to_status: str,
        *,
        reason: str | None = None,
        message: str | None = None,
        action: object = None,
    ) -> TransitionResult:
        current = normalize_status(self.redis_client.get(self._key("merge_status")))
        target = normalize_status(to_status)
        if not is_transition_allowed(current, target, action):
            return TransitionResult(
                allowed=False,
                from_status=current,
                to_status=target,
                reason=f"transition rejected: {current} -> {target} by {action or 'inline-merge'}",
            )

        self.redis_client.set(self._key("merge_status"), target)
        if reason is not None:
            if reason:
                self.redis_client.set(self._key("merge_reason"), str(reason))
            else:
                self.redis_client.delete(self._key("merge_reason"))
        if message is not None:
            self.redis_client.set(self._key("merge_message"), str(message))
        return TransitionResult(allowed=True, from_status=current, to_status=target)

    def clear_request(self) -> None:
        self.redis_client.delete(self._key("merge_requested"))

    def request_merge(self) -> None:
        self.redis_client.set(self._key("merge_requested"), "1")

    def persist_result_metadata(self, result: dict) -> None:
        reason = result.get("reason")
        if not reason and isinstance(result.get("post_merge_done"), dict):
            reason = result["post_merge_done"].get("reason")
        quarantine_diff_path = result.get("quarantine_diff_path")
        if not quarantine_diff_path and isinstance(result.get("post_merge_done"), dict):
            quarantine_diff_path = result["post_merge_done"].get("quarantine_diff_path")

        try:
            current = self.read()
            preserve_terminal_metadata = (
                current.merge_status in TERMINAL_STATUSES
                and bool(current.merge_reason or current.merge_message)
                and (
                    normalize_status(reason) != normalize_status(current.merge_reason)
                    or str(result.get("message") or "") != current.merge_message
                )
            )
            if not preserve_terminal_metadata:
                self.redis_client.set(self._key("merge_message"), str(result.get("message") or ""))
                if reason:
                    self.redis_client.set(self._key("merge_reason"), str(reason))
                else:
                    self.redis_client.delete(self._key("merge_reason"))
            if quarantine_diff_path:
                self.redis_client.set(self._key("quarantine_diff_path"), str(quarantine_diff_path))
            else:
                self.redis_client.delete(self._key("quarantine_diff_path"))
            if result.get("snapshot_path"):
                self.redis_client.set(self._key("merge_snapshot_path"), str(result["snapshot_path"]))
            summary = self.build_gate_evidence_summary(result)
            if summary:
                self.redis_client.set(
                    self._key("gate_evidence_summary"),
                    json.dumps(summary, ensure_ascii=False, sort_keys=True),
                )
        except Exception:
            logger.debug("[MergePersistence] result metadata persist failed", exc_info=True)

    def push_result_history(self, *, branch: str | None, plan_file: str | None, result: dict) -> None:
        try:
            final_status = _decode(self.redis_client.get(self._key("merge_status"))).strip() or "unknown"
            self.redis_client.lpush(
                "plan-runner:merge-results",
                json.dumps(
                    {
                        "runner_id": self.runner_id,
                        "branch": branch,
                        "plan_file": plan_file,
                        "timestamp": datetime.now().isoformat(),
                        "status": final_status,
                        "success": bool(result.get("success", False)),
                        "message": result.get("message", f"merge_status={final_status}"),
                        "reason": result.get("reason"),
                        "quarantine_diff_path": result.get("quarantine_diff_path"),
                        "gate_evidence_summary": self.build_gate_evidence_summary(result),
                    },
                    ensure_ascii=False,
                ),
            )
            self.redis_client.expire("plan-runner:merge-results", 86400 * 7)
        except Exception:
            logger.debug("[MergePersistence] merge-results push failed", exc_info=True)

    @staticmethod
    def build_completed_sentinel(result: dict) -> str:
        success = bool(result.get("success", False))
        merge_status = normalize_status(result.get("merge_status"))
        if merge_status == "merged" or (success and not merge_status):
            return "__MERGE_COMPLETED__"
        return "__MERGE_COMPLETED::merge_failed__"

    @staticmethod
    def _extract_service_lock_details(message: str) -> dict:
        """service_lock 메시지에서 changed/running 목록을 구조화해 반환한다.

        메시지 형식:
            MERGE_PRECHECK_FAILED[service_lock]: ...\n- changed: f1, f2\n- running: s1, s2
        """
        details: dict = {}
        if not message:
            return details
        for line in message.splitlines():
            stripped = line.strip()
            if stripped.startswith("- changed:"):
                text = stripped[len("- changed:"):].strip()
                if text:
                    details["service_lock_changed"] = [f.strip() for f in text.split(",") if f.strip()]
            elif stripped.startswith("- running:"):
                text = stripped[len("- running:"):].strip()
                if text:
                    details["service_lock_running"] = [s.strip() for s in text.split(",") if s.strip()]
        return details

    @staticmethod
    def build_gate_evidence_summary(result: dict) -> dict | None:
        if not isinstance(result, dict):
            return None
        post_merge_done = result.get("post_merge_done")
        if not isinstance(post_merge_done, dict):
            post_merge_done = {}
        reason = (
            result.get("reason")
            or post_merge_done.get("reason")
            or post_merge_done.get("status")
            or result.get("merge_status")
        )
        message = result.get("message") or post_merge_done.get("message")
        summary = {
            "tool": "merge-test",
            "status": result.get("merge_status") or result.get("status") or post_merge_done.get("status"),
            "reason": reason,
            "success": bool(result.get("success", False)),
            "quarantine_diff_path": result.get("quarantine_diff_path") or post_merge_done.get("quarantine_diff_path"),
            "merge_snapshot_path": result.get("snapshot_path"),
            "done_post_merge_status": post_merge_done.get("status"),
            "restart_after_merge": post_merge_done.get("status") == "restart_scheduled",
            "message": message,
        }
        if "service_lock" in (reason or "").lower():
            sl_details = MergePersistence._extract_service_lock_details(message or "")
            summary.update(sl_details)
        return {key: value for key, value in summary.items() if value not in (None, "")}

    def publish_completed_sentinel(self, result: dict) -> None:
        channel = f"plan-runner:merge-log:{self.runner_id}"
        payload = self.build_completed_sentinel(result)
        if not _publish_with_retry(self.redis_client, channel, payload):
            logger.debug("[MergePersistence] merge sentinel publish retry failed")
