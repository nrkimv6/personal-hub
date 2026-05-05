"""ClaudeExecutor — Claude CLI subprocess 실행 전담."""

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from app.modules.claude_worker.services.executors.base import (
    LLMExecutorBase,
    normalize_json_payload,
)
from app.modules.claude_worker.services.profile_env import build_cli_env

QUOTA_PAUSE_DEFAULT_MS = 6 * 60 * 60 * 1000  # 6시간
DEFAULT_QUOTA_RESET_TZ = "Asia/Seoul"
QUOTA_RESET_PATTERN = re.compile(
    r"\b(?:resets?|reset)\s+(?:at\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<ampm>a\.?m\.?|p\.?m\.?)"
    r"(?:\s*\((?P<tz>[^)]+)\))?",
    re.IGNORECASE,
)


def _normalize_allowed_tools(allowed_tools) -> list[str]:
    if not allowed_tools:
        return []
    if isinstance(allowed_tools, str):
        return [allowed_tools]
    if isinstance(allowed_tools, Iterable):
        return [str(tool) for tool in allowed_tools if tool]
    return [str(allowed_tools)]


def _build_claude_command(
    *,
    model: str,
    output_format: str | None,
    schema_file: str | None,
    allowed_tools,
    enable_tools: bool,
) -> list[str]:
    command = ["claude"]

    tools = _normalize_allowed_tools(allowed_tools)
    if tools:
        for tool in tools:
            command.extend(["--allowedTools", tool])
    elif enable_tools:
        command.extend(["--allowedTools", "Read"])

    if model:
        command.extend(["--model", model])
    if output_format:
        command.extend(["--output-format", output_format])
    if schema_file:
        command.extend(["--json-schema", f"@{schema_file}"])

    return command


def _extract_session_id(raw: str) -> "str | None":
    """raw_response JSON에서 session_id 추출. 없거나 파싱 실패 시 None 반환."""
    try:
        return json.loads(raw).get("session_id")
    except (json.JSONDecodeError, AttributeError):
        return None


def _timezone_from_label(label: str | None) -> ZoneInfo:
    normalized = (label or DEFAULT_QUOTA_RESET_TZ).strip()
    aliases = {
        "kst": "Asia/Seoul",
        "korea standard time": "Asia/Seoul",
        "asia/seoul": "Asia/Seoul",
    }
    return ZoneInfo(aliases.get(normalized.lower(), normalized))


def _parse_quota_reset_until(text: str, now: datetime | None = None) -> datetime | None:
    """Claude quota reset wall-clock 안내를 다음 KST datetime으로 변환한다."""
    if not text:
        return None

    match = QUOTA_RESET_PATTERN.search(text)
    if not match:
        return None

    tz = _timezone_from_label(match.group("tz"))
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or "0")
    ampm = match.group("ampm").lower().replace(".", "")

    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return None
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate.replace(tzinfo=None)


def _parse_quota_retry_ms(text: str, now: datetime | None = None):
    """stderr/stdout에서 quota 재시도 대기 시간(ms) 파싱.

    1순위: retryDelayMs: 숫자 정규식 파싱
    2순위: reset after Xh Ym Zs 텍스트 파싱
    미감지: None 반환
    """
    if not text:
        return None

    # 1순위: retryDelayMs 파싱
    m = re.search(r"retryDelayMs:\s*([\d.]+)", text)
    if m:
        return int(float(m.group(1)))

    # 2순위: "reset after Xh Ym Zs" 파싱
    m = re.search(r"reset after (\d+)h(\d+)m(\d+)s", text)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (h * 3600 + mn * 60 + s) * 1000

    # 3순위: "resets 5:20pm (Asia/Seoul)" wall-clock 파싱
    reset_until = _parse_quota_reset_until(text, now=now)
    if reset_until:
        reset_match = QUOTA_RESET_PATTERN.search(text)
        tz = _timezone_from_label(reset_match.group("tz") if reset_match else None)
        current = now or datetime.now(tz)
        if current.tzinfo is not None:
            current = current.astimezone(tz).replace(tzinfo=None)
        delta_ms = int((reset_until - current).total_seconds() * 1000)
        return max(1000, delta_ms)

    return None


