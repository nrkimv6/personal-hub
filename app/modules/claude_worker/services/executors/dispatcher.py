"""ExecutionDispatcher — provider → Executor 라우팅."""

from __future__ import annotations

from app.modules.claude_worker.services.executors.base import LLMExecutorBase


class ExecutionDispatcher:
    """provider key를 Executor 인스턴스에 매핑하고 dispatch를 수행한다.

    모듈 로드 시 4개 executor 자동 등록:
      claude → ClaudeExecutor
      gemini → GeminiExecutor
      codex  → CodexExecutor
      cc-codex → CCCodexExecutor
    """

    _registry: dict[str, LLMExecutorBase] = {}

    @classmethod
    def register(cls, executor_key: str, executor: LLMExecutorBase) -> None:
        """executor_key에 Executor 인스턴스를 등록한다."""
        cls._registry[executor_key] = executor

    @classmethod
    def dispatch(cls, provider: str, prompt: str, **kwargs) -> dict:
        """provider에 해당하는 Executor를 조회하고 execute를 호출한다.

        Args:
            provider: provider key ('claude', 'gemini', 'codex', 'cc-codex')
            prompt: LLM 프롬프트
            **kwargs: Executor.execute에 전달할 키워드 인수

        Returns:
            {"success": True/False, ...}
        """
        from app.modules.claude_worker.services import provider_registry

        meta = provider_registry.get_provider(provider)
        if meta is None or not meta.enabled:
            return {"success": False, "error": f"지원되지 않는 provider: {provider}"}

        executor_key = meta.executor_key
        executor = cls._registry.get(executor_key)
        if executor is None:
            return {
                "success": False,
                "error": f"executor_key '{executor_key}'에 등록된 Executor 없음",
            }

        return executor.execute(prompt, **kwargs)


# ── 모듈 로드 시 자동 등록 ────────────────────────────────────────────────────

def _register_defaults() -> None:
    from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor
    from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor
    from app.modules.claude_worker.services.executors.codex_executor import CodexExecutor
    from app.modules.claude_worker.services.executors.cc_codex_executor import CCCodexExecutor

    ExecutionDispatcher.register("claude", ClaudeExecutor())
    ExecutionDispatcher.register("gemini", GeminiExecutor())
    ExecutionDispatcher.register("codex", CodexExecutor())
    ExecutionDispatcher.register("cc-codex", CCCodexExecutor())


_register_defaults()
