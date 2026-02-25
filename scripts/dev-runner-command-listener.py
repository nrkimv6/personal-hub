"""
Redis Dev Runner Command Listener

Session 1 (?ъ슜???몄뀡)?먯꽌 ?ㅽ뻾?섎뒗 dev-runner 紐낅졊 由ъ뒪?덉엯?덈떎.
API ?쒕쾭(Session 0)?먯꽌 Redis瑜??듯빐 ?꾨떖??紐낅졊???섏떊?섍퀬 ?ㅽ뻾?⑸땲??

?숈옉 諛⑹떇:
    - BRPOP?쇰줈 plan-runner:commands ?ㅻ? 釉붾줈???湲?(CPU 0%)
    - 紐낅졊 ?섏떊 ??plan-runner CLI ?ㅽ뻾
    - ?ㅽ뻾 寃곌낵/PID瑜?plan-runner:command_results??諛섑솚
    - stop 紐낅졊 ???꾨줈?몄뒪 terminate

?ъ슜踰?
    python scripts/dev-runner-command-listener.py

?꾪궎?띿쿂:
    API (Session 0) ??Redis LPUSH ??[??由ъ뒪??(Session 1)] ??plan-runner CLI
"""
import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

import redis

# ?ㅼ젙
REDIS_HOST = "localhost"
REDIS_PORT = 6379
COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
STATE_KEY = "plan-runner:state"
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
HEARTBEAT_INTERVAL = 10  # heartbeat 媛깆떊 二쇨린 (珥?
HEARTBEAT_TTL = 30  # heartbeat 留뚮즺 ?쒓컙 (珥? 3??誘멸갚????留뚮즺)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
WTOOLS_BASE_DIR = Path("D:/work/project/service/wtools")
PLAN_RUNNER_MODULE_PATH = WTOOLS_BASE_DIR / "common/tools/plan-runner"
PLAN_RUNNER_PYTHON = PLAN_RUNNER_MODULE_PATH / ".venv/Scripts/python.exe"
LOG_DIR = WTOOLS_BASE_DIR / "common/logs"

# 濡쒓퉭 ?ㅼ젙
log_dir = PROJECT_ROOT / "logs" / "dev"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "dev_runner_command_listener.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

LOG_CHANNEL = "plan-runner:logs"

# ?꾩뿭 ?꾨줈?몄뒪 愿由?
_current_process: Optional[subprocess.Popen] = None
_current_log_file: Optional[Path] = None
_stream_thread: Optional[threading.Thread] = None


def _is_pid_alive(pid: int) -> bool:
    """PID媛 ?ㅼ젣濡??댁븘?덈뒗吏 OS ?덈꺼 ?뺤씤 (Windows)"""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        STILL_ACTIVE = 259
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == STILL_ACTIVE
    except Exception:
        return False


def _cleanup_process_state(redis_client: redis.Redis):
    """?꾩뿭 ?꾨줈?몄뒪 蹂??+ Redis ?곹깭 ?뺣━"""
    global _current_process, _current_log_file, _stream_thread

    _current_process = None
    _current_log_file = None

    if _stream_thread and _stream_thread.is_alive():
        _stream_thread.join(timeout=3)
    _stream_thread = None

    try:
        redis_client.set(STATE_KEY + ":status", "stopped")
        redis_client.delete(
            STATE_KEY + ":pid",
            STATE_KEY + ":plan_file",
            STATE_KEY + ":start_time",
            STATE_KEY + ":log_file_path",
            STATE_KEY + ":stream_log_path",
        )
    except Exception:
        pass


def _stream_output(process: subprocess.Popen, log_handle, redis_client: redis.Redis):
    """?꾨줈?몄뒪 stdout???쇱씤蹂꾨줈 ?쎌뼱 ?뚯씪 湲곕줉 + Redis publish ?숈떆 ?섑뻾"""
    try:
        for line in process.stdout:
            stripped = line.rstrip('\n')
            # ?뚯씪??湲곕줉
            log_handle.write(line)
            log_handle.flush()
            # Redis Pub/Sub?쇰줈 publish
            try:
                redis_client.publish(LOG_CHANNEL, stripped)
            except redis.ConnectionError:
                pass  # Redis ?딄꺼???뚯씪 湲곕줉? 怨꾩냽
    except Exception as e:
        logger.error(f"Output streaming error: {e}")
    finally:
        try:
            log_handle.flush()
            log_handle.close()
        except Exception:
            pass

        # ?꾨줈?몄뒪 醫낅즺 ?湲?+ ?꾩뿭 ?곹깭 ?뺣━
        try:
            process.wait(timeout=10)
        except Exception:
            pass
        logger.info(f"Output streaming thread finished (exit code: {process.returncode})")
        _cleanup_process_state(redis_client)


