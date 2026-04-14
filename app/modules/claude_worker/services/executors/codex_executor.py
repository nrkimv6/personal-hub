"""CodexExecutor — Codex CLI subprocess 실행 (B4에서 실구현 예정)."""

import shutil

from app.modules.claude_worker.services.executors.base import LLMExecutorBase


class CodexExecutor(LLMExecutorBase):
    """Codex CLI 실행 Executor.

    dev-runner 엔진의 codex 경로와 독립 — dev-runner 모듈 import 금지.
    B4에서 실제 CLI 호출 경로 신설 예정.
    """

    def execute(
        self,
        prompt: str,
        *,
        model: str = "",
        timeout: int = 120,
        **kwargs,
    ) -> dict:
        """Codex CLI 실행.

        binary 미발견 시 명시적 오류 반환.
        """
        binary = shutil.which("codex") or shutil.which("codex.cmd")
        if not binary:
            return {
                "success": False,
                "error": "codex CLI not found (B4 미구현). shutil.which('codex') → None",
            }
        # TODO(B4): codex exec --json --model {model} {prompt} 패턴으로 실구현
        return {"success": False, "error": "codex provider 실행 경로 미구현 (B4)"}
