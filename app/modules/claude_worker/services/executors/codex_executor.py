"""CodexExecutor — Codex CLI subprocess 실행 전담."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.modules.claude_worker.services.executors.base import LLMExecutorBase
from app.modules.claude_worker.services.profile_env import build_cli_env

CODEX_SAFE_DEFAULT_MODEL = "gpt-5.5"
CODEX_DEFAULT_SANDBOX = "read-only"
MODEL_INCOMPATIBLE_SNIPPET = "requires a newer version of Codex"
ALLOWED_CLI_OPTION_KEYS = {"cwd", "parse_json", "sandbox"}


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return Path.cwd()


def _validate_cli_options(cli_options: dict | None, project_root: Path) -> tuple[dict, str | None]:
    options = dict(cli_options or {})
    unknown = set(options) - ALLOWED_CLI_OPTION_KEYS
    if unknown:
        return {}, f"CODEX_UNSUPPORTED_CLI_OPTION: {sorted(unknown)}"

    sandbox = str(options.get("sandbox") or CODEX_DEFAULT_SANDBOX)
    if sandbox != CODEX_DEFAULT_SANDBOX:
        return {}, f"CODEX_UNSAFE_CLI_OPTION: sandbox={sandbox!r}"

    cwd = options.get("cwd")
    cwd_path = project_root
    if cwd:
        candidate = Path(str(cwd)).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError:
            return {}, f"CODEX_UNSAFE_CLI_OPTION: cwd outside project root: {cwd}"
        if not candidate.exists():
            return {}, f"CODEX_INVALID_CWD: {cwd}"
        cwd_path = candidate

    return {"sandbox": sandbox, "cwd": str(cwd_path)}, None


def _build_codex_command(
    *,
    binary: str,
    model: str,
    sandbox: str,
    cd_path: str,
    output_last_message: str,
) -> list[str]:
    return [
        binary,
        "exec",
        "--model",
        model,
        "--sandbox",
        sandbox,
        "--color",
        "never",
        "--cd",
        cd_path,
        "--output-last-message",
        output_last_message,
        "-",
    ]


class CodexExecutor(LLMExecutorBase):
    """Codex CLI 실행 Executor.

    dev-runner 엔진의 codex 경로와 독립 — dev-runner 모듈 import 금지.
    """

    def execute(
        self,
        prompt: str,
        *,
        model: str = "",
        timeout: int = 120,
        parse_json: bool = True,
        enable_tools: bool = False,
        cli_options: dict = None,
        **kwargs,
    ) -> dict:
        """Codex CLI 실행."""
        started = time.monotonic()
        binary = shutil.which("codex") or shutil.which("codex.cmd")
        if not binary:
            return {
                "success": False,
                "error": "Codex CLI not found. Install or expose `codex` on PATH.",
            }

        project_root = _project_root()
        validated_options, option_error = _validate_cli_options(cli_options, project_root)
        if option_error:
            return {
                "success": False,
                "error": option_error,
                "warnings": ["CODEX_CLI_OPTION_REJECTED"],
                "model": model or CODEX_SAFE_DEFAULT_MODEL,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }

        effective_model = (model or "").strip() or CODEX_SAFE_DEFAULT_MODEL
        output_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as output_file:
                output_path = output_file.name

            command = _build_codex_command(
                binary=binary,
                model=effective_model,
                sandbox=validated_options["sandbox"],
                cd_path=validated_options["cwd"],
                output_last_message=output_path,
            )

            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                shell=False,
                env=build_cli_env("codex"),
            )

            last_message = ""
            if output_path and os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8", errors="replace") as f:
                    last_message = f.read().strip()
            raw_response = last_message or (completed.stdout or "").strip()
            combined_output = "\n".join(
                part for part in (completed.stderr, completed.stdout, raw_response) if part
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)

            if completed.returncode != 0:
                if MODEL_INCOMPATIBLE_SNIPPET.lower() in combined_output.lower():
                    return {
                        "success": False,
                        "error": "CODEX_CLI_MODEL_INCOMPATIBLE",
                        "warnings": ["CODEX_CLI_MODEL_INCOMPATIBLE"],
                        "raw_response": raw_response,
                        "model": effective_model,
                        "elapsed_ms": elapsed_ms,
                    }
                detail = (completed.stderr or completed.stdout or f"returncode={completed.returncode}").strip()
                return {
                    "success": False,
                    "error": f"Codex CLI error: {detail}",
                    "raw_response": raw_response,
                    "model": effective_model,
                    "elapsed_ms": elapsed_ms,
                    "warnings": [],
                }

            if parse_json:
                try:
                    parsed = self._parse_json_response(raw_response)
                except ValueError as exc:
                    return {
                        "success": False,
                        "error": f"JSON 파싱 실패: {exc}",
                        "raw_response": raw_response,
                        "model": effective_model,
                        "elapsed_ms": elapsed_ms,
                        "warnings": [],
                    }
            else:
                parsed = None

            return {
                "success": True,
                "result": parsed,
                "parsed": parsed,
                "raw_response": raw_response,
                "model": effective_model,
                "elapsed_ms": elapsed_ms,
                "warnings": [],
            }
        except subprocess.TimeoutExpired as exc:
            raw_response = ""
            if isinstance(exc.stdout, str):
                raw_response = exc.stdout.strip()
            return {
                "success": False,
                "error": "CODEX_TIMEOUT",
                "raw_response": raw_response,
                "model": effective_model,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "warnings": ["CODEX_TIMEOUT"],
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Codex CLI not found. Install or expose `codex` on PATH.",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "model": effective_model,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "warnings": [],
            }
        finally:
            if output_path:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
