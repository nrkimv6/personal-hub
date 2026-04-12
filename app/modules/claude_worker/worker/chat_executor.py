"""
Chat Executor: LLM Worker chat 요청 처리 (Session 1).

LLM Worker가 Redis LPUSH로 위임한 chat 요청을 BRPOP으로 수신하고,
subprocess로 claude 채팅 세션을 실행하여 stdout을 스트리밍한다.

동작 방식:
    - BRPOP "llm-chat:commands" 블로킹 대기
    - 명령 수신 -> subprocess.Popen(['claude', '--output-format', 'stream-json', ...])
    - stdout 스트리밍 -> Redis Pub/Sub (llm-chat:stream:{request_id}) + 로그 파일
    - 완료 시 -> 마지막 JSON 줄 파싱 -> DB raw_response 저장 + status=completed
    - heartbeat -> Redis (llm-chat:executor:heartbeat)

사용법:
    python -m app.modules.claude_worker.worker.chat_executor
"""
import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import redis

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs" / "admin"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR = PROJECT_ROOT / ".pids"
PID_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("chat_executor")

COMMANDS_KEY = "llm-chat:commands"
LOG_CHANNEL_PREFIX = "llm-chat:stream"
HEARTBEAT_KEY = "llm-chat:executor:heartbeat"
PID_FILE = PID_DIR / "chat_executor_admin.pid"