def start_plan_runner(command: Dict, redis_client: redis.Redis) -> Dict:
    """plan-runner CLI ?ㅽ뻾 ?쒖옉

    Args:
        command: {action: "run", plan_file: str, max_cycles: int, ...}
        redis_client: Redis ?대씪?댁뼵??

    Returns:
        dict: {success: bool, message: str, pid: int|None, log_file: str|None}
    """
    global _current_process, _current_log_file

    # ?대? ?ㅽ뻾 以묒씠硫??먮윭 (stale ?꾨줈?몄뒪 ?먮룞 ?뺣━ ?ы븿)
    if _current_process and _current_process.poll() is None:
        if not _is_pid_alive(_current_process.pid):
            # OS ?덈꺼?먯꽌 二쎌? ?꾨줈?몄뒪 ???먮룞 ?뺣━
            logger.warning(f"Stale process detected (PID: {_current_process.pid}), cleaning up")
            _cleanup_process_state(redis_client)
        else:
            return {
                "success": False,
                "message": f"Already running (PID: {_current_process.pid})"
            }
    elif _current_process and _current_process.poll() is not None:
        # 醫낅즺?섏뿀吏留??뺣━ ????寃쎌슦
        logger.info(f"Previous process ended (exit code: {_current_process.returncode}), cleaning up")
        _cleanup_process_state(redis_client)

    # 紐낅졊??援ъ꽦
    plan_file = command.get("plan_file")
    engine = command.get("engine")
    is_parallel = command.get("parallel", False)
    if not plan_file and not is_parallel:
        return {"success": False, "message": "plan_file required (use parallel mode for batch execution)"}

    cmd = [
        str(PLAN_RUNNER_PYTHON),
        "-m",
        "plan_runner",
        "run",
    ]

    if plan_file:
        cmd.extend(["占쏙옙plan-file", plan_file])
    if engine:
        cmd.extend(["占쏙옙engine", engine])

    # ?듭뀡 異붽?
    if command.get("max_cycles"):
        cmd.extend(["--max-cycles", str(command["max_cycles"])])

    if command.get("max_tokens"):
        cmd.extend(["--max-tokens", str(command["max_tokens"])])

    if command.get("until"):
        cmd.extend(["--until", command["until"]])

    if command.get("dry_run"):
        cmd.append("--dry-run")

    if command.get("skip_plan"):
        cmd.append("--skip-plan")

    if command.get("parallel"):
        cmd.append("--parallel")

    if command.get("projects"):
        cmd.extend(["--projects", command["projects"]])

    if command.get("extra_plan_dirs"):
        cmd.extend(["--extra-plan-dirs", command["extra_plan_dirs"]])

    if command.get("ignored_plans"):
        cmd.extend(["--ignored-plans", command["ignored_plans"]])

    # 濡쒓렇 ?뚯씪 ?앹꽦
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"plan-runner-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    try:
        # subprocess ?ㅽ뻾 ??stdout??PIPE濡?諛쏆븘 ?ㅻ젅?쒖뿉???뚯씪+Redis ?숈떆 湲곕줉
        log_handle = open(log_file, "w", encoding="utf-8")

        # UTF-8 媛뺤젣
        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env.pop("CLAUDECODE", None)  # 以묒꺽 ?몄뀡 媛먯? 諛⑹?

        process = subprocess.Popen(
            cmd,
            cwd=str(PLAN_RUNNER_MODULE_PATH),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        _current_process = process
        _current_log_file = log_file

        # 蹂꾨룄 ?ㅻ젅?쒖뿉??stdout ???뚯씪 + Redis publish
        global _stream_thread
        _stream_thread = threading.Thread(
            target=_stream_output,
            args=(process, log_handle, redis_client),
            daemon=True,
        )
        _stream_thread.start()

        # Redis???곹깭 ???
        redis_client.set(STATE_KEY + ":log_file_path", str(log_file))
        redis_client.set(STATE_KEY + ":stream_log_path", str(log_file))
        redis_client.set(STATE_KEY + ":pid", process.pid)
        redis_client.set(STATE_KEY + ":plan_file", plan_file or "ALL")
        redis_client.set(STATE_KEY + ":start_time", datetime.now().isoformat())
        redis_client.set(STATE_KEY + ":status", "running")
        redis_client.set(STATE_KEY + ":engine", command.get("engine", "claude"))

        logger.info(f"plan-runner started (PID: {process.pid}, log: {log_file})")

        return {
            "success": True,
            "message": "plan-runner started",
            "pid": process.pid,
            "log_file": str(log_file),
        }

    except Exception as e:
        logger.error(f"Failed to start plan-runner: {e}")
        return {
            "success": False,
            "message": f"Failed to start: {str(e)}"
        }


def stop_plan_runner(redis_client: redis.Redis) -> Dict:
    """plan-runner ?꾨줈?몄뒪 醫낅즺

    Returns:
        dict: {success: bool, message: str}
    """
    global _current_process, _current_log_file

    if not _current_process or _current_process.poll() is not None:
        return {"success": False, "message": "Not running"}

    try:
        logger.info(f"Stopping plan-runner (PID: {_current_process.pid})...")

        # Windows: terminate() ?몄텧
        _current_process.terminate()

        # 5珥??湲?
        try:
            _current_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 媛뺤젣 醫낅즺
            _current_process.kill()
            _current_process.wait()

        logger.info("plan-runner stopped")

        # ?ㅽ듃由щ컢 ?ㅻ젅???뺣━
        global _stream_thread
        if _stream_thread and _stream_thread.is_alive():
            _stream_thread.join(timeout=5)
        _stream_thread = None

        # Redis ?곹깭 ?낅뜲?댄듃
        redis_client.set(STATE_KEY + ":status", "stopped")
        redis_client.delete(STATE_KEY + ":pid")
        redis_client.delete(STATE_KEY + ":log_file_path")
        redis_client.delete(STATE_KEY + ":stream_log_path")

        _current_process = None
        _current_log_file = None

        return {
            "success": True,
            "message": "Stopped successfully"
        }

    except Exception as e:
        logger.error(f"Failed to stop plan-runner: {e}")
        return {
            "success": False,
            "message": f"Failed to stop: {str(e)}"
        }


def get_status(redis_client: redis.Redis) -> Dict:
    """?꾩옱 ?ㅽ뻾 ?곹깭 議고쉶

    Returns:
        dict: {success: bool, running: bool, pid: int|None, log_file: str|None}
    """
    global _current_process, _current_log_file

    if _current_process and _current_process.poll() is None:
        return {
            "success": True,
            "running": True,
            "pid": _current_process.pid,
            "log_file": str(_current_log_file) if _current_log_file else None,
        }
    else:
        # 醫낅즺??寃쎌슦 Redis ?곹깭 ?뺣━
        if _current_process:
            redis_client.set(STATE_KEY + ":status", "stopped")
            redis_client.delete(STATE_KEY + ":pid")
            redis_client.delete(STATE_KEY + ":log_file_path")
            redis_client.delete(STATE_KEY + ":stream_log_path")
            _current_process = None
            _current_log_file = None

        return {
            "success": True,
            "running": False,
            "pid": None,
            "log_file": None,
        }


def force_stop_plan_runner(redis_client: redis.Redis) -> Dict:
    """媛뺤젣 醫낅즺 - kill ???꾩뿭 ?곹깭 珥덇린??(由ъ뀑??

    Returns:
        dict: {success: bool, message: str}
    """
    global _current_process, _current_log_file, _stream_thread

    pid = _current_process.pid if _current_process else None

    if _current_process:
        try:
            _current_process.kill()
            _current_process.wait(timeout=5)
        except Exception:
            pass

    _cleanup_process_state(redis_client)

    msg = f"Force stopped (PID: {pid})" if pid else "Force cleaned (no process)"
    logger.info(msg)
    return {"success": True, "message": msg}


def execute_command(command: Dict, redis_client: redis.Redis) -> Dict:
    """紐낅졊 ?ㅽ뻾

    Args:
        command: {action: str, ...}
        redis_client: Redis ?대씪?댁뼵??

    Returns:
        dict: {success: bool, message: str, ...}
    """
    action = command.get("action")

    if action == "run":
        return start_plan_runner(command, redis_client)
    elif action == "stop":
        return stop_plan_runner(redis_client)
    elif action == "force-stop":
        return force_stop_plan_runner(redis_client)
    elif action == "status":
        return get_status(redis_client)
    else:
        return {"success": False, "message": f"Unknown action: {action}"}


def main():
    """硫붿씤 猷⑦봽: Redis BRPOP?쇰줈 紐낅졊 ?湲?諛??ㅽ뻾."""
    logger.info("=" * 50)
    logger.info("Dev Runner Command Listener ?쒖옉")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"紐낅졊 ?? {COMMANDS_KEY}")
    logger.info(f"寃곌낵 ?? {RESULTS_KEY}")
    logger.info(f"?곹깭 ?? {STATE_KEY}")
    logger.info(f"plan-runner 紐⑤뱢: {PLAN_RUNNER_MODULE_PATH}")
    logger.info("=" * 50)

    reconnect_delay = 1

    while True:
        try:
            # Redis ?곌껐
            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            r.ping()
            logger.info("Redis ?곌껐 ?깃났")
            reconnect_delay = 1  # ?곌껐 ?깃났 ??由ъ뀑

            # Redis ?ъ뿰寃????꾩옱 ?꾨줈?몄뒪 ?곹깭 蹂듭썝
            # (Redis ?ъ떆???깆쑝濡??ㅺ? ?좎븘媛?寃쎌슦 status: running 蹂듭썝)
            if _current_process and _current_process.poll() is None and _is_pid_alive(_current_process.pid):
                r.set(STATE_KEY + ":status", "running")
                r.set(STATE_KEY + ":pid", _current_process.pid)
                logger.info(f"Redis ?ъ뿰寃? ?꾨줈?몄뒪 ?곹깭 蹂듭썝 (PID: {_current_process.pid})")

            # 珥덇린 heartbeat ?ㅼ젙
            last_heartbeat = 0

            # BRPOP 猷⑦봽 (釉붾줈???湲?
            while True:
                # heartbeat 媛깆떊
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
                    # ?꾨줈?몄뒪 ?ㅽ뻾 以묒씠硫?Redis ?곹깭 ?숆린??
                    # (Redis ??留뚮즺 ?먮뒗 ?ъ떆?묒쑝濡??좎븘媛?寃쎌슦 10珥???蹂듭썝)
                    if _current_process and _current_process.poll() is None:
                        if r.get(STATE_KEY + ":status") != "running":
                            r.set(STATE_KEY + ":status", "running")
                            r.set(STATE_KEY + ":pid", _current_process.pid)
                            logger.info(f"heartbeat: Redis ?곹깭 蹂듭썝 (PID: {_current_process.pid})")
                    elif _current_process and _current_process.poll() is not None:
                        # ?꾨줈?몄뒪媛 醫낅즺?먮뒗???꾩뿭蹂?섍? ?⑥븘?덈뒗 寃쎌슦 ??利됱떆 cleanup
                        logger.warning(f"heartbeat: ?꾨줈?몄뒪 醫낅즺 媛먯? (exit code: {_current_process.returncode}), ?곹깭 ?뺣━")
                        _cleanup_process_state(r)
                    last_heartbeat = now

                result = r.brpop(COMMANDS_KEY, timeout=HEARTBEAT_INTERVAL)

                if result is None:
                    continue

                _, raw_command = result

                try:
                    command = json.loads(raw_command)
                except json.JSONDecodeError:
                    logger.warning(f"?섎せ??紐낅졊 ?뺤떇: {raw_command}")
                    continue

                action = command.get("action")
                source = command.get("source", "unknown")
                timestamp = command.get("timestamp", "")

                logger.info(f"紐낅졊 ?섏떊: action={action}, source={source}, time={timestamp}")

                # 紐낅졊 ?ㅽ뻾
                command_result = execute_command(command, r)
                command_result["action"] = action
                command_result["executed_at"] = datetime.now().isoformat()

                # 寃곌낵 諛섑솚 (API媛 BRPOP?쇰줈 ?湲?以?
                r.lpush(RESULTS_KEY, json.dumps(command_result, ensure_ascii=False))
                # 寃곌낵 ??留뚮즺 ?ㅼ젙 (30珥????먮룞 ??젣, ?꾩쟻 諛⑹?)
                r.expire(RESULTS_KEY, 30)

                logger.info(f"紐낅졊 寃곌낵 諛섑솚: {command_result}")

        except redis.ConnectionError as e:
            logger.warning(f"Redis connection error: {e}, retrying in {reconnect_delay}s")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except KeyboardInterrupt:
            try:
                r.delete(HEARTBEAT_KEY)
            except Exception:
                pass
            logger.info("Ctrl+C濡?醫낅즺")
            break

        except Exception as e:
            logger.error(f"?덉긽移?紐삵븳 ?ㅻ쪟: {e}", exc_info=True)
            time.sleep(5)

    logger.info("Dev Runner Command Listener 醫낅즺")


if __name__ == "__main__":
    main()