class ClaudeExecutor(LLMExecutorBase):
    """Claude CLI 실행 Executor.

    DB 접근 없음 — subprocess 호출과 결과 파싱만 담당.
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
    ) -> dict:
        """Claude CLI 실행 (동기).

        Args:
            prompt: LLM 프롬프트
            model: 모델명 (빈 문자열이면 기본 모델 사용)
            timeout: 타임아웃 (초)
            parse_json: True면 JSON 파싱 시도, False면 raw_response만 반환
            enable_tools: True면 Read 도구 활성화 (이미지 분석 등)
            cli_options: CLI 옵션 dict (exec_mode, output_format, json_schema, allowed_tools, cwd 등)

        Returns:
            {"success": True, "result": {...}, "raw_response": "..."}
            또는
            {"success": False, "error": "..."}
        """
        if cli_options is None:
            cli_options = {}

        # session_id 추출을 위해 --output-format json 강제 (R-1: plain --print에는 session_id 없음)
        if "output_format" not in cli_options:
            cli_options = {**cli_options, "output_format": "json"}

        try:
            # 프롬프트를 임시 파일에 저장하고 UTF-8 stdin으로 직접 전달한다.
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            # Claude CLI 실행 env 조립 (profile 기반 config_dir 주입 포함)
            env = build_cli_env("claude")

            schema_file = None

            try:
                output_format = cli_options.get("output_format")
                json_schema = cli_options.get("json_schema")
                allowed_tools = cli_options.get("allowed_tools")

                # cwd 처리 — 허용 경로 검증 후 subprocess cwd로 전달
                cwd_opt = cli_options.get("cwd")
                if cwd_opt:
                    import pathlib

                    ALLOWED_CWD_PREFIX = r"D:\work\project"
                    cwd_path = pathlib.Path(cwd_opt)
                    try:
                        cwd_path.relative_to(ALLOWED_CWD_PREFIX)
                    except ValueError:
                        raise ValueError(
                            f"허용되지 않은 cwd 경로: {cwd_opt} (허용: {ALLOWED_CWD_PREFIX} 하위만)"
                        )
                    if not cwd_path.exists():
                        raise ValueError(f"cwd 경로가 존재하지 않음: {cwd_opt}")
                    cwd_value = str(cwd_path)
                else:
                    cwd_value = None

                if json_schema:
                    schema_str = json.dumps(json_schema, ensure_ascii=False)
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".json", delete=False, encoding="utf-8"
                    ) as sf:
                        sf.write(schema_str)
                        schema_file = sf.name

                command = _build_claude_command(
                    model=model,
                    output_format=output_format,
                    schema_file=schema_file,
                    allowed_tools=allowed_tools,
                    enable_tools=enable_tools,
                )

                with open(prompt_file, "r", encoding="utf-8") as prompt_stream:
                    result = subprocess.run(
                        command,
                        stdin=prompt_stream,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        encoding="utf-8",
                        errors="replace",
                        shell=False,
                        env=env,
                        cwd=cwd_value,
                    )
            finally:
                os.unlink(prompt_file)
                if schema_file:
                    try:
                        os.unlink(schema_file)
                    except Exception:
                        pass

            if result.returncode != 0:
                error_details = result.stderr.strip() if result.stderr else ""
                if not error_details and result.stdout:
                    error_details = result.stdout.strip()[:500]
                if not error_details:
                    error_details = f"returncode={result.returncode}"

                combined_output = (result.stderr or "") + (result.stdout or "")
                quota_keywords = ["overloaded_error", "rate_limit_error"]
                if any(kw in combined_output for kw in quota_keywords):
                    retry_ms = _parse_quota_retry_ms(combined_output)
                    if retry_ms is None:
                        retry_ms = QUOTA_PAUSE_DEFAULT_MS
                    return {
                        "success": False,
                        "error": f"Claude CLI error: {error_details}",
                        "quota_retry_ms": retry_ms,
                    }

                return {"success": False, "error": f"Claude CLI error: {error_details}"}

            raw_response = result.stdout.strip()

            # --output-format json + --json-schema 사용 시 structured_output 파싱
            if output_format == "json" and json_schema:
                try:
                    raw_json = json.loads(raw_response)
                    if "structured_output" in raw_json and raw_json["structured_output"]:
                        return {
                            "success": True,
                            "result": raw_json["structured_output"],
                            "raw_response": raw_response,
                            "claude_session_id": _extract_session_id(raw_response),
                        }
                    result_field = raw_json.get("result", "")
                    if isinstance(result_field, dict):
                        return {
                            "success": True,
                            "result": result_field,
                            "raw_response": raw_response,
                            "claude_session_id": _extract_session_id(raw_response),
                        }
                    if isinstance(result_field, str) and result_field.strip().startswith("{"):
                        try:
                            return {
                                "success": True,
                                "result": json.loads(result_field),
                                "raw_response": raw_response,
                                "claude_session_id": _extract_session_id(raw_response),
                            }
                        except json.JSONDecodeError:
                            pass
                    return {
                        "success": False,
                        "error": f"structured_output/result 필드 없음. raw: {str(raw_json)[:200]}",
                        "raw_response": raw_response,
                    }
                except json.JSONDecodeError as e:
                    return {
                        "success": False,
                        "error": f"structured output JSON 파싱 실패: {e}",
                        "raw_response": raw_response,
                    }

            # JSON 파싱 (선택적)
            if parse_json:
                try:
                    if output_format == "json":
                        try:
                            parsed = normalize_json_payload(json.loads(raw_response))
                        except (json.JSONDecodeError, ValueError, TypeError):
                            parsed = self._parse_json_response(raw_response)
                    else:
                        parsed = self._parse_json_response(raw_response)
                    return {
                        "success": True,
                        "result": parsed,
                        "raw_response": raw_response,
                        "claude_session_id": _extract_session_id(raw_response),
                    }
                except ValueError as e:
                    return {
                        "success": False,
                        "error": f"JSON 파싱 실패: {e}",
                        "raw_response": raw_response,
                    }
            else:
                return {
                    "success": True,
                    "result": None,
                    "raw_response": raw_response,
                    "claude_session_id": _extract_session_id(raw_response),
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Timeout ({timeout}s)"}
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