_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _is_pid_alive(pid: int) -> bool:
    """PID 생존 확인 (Windows)."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


def _extract_last_json(lines: list) -> Optional[str]:
    """stdout 줄 목록에서 마지막 유효 JSON 줄 반환."""
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            json.loads(stripped)
            return stripped
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _stream_output(proc, request_id: int, redis_client, log_file) -> list:
    """stdout 라인별 읽기 -> 파일 기록 + Redis publish. 수집된 줄 목록 반환."""
    channel = f"{LOG_CHANNEL_PREFIX}:{request_id}"
    collected = []
    try:
        for line in proc.stdout:
            stripped = _ANSI_ESCAPE.sub("", line).rstrip("\n")
            collected.append(stripped)
            log_file.write(line)
            log_file.flush()
            try:
                redis_client.publish(channel, stripped)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"stream read error request_id={request_id}: {e}")
    return collected


def _heartbeat_loop(redis_client, stop_event: threading.Event):
    """10초 주기 heartbeat (TTL 30초)."""
    pid = os.getpid()
    while not stop_event.is_set():
        try:
            redis_client.set(HEARTBEAT_KEY, str(pid), ex=30)
        except Exception:
            pass
        stop_event.wait(10)


class ChatExecutor:
    """Chat 요청 처리 프로세스."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis_client = None
        self._stop_event = threading.Event()
        self._busy = False

    def _connect_redis(self) -> bool:
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info(f"Redis connected: {self.redis_url}")
            return True
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            return False

    def _write_pid(self):
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    def _cleanup_pid(self):
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def _check_stale_pid(self):
        """이전 PID 파일 확인 -> stale이면 정리."""
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text(encoding="utf-8").strip())
                if _is_pid_alive(pid):
                    logger.warning(f"Already running (PID={pid}). Exiting.")
                    sys.exit(1)
                else:
                    logger.info(f"Stale PID file removed: {pid}")
                    PID_FILE.unlink(missing_ok=True)
            except Exception:
                PID_FILE.unlink(missing_ok=True)

    def _get_db_service(self):
        """DB 세션 + LLMService 반환."""
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from app.database import SessionLocal
            from app.modules.claude_worker.services.llm_service import LLMService
            db = SessionLocal()
            return db, LLMService(db)
        except Exception as e:
            logger.error(f"DB connection failed: {e}")
            return None, None

    def _run_chat_session(self, request_id: int, prompt: str, provider: str,
                          model: str, cli_options: dict, chat_session_id: str):
        """Claude 채팅 세션 subprocess 실행 + 스트리밍."""
        log_path = LOG_DIR / f"chat_executor_{request_id}_{int(time.time())}.log"
        db, service = self._get_db_service()
        prompt_file_path = None
        try:
            # 프롬프트 임시 파일
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
                f.write(prompt)
                prompt_file_path = f.name

            # Claude CLI 실행 env 조립 (profile 기반 config_dir 주입 포함)
            # base_env 로 기존 필터 결과를 전달해 해당 필터를 보존한다
            from app.modules.claude_worker.services.profile_env import build_cli_env
            filtered_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            env = build_cli_env("claude", base_env=filtered_env)

            allowed_tools = cli_options.get("allowed_tools", "Bash,Read")
            cmd = ["claude", "--output-format", "stream-json", "--allowedTools", allowed_tools, "--print"]
            if model:
                cmd += ["--model", model]

            logger.info(f"Claude session start: request_id={request_id}, tools={allowed_tools}")

            with open(prompt_file_path, "r", encoding="utf-8") as stdin_file:
                proc = subprocess.Popen(
                    cmd,
                    stdin=stdin_file,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    env=env,
                )

            # stream_log_path DB 저장
            if service and db:
                from app.modules.claude_worker.models.llm_request import LLMRequest
                req = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
                if req:
                    req.stream_log_path = str(log_path)
                    db.commit()

            # stdout 스트리밍 (동기, 완료될 때까지 블로킹)
            with open(log_path, "w", encoding="utf-8") as lf:
                collected = _stream_output(proc, request_id, self.redis_client, lf)

            proc.wait()
            exit_code = proc.returncode
            logger.info(f"Claude session done: request_id={request_id}, exit_code={exit_code}")

            # 결과 파싱 + DB 업데이트
            if service:
                last_json = _extract_last_json(collected)
                if exit_code == 0:
                    service.mark_completed(request_id, {}, raw_response=last_json or "\n".join(collected[-20:]))
                else:
                    service.mark_failed(
                        request_id,
                        error_message=f"exit_code={exit_code}",
                        raw_response="\n".join(collected[-20:]),
                    )

            # 완료 신호
            try:
                self.redis_client.publish(f"{LOG_CHANNEL_PREFIX}:{request_id}", "__COMPLETED__")
            except Exception:
                pass

        except Exception as e:
            logger.error(f"chat session error request_id={request_id}: {e}", exc_info=True)
            if service:
                try:
                    service.mark_failed(request_id, error_message=str(e), raw_response="")
                except Exception:
                    pass
            try:
                self.redis_client.publish(f"{LOG_CHANNEL_PREFIX}:{request_id}", "__COMPLETED__")
            except Exception:
                pass
        finally:
            if prompt_file_path:
                try:
                    os.unlink(prompt_file_path)
                except Exception:
                    pass
            if db:
                db.close()
            self._busy = False

    def _handle_command(self, cmd: dict):
        """수신 명령 처리."""
        action = cmd.get("action")
        if action != "execute":
            logger.warning(f"Unknown action: {action}")
            return

        request_id = cmd["request_id"]
        if self._busy:
            # 이미 실행 중 -> 큐에 재삽입 후 대기
            logger.info(f"Executor busy, re-queuing: request_id={request_id}")
            self.redis_client.rpush(COMMANDS_KEY, json.dumps(cmd, ensure_ascii=False))
            time.sleep(1)
            return

        self._busy = True
        t = threading.Thread(
            target=self._run_chat_session,
            args=(
                request_id,
                cmd["prompt"],
                cmd.get("provider", "claude"),
                cmd.get("model", ""),
                cmd.get("cli_options", {}),
                cmd.get("chat_session_id", f"llm-chat:stream:{request_id}"),
            ),
            daemon=True,
        )
        t.start()

    def _main_loop(self):
        """BRPOP 메인 루프."""
        logger.info("Chat Executor listening for commands...")
        while not self._stop_event.is_set():
            try:
                result = self.redis_client.brpop(COMMANDS_KEY, timeout=5)
                if result:
                    _, raw = result
                    cmd = json.loads(raw)
                    self._handle_command(cmd)
            except redis.exceptions.ConnectionError:
                logger.error("Redis disconnected, retrying in 5s...")
                time.sleep(5)
                self._connect_redis()
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                time.sleep(1)

    def start(self):
        """Chat Executor 시작."""
        self._check_stale_pid()
        if not self._connect_redis():
            sys.exit(1)
        self._write_pid()
        logger.info(f"Chat Executor started (PID={os.getpid()})")

        stop_event = threading.Event()
        hb = threading.Thread(
            target=_heartbeat_loop,
            args=(self.redis_client, stop_event),
            daemon=True,
        )
        hb.start()

        try:
            self._main_loop()
        finally:
            stop_event.set()
            self._cleanup_pid()
            logger.info("Chat Executor stopped")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LLM Chat Executor")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    args = parser.parse_args()
    ChatExecutor(redis_url=args.redis_url).start()


if __name__ == "__main__":
    main()
