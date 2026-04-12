"""_dr_subprocess.py — dev-runner subprocess 실행 헬퍼 모듈"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import logging
import os
import subprocess
import threading
from pathlib import Path

import redis

from _dr_constants import (
    get_redis_db, PROJECT_ROOT, PLAN_RUNNER_PYTHON, PLAN_RUNNER_MODULE_PATH,
    LOG_CHANNEL_PREFIX, RUNNER_KEY_PREFIX,
)
from _dr_state import get_running_processes, get_running_log_files, get_stream_threads

logger = logging.getLogger(__name__)

import re
_ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _make_plan_runner_env(runner_id: str, **extra: str) -> dict:
    """plan-runner 서브프로세스용 env를 구성한다.

    부모 프로세스의 PLAN_RUNNER_* 키는 stale 값 전파를 막기 위해 기본 제거한다.
    필요한 키는 각 호출부에서 allowlist 형태로 extra 인자로만 명시 주입한다.
    """
    env = os.environ.copy()
    for key in list(env.keys()):
        if key.startswith("PLAN_RUNNER_"):
            env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("CLAUDECODE", None)
    env["PLAN_RUNNER_RUNNER_ID"] = runner_id
    env["REDIS_DB"] = str(get_redis_db())
    env.update(extra)
    return env


def _run_subprocess_streaming(cmd: list, env: dict, cwd: str, pub_fn, tag: str, timeout: int = 300) -> dict:
    """서브프로세스를 실행하며 stdout을 라인별로 실시간 pub_fn에 전달한다.

    capture_output=True 방식 대신 Popen + 라인 스트리밍으로 교체하여
    장시간 실행 중에도 로그 채널이 끊기지 않도록 한다.

    Returns:
        {"success": bool, "message": str, "output": str}
    """
    output_lines: list = []
    timed_out = False
    _timer = None

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        def _kill_on_timeout():
            nonlocal timed_out
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass

        _timer = threading.Timer(timeout, _kill_on_timeout)
        _timer.start()

        for line in proc.stdout:
            stripped = line.rstrip()
            output_lines.append(stripped)
            if pub_fn and stripped:
                try:
                    pub_fn(f"[{tag}] {stripped}")
                except Exception:
                    pass

        proc.wait()

    except Exception as e:
        if _timer:
            _timer.cancel()
        return {"success": False, "message": str(e), "output": "\n".join(output_lines)}
    finally:
        if _timer:
            _timer.cancel()

    if timed_out:
        return {"success": False, "message": f"{tag} timeout ({timeout}s)", "output": "\n".join(output_lines)}

    output_text = "\n".join(output_lines)
    if proc.returncode == 0:
        return {"success": True, "message": f"{tag} 성공", "output": output_text}

    # 실패 시 핵심 에러 라인 추출 (마지막 Error/Exception 라인 우선)
    error_lines = [l.strip() for l in output_lines if l.strip() and ("Error" in l or "Exception" in l)]
    if error_lines:
        msg = error_lines[-1][:300]
    else:
        non_empty = [l.strip() for l in output_lines if l.strip() and not l.strip().startswith(("│", "┌", "└", "├", "─"))]
        msg = "; ".join(non_empty[-3:])[:300] if non_empty else f"exit code {proc.returncode}"
    return {"success": False, "message": msg, "output": output_text}


def _get_fix_engine(redis_client, runner_id: str) -> str:
    """runner의 fix_engine 값을 Redis에서 읽어 반환한다.

    우선순위: fix_engine 키 > engine 키 > "claude" 기본값
    Redis 오류 시 "claude" fallback.
    """
    try:
        value = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:fix_engine")
        if value:
            return value
        value = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine")
        if value:
            return value
    except Exception:
        pass
    return "claude"


def _launch_conflict_resolver_process(runner_id: str, branch: str, worktree_path: Path, redis_client, pub_fn=None, engine: str = "claude", needs_remerge: bool = False) -> dict:
    """plan-runner resolve 서브커맨드로 conflict 자동 해결 프로세스를 실행한다.

    stdout을 라인별로 실시간 pub_fn에 전달하여 로그 끊김을 방지한다.

    Args:
        needs_remerge: True → --needs-remerge 플래그 전달 (abort 후 재머지로 conflict 생성)

    Returns:
        {"success": True/False, "message": str}
    """
    cmd = [
        str(PLAN_RUNNER_PYTHON),
        "-m",
        "plan_runner",
        "resolve",
        "--branch", branch,
        "--project-dir", str(PROJECT_ROOT),
        "--engine", engine,
    ]
    if needs_remerge:
        cmd.append("--needs-remerge")

    env = _make_plan_runner_env(
        runner_id,
        PLAN_RUNNER_PROJECT_ROOT=str(PROJECT_ROOT),
        PLAN_RUNNER_WORK_DIR=str(worktree_path),
    )

    result = _run_subprocess_streaming(
        cmd=cmd,
        env=env,
        cwd=str(PLAN_RUNNER_MODULE_PATH),
        pub_fn=pub_fn,
        tag="RESOLVE",
        timeout=300,
    )
    if result["success"]:
        logger.info(f"[conflict-resolver] auto-resolve 성공 (runner_id={runner_id})")
    else:
        logger.warning(f"[conflict-resolver] auto-resolve 실패 (runner_id={runner_id}): {result['message']}")
    return {"success": result["success"], "message": result["message"]}


def _launch_auto_fix_process(runner_id: str, test_output: str, targets: dict, redis_client, pub_fn=None, engine: str = "claude") -> dict:
    """plan-runner auto-fix 서브커맨드로 자동 수정 프로세스를 실행한다.

    stdout을 라인별로 실시간 pub_fn에 전달하여 로그 끊김을 방지한다.

    Returns:
        {"success": bool, "message": str}
    """
    # test_output을 임시 파일에 기록
    error_file_path = PROJECT_ROOT / "logs" / f"auto-fix-{runner_id}.log"
    try:
        error_file_path.parent.mkdir(parents=True, exist_ok=True)
        error_file_path.write_text(test_output, encoding="utf-8")
    except Exception as e:
        if pub_fn:
            pub_fn(f"[AUTO-FIX] error-file 기록 실패: {e}")

    target_args = []
    for t in targets:
        target_args += ["--target", t]

    cmd = [
        str(PLAN_RUNNER_PYTHON), "-m", "plan_runner", "auto-fix",
        str(PROJECT_ROOT),
        *target_args,
        "--max-attempts", "1",
        "--skip-test",
        "--error-file", str(error_file_path),
        "--engine", engine,
    ]

    env = _make_plan_runner_env(
        runner_id,
        PLAN_RUNNER_PROJECT_ROOT=str(PROJECT_ROOT),
        PLAN_RUNNER_WORK_DIR=str(PROJECT_ROOT),
    )

    result = _run_subprocess_streaming(
        cmd=cmd,
        env=env,
        cwd=str(PLAN_RUNNER_MODULE_PATH),
        pub_fn=pub_fn,
        tag="AUTO-FIX",
        timeout=300,
    )
    if result["success"]:
        logger.info(f"[auto-fix] 성공 (runner_id={runner_id})")
    else:
        logger.warning(f"[auto-fix] 실패 (runner_id={runner_id}): {result['message']}")
    return {"success": result["success"], "message": result["message"]}


def _launch_auto_impl_post_merge_process(runner_id: str, plan_file: str, redis_client, pub_fn=None, engine: str = "claude") -> dict:
    """plan-runner run 서브커맨드로 auto-impl-post-merge 에이전트를 실행한다.

    post-merge 테스트 실패(exit_code=2) 시 호출되어 테스트 수정을 시도한다.

    Args:
        runner_id: runner ID
        plan_file: plan 파일 절대 경로
        redis_client: Redis 클라이언트
        pub_fn: 로그 publish 함수
        engine: 사용할 AI 엔진

    Returns:
        {"success": bool, "message": str}
    """
    cmd = [
        str(PLAN_RUNNER_PYTHON), "-m", "plan_runner", "run",
        "--plan-file", plan_file,
        "--engine", engine,
        "--max-cycles", "1",
    ]

    worktree_path_str = ""
    try:
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path") or ""
    except Exception:
        pass

    env = _make_plan_runner_env(
        runner_id,
        PLAN_RUNNER_PROJECT_ROOT=str(PROJECT_ROOT),
        PLAN_RUNNER_WORK_DIR=worktree_path_str or str(PROJECT_ROOT),
    )

    result = _run_subprocess_streaming(
        cmd=cmd,
        env=env,
        cwd=str(PLAN_RUNNER_MODULE_PATH),
        pub_fn=pub_fn,
        tag="AUTO-IMPL-POST-MERGE",
        timeout=600,
    )
    if result["success"]:
        logger.info(f"[auto-impl-post-merge] 성공 (runner_id={runner_id})")
    else:
        logger.warning(f"[auto-impl-post-merge] 실패 (runner_id={runner_id}): {result['message']}")
    return {"success": result["success"], "message": result["message"]}


def _launch_general_merge_resolver_process(runner_id: str, branch: str, error_msg: str, redis_client, pub_fn=None, engine: str = "claude") -> dict:
    """plan-runner resolve --mode=general-merge-error 서브커맨드로 일반 머지 실패를 자동 복구한다.

    CONFLICT/overwritten 아닌 알 수 없는 에러(exit_code 1 등)에 대해 AI 에이전트가
    git 상태를 분석하고 복구를 시도한다.

    Returns:
        {"success": True/False, "message": str}
    """
    cmd = [
        str(PLAN_RUNNER_PYTHON),
        "-m",
        "plan_runner",
        "resolve",
        "--branch", branch,
        "--project-dir", str(PROJECT_ROOT),
        "--engine", engine,
        "--mode", "general-merge-error",
    ]

    env = _make_plan_runner_env(
        runner_id,
        PLAN_RUNNER_PROJECT_ROOT=str(PROJECT_ROOT),
        PLAN_RUNNER_WORK_DIR=str(PROJECT_ROOT),
        PLAN_RUNNER_MERGE_ERROR=error_msg[:2000],
    )

    result = _run_subprocess_streaming(
        cmd=cmd,
        env=env,
        cwd=str(PLAN_RUNNER_MODULE_PATH),
        pub_fn=pub_fn,
        tag="GENERAL-RESOLVE",
        timeout=300,
    )
    if result["success"]:
        logger.info(f"[general-resolver] 성공 (runner_id={runner_id})")
    else:
        logger.warning(f"[general-resolver] 실패 (runner_id={runner_id}): {result['message']}")
    return {"success": result["success"], "message": result["message"]}
