"""
Redis Dev Runner Command Listener

Session 1 (사용자 세션)에서 실행되는 dev-runner 명령 리스너입니다.
API 서버(Session 0)에서 Redis를 통해 전달된 명령을 수신하고 실행합니다.

동작 방식:
    - BRPOP으로 plan-runner:commands 큐를 블로킹 대기 (CPU 0%)
    - 명령 수신 시 plan-runner CLI 실행
    - 실행 결과/PID를 plan-runner:command_results에 반환
    - stop 명령 시 프로세스 terminate

사용법:
    python scripts/dev-runner-command-listener.py

아키텍처:
    API (Session 0) -> Redis LPUSH -> [이 리스너 (Session 1)] -> plan-runner CLI
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

import redis

# scripts/ 디렉토리 sys.path 등록
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _dr_constants import (
    REDIS_HOST, REDIS_PORT, COMMANDS_KEY, RESULTS_KEY, RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL,
    RECENT_RUNNERS_TTL, ADMIN_API_PORT, RUNNER_KEY_SUFFIXES,
    HEARTBEAT_KEY, HEARTBEAT_INTERVAL, HEARTBEAT_TTL, MERGE_ACTIVE_STATUSES,
    SCRIPT_DIR, PROJECT_ROOT, WORKTREE_BASE_DIR, WTOOLS_BASE_DIR,
    PLAN_RUNNER_MODULE_PATH, PLAN_RUNNER_PYTHON, LOG_DIR,
    LOG_CHANNEL_PREFIX,
    get_redis_db, set_redis_db, get_admin_api_base,
)
from _dr_state import (
    set_wf_manager, get_wf_manager, get_running_processes, get_running_log_files,
    get_stream_threads, get_cleanup_done, get_dead_process_first_seen,
)
from _dr_process_utils import (
    _evict_stale_cleanup_done, _evict_stale_dead_process, _is_pid_alive,
    _cleanup_process_state, _DummyProcess, _tail_log_and_publish,
    _monitor_pid_until_exit, _attach_to_running_process, _recover_pending_merge,
    _reconnect_surviving_runners, _detect_orphan_workflows, _cleanup_orphan_plans,
)
from _dr_subprocess import (
    _run_subprocess_streaming, _get_fix_engine, _make_plan_runner_env,
    _launch_conflict_resolver_process, _launch_auto_fix_process,
    _launch_auto_impl_post_merge_process, _launch_general_merge_resolver_process,
)
from _dr_merge import (
    _execute_merge_with_lock, _handle_post_merge_done, _call_done_api, _pub_and_log,
    detect_merged_but_not_done,
)
from _dr_plan_runner import (
    _do_inline_merge, _stream_output, _do_start_plan_runner,
    start_plan_runner, _launch_plan_runner_process,
    stop_plan_runner, get_status, force_stop_plan_runner, force_kill_plan_runner,
)
from _dr_commands import (
    _do_retry_merge, retry_merge, _do_direct_merge, direct_merge,
    _do_resolve_conflict, resolve_conflict, _do_cleanup_worktree, cleanup_worktree,
    start_merge_orchestrator, _reconnect_surviving_merge_orchestrator, stop_merge_orchestrator,
)

from workflow_manager import WorkflowManager
from worktree_manager import WorktreeManager

# 로깅 설정
log_dir = PROJECT_ROOT / "logs" / "admin"
log_dir.mkdir(parents=True, exist_ok=True)
_log_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / f"dev_runner_command_listener_{_log_timestamp}.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# 하위 호환 별칭 — 테스트/외부 코드에서 직접 접근 지원 (리팩토링 후 _dr_state로 이동됨)
_running_processes = get_running_processes()
_running_log_files = get_running_log_files()
_stream_threads = get_stream_threads()
_cleanup_done = get_cleanup_done()
_dead_process_first_seen = get_dead_process_first_seen()


def execute_command(command: Dict, redis_client: redis.Redis) -> Dict:
    """명령 실행

    Args:
        command: {action: str, ...}
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str, ...}
    """
    action = command.get("action")

    if action == "run":
        return start_plan_runner(command, redis_client)
    elif action == "stop":
        runner_id = command.get("runner_id", "")
        return stop_plan_runner(runner_id, redis_client)
    elif action == "force-stop":
        runner_id = command.get("runner_id", "")
        return force_stop_plan_runner(runner_id, redis_client)
    elif action == "force-kill":
        runner_id = command.get("runner_id", "")
        return force_kill_plan_runner(runner_id, redis_client)
    elif action == "status":
        return get_status(redis_client)
    elif action == "retry-merge":
        return retry_merge(command, redis_client)
    elif action == "direct-merge":
        return direct_merge(command, redis_client)
    elif action == "resolve-conflict":
        return resolve_conflict(command, redis_client)
    elif action == "cleanup-worktree":
        return cleanup_worktree(command, redis_client)
    elif action == "start-orchestrator":
        return start_merge_orchestrator(redis_client)
    elif action == "stop-orchestrator":
        return stop_merge_orchestrator(redis_client)
    else:
        return {"success": False, "message": f"Unknown action: {action}"}


def main():
    """메인 루프: Redis BRPOP으로 명령 대기 및 실행."""
    set_wf_manager(WorkflowManager(PROJECT_ROOT / "data" / "monitor.db"))
    logger.info("=" * 50)
    logger.info("Dev Runner Command Listener 시작")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"명령 큐: {COMMANDS_KEY}")
    logger.info(f"결과 큐: {RESULTS_KEY}")
    logger.info(f"Runner Key Prefix: {RUNNER_KEY_PREFIX}")
    logger.info(f"plan-runner 모듈: {PLAN_RUNNER_MODULE_PATH}")
    logger.info("=" * 50)

    reconnect_delay = 1

    while True:
        try:
            # Redis 연결
            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=get_redis_db(),
                decode_responses=True,
                socket_connect_timeout=5,
            )
            r.ping()
            logger.info("Redis 연결 성공")
            reconnect_delay = 1  # 연결 성공 시 리셋

            # 초기 heartbeat 설정 (시작 즉시 한 번 찍음)
            r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
            last_heartbeat = time.time()

            # listener 시작/재시작 시 생존 plan-runner 재연결 (고아 프로세스 처리)
            _reconnect_surviving_runners(r)
            # listener 시작/재시작 시 DB↔Redis 교차검증으로 고아 워크플로우 탐지
            orphan_wf_count = _detect_orphan_workflows(r)
            orphan_plan_count = _cleanup_orphan_plans(r)
            if orphan_wf_count or orphan_plan_count:
                logger.warning(f"[orphan] 고아 탐지 완료: workflow {orphan_wf_count}개 정리, plan {orphan_plan_count}개 정리")
            # listener 시작/재시작 시 생존 MergeOrchestrator 재연결
            _reconnect_surviving_merge_orchestrator(r)

            # Redis 재연결 시 현재 프로세스 상태 복원
            _running_processes = get_running_processes()
            for rid, proc in list(_running_processes.items()):
                if proc.poll() is None and _is_pid_alive(proc.pid):
                    r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
                    r.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", proc.pid)
                    r.sadd(ACTIVE_RUNNERS_KEY, rid)
                    logger.info(f"Redis 재연결: 프로세스 상태 복원 (runner_id: {rid}, PID: {proc.pid})")

            # BRPOP 루프 (블로킹 대기)
            while True:
                # heartbeat 갱신
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
                    _evict_stale_cleanup_done()
                    _evict_stale_dead_process()
                    # 각 runner 상태 동기화
                    _running_processes = get_running_processes()
                    _cleanup_done = get_cleanup_done()
                    _dead_process_first_seen = get_dead_process_first_seen()
                    _stream_threads = get_stream_threads()
                    _wf_manager = get_wf_manager()
                    for rid, proc in list(_running_processes.items()):
                        if rid in _cleanup_done:
                            _running_processes.pop(rid, None)
                            continue
                        if proc.poll() is None:
                            current_status = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
                            if current_status not in (None, "stopped") and current_status != "running":
                                r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
                                r.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", proc.pid)
                                r.sadd(ACTIVE_RUNNERS_KEY, rid)
                                logger.info(f"heartbeat: Redis 상태 복원 (runner_id: {rid}, PID: {proc.pid})")
                        else:
                            # 프로세스가 종료되었는데 전역변수가 남아있는 경우 — 머지 진행 중 여부 확인 후 cleanup
                            if rid not in _dead_process_first_seen:
                                _dead_process_first_seen[rid] = time.time()
                            _dead_elapsed = time.time() - _dead_process_first_seen.get(rid, time.time())
                            try:
                                _hb_mr = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_requested")
                                _hb_ms = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_status")
                            except Exception:
                                _hb_mr, _hb_ms = None, None
                            if _hb_mr or _hb_ms in MERGE_ACTIVE_STATUSES:
                                if _dead_elapsed >= 60:
                                    # 60초 경과: stale merge flag → 강제 cleanup
                                    logger.warning(
                                        f"heartbeat: runner {rid} merge stale {_dead_elapsed:.0f}초 → 강제 cleanup "
                                        f"(merge_requested={bool(_hb_mr)}, merge_status={_hb_ms})"
                                    )
                                    # merge lock 해제 (wtools subprocess 사망 fallback)
                                    try:
                                        from merge_lock import release_merge_lock, _get_repo_id
                                        release_merge_lock(r, rid, repo_id=_get_repo_id(PROJECT_ROOT))
                                    except Exception:
                                        pass
                                    # merge 키 삭제 후 cleanup (머지 가드 자연 통과)
                                    try:
                                        r.delete(f"{RUNNER_KEY_PREFIX}:{rid}:merge_requested")
                                        r.delete(f"{RUNNER_KEY_PREFIX}:{rid}:merge_status")
                                    except Exception:
                                        pass
                                    # heartbeat_stale_merge는 머지 가드 대상 아님 — 직접 호출
                                    _running_processes.pop(rid, None)
                                    _dead_process_first_seen.pop(rid, None)
                                    _cleanup_done[rid] = time.time()
                                    _cleanup_process_state(rid, r, reason="process_cleanup")
                                    # Workflow DB 보정: running 상태면 failed로
                                    try:
                                        if _wf_manager:
                                            wf = _wf_manager.get_by_runner_id(rid)
                                            if wf and wf["status"] == "running":
                                                _wf_manager.update_status(wf["id"], "failed", error_message="heartbeat: stale merge flag timeout")
                                    except Exception:
                                        pass
                                else:
                                    logger.info(
                                        f"heartbeat: runner {rid} 프로세스 종료 but 머지 진행중 "
                                        f"(merge_requested={bool(_hb_mr)}, merge_status={_hb_ms}, elapsed={_dead_elapsed:.0f}s) → cleanup 스킵"
                                    )
                                    # Workflow DB 보정: running 상태면 failed로 (merge_pending/merging은 보존)
                                    try:
                                        if _wf_manager:
                                            wf = _wf_manager.get_by_runner_id(rid)
                                            if wf and wf["status"] == "running":
                                                _wf_manager.update_status(wf["id"], "failed", error_message="heartbeat: process dead, merge flag set")
                                    except Exception:
                                        pass
                            else:
                                # _stream_output 스레드가 아직 finally 블록 실행 중이면 cleanup 위임
                                _t = _stream_threads.get(rid)
                                if _t and _t.is_alive():
                                    if _dead_elapsed >= 30:
                                        # 30초 경과: stream thread hang → 강제 cleanup
                                        logger.warning(
                                            f"heartbeat: runner {rid} stream thread hang {_dead_elapsed:.0f}초 → 강제 cleanup"
                                        )
                                        # v2 merge fallback: stream thread가 hang 중이라 finally 미실행 가능
                                        _hang_v2_detect = None
                                        try:
                                            _hang_v2_detect = detect_merged_but_not_done(rid, r)
                                        except Exception as _hang_det_err:
                                            logger.debug(f"heartbeat: v2 detect 실패 (hang 경로, 무시): {_hang_det_err}")
                                        if _hang_v2_detect:
                                            logger.info(f"heartbeat: v2 merge fallback 실행 (hang 경로, runner_id={rid})")
                                            try:
                                                def _hang_pub(msg: str, _rid=rid) -> None:
                                                    _pub_and_log(_rid, msg, r, "MERGE-FALLBACK")
                                                _handle_post_merge_done(_hang_v2_detect["plan_file"], rid, _hang_pub, r)
                                            except Exception as _hang_fb_err:
                                                logger.warning(f"heartbeat: v2 merge fallback 실패 (hang, cleanup 계속): {_hang_fb_err}")
                                        _cleanup_process_state(rid, r, reason="heartbeat_dead_process")
                                    else:
                                        logger.debug(
                                            f"heartbeat: runner {rid} _stream_output 스레드 alive → cleanup 위임 "
                                            f"(exit code: {proc.returncode}, elapsed={_dead_elapsed:.0f}s)"
                                        )
                                        # Workflow DB 보정: running 상태면 failed로
                                        try:
                                            if _wf_manager:
                                                wf = _wf_manager.get_by_runner_id(rid)
                                                if wf and wf["status"] == "running":
                                                    _wf_manager.update_status(wf["id"], "failed", error_message="heartbeat: process dead, stream thread alive")
                                        except Exception:
                                            pass
                                else:
                                    logger.warning(f"heartbeat: 프로세스 종료 감지 (runner_id: {rid}, exit code: {proc.returncode}, merge_status={_hb_ms}), 상태 정리")
                                    # v2 merge fallback: merge_requested 없어도 merge 후처리 누락 여부 확인
                                    _hb_v2_detect = None
                                    try:
                                        _hb_v2_detect = detect_merged_but_not_done(rid, r)
                                    except Exception as _hb_det_err:
                                        logger.debug(f"heartbeat: v2 detect 실패 (무시): {_hb_det_err}")
                                    if _hb_v2_detect:
                                        logger.info(f"heartbeat: v2 merge fallback 실행 (runner_id={rid})")
                                        try:
                                            def _hb_pub(msg: str, _rid=rid) -> None:
                                                _pub_and_log(_rid, msg, r, "MERGE-FALLBACK")
                                            _handle_post_merge_done(_hb_v2_detect["plan_file"], rid, _hb_pub, r)
                                        except Exception as _hb_fb_err:
                                            logger.warning(f"heartbeat: v2 merge fallback 실패 (cleanup 계속): {_hb_fb_err}")
                                    _cleanup_process_state(rid, r, reason="heartbeat_dead_process")

                    last_heartbeat = now

                result = r.brpop(COMMANDS_KEY, timeout=HEARTBEAT_INTERVAL)

                if result is None:
                    continue

                _, raw_command = result

                try:
                    command = json.loads(raw_command)
                except json.JSONDecodeError:
                    logger.warning(f"잘못된 명령 형식: {raw_command}")
                    continue

                action = command.get("action")
                source = command.get("source", "unknown")
                timestamp = command.get("timestamp", "")

                logger.info(f"명령 수신: action={action}, source={source}, time={timestamp}")

                # 명령 실행
                command_result = execute_command(command, r)

                # run 명령은 백그라운드 스레드가 결과를 직접 push → main loop에서 스킵
                if command_result is None:
                    logger.info(f"명령 결과: run 명령 — 백그라운드 스레드가 결과 반환 예정")
                    continue

                command_result["action"] = action
                command_result["executed_at"] = datetime.now().isoformat()

                # 결과 반환 (per-command 키 우선, 하위호환으로 공유 키 fallback)
                command_id = command.get("command_id", "")
                result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
                r.lpush(result_key, json.dumps(command_result, ensure_ascii=False))
                # 결과 키 만료 설정 (60초 후 자동 삭제, 누적 방지)
                r.expire(result_key, 60)

                logger.info(f"명령 결과 반환: {command_result}")

        except redis.ConnectionError as e:
            logger.warning(f"Redis connection error: {e}, retrying in {reconnect_delay}s")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except KeyboardInterrupt:
            try:
                r.delete(HEARTBEAT_KEY)
            except Exception:
                pass
            logger.info("Ctrl+C로 종료")
            break

        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}", exc_info=True)
            time.sleep(5)

    logger.info("Dev Runner Command Listener 종료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dev Runner Command Listener")
    parser.add_argument(
        "--redis-db",
        type=int,
        default=0,
        help="Redis DB 번호 (기본: 0, 테스트 격리 시 1 이상 사용)",
    )
    args = parser.parse_args()
    set_redis_db(args.redis_db)
    main()
