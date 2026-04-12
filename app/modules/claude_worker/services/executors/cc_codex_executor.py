"""CCCodexExecutor — CC-Codex CLI subprocess 실행 (B4에서 실구현 예정)."""

import shutil

from app.modules.claude_worker.services.executors.base import LLMExecutorBase


class CCCodexExecutor(LLMExecutorBase):
    """CC-Codex CLI 실행 Executor.

    CodexExecutor와 완전 독립 — 코드 공유 금지.
    dev-runner 엔진의 cc-codex 경로와 독립.
    B4에서 실제 CLI 호출 경로 신설 예정 (execute_codex와 완전 별도 경로).
    """

    def execute(
        self,
        prompt: str,
        *,
        model: str = "",
        timeout: int = 120,
        **kwargs,
    ) -> dict:
        """CC-Codex CLI 실행.

        binary 미발견 시 명시적 오류 반환.
        """
        binary = shutil.which("cc-codex") or shutil.which("cc-codex.cmd")
        if not binary:
            return {
                "success": False,
                "error": "cc-codex CLI not found (B4 미구현). shutil.which('cc-codex') → None",
            }
        # TODO(B4): cc-codex CLI 호출 경로 신설 (execute_codex와 완전 별도 경로)
        return {"success": False, "error": "cc-codex provider 실행 경로 미구현 (B4)"}
