"""_dr_process_utils.py — dev-runner 프로세스 유틸리티 모듈"""
import logging
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import redis

from _dr_constants import (
    RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL,
    LOG_CHANNEL_PREFIX, MERGE_ACTIVE_STATUSES, WORKTREE_BASE_DIR,
    RECENT_RUNNERS_TTL, RUNNER_KEY_SUFFIXES, PROJECT_ROOT,
)
from _dr_plan_paths import classify_plan_stage, read_plan_status
from _dr_state import (
    get_running_processes, get_running_log_files, get_stream_threads,
    get_cleanup_done, get_dead_process_first_seen, get_wf_manager,
)
from _dr_log_framing import MultilineFrameBuffer
from _dr_subprocess import _ANSI_ESCAPE
from _dr_runtime_utils import _normalize_exit_reason, _publish_with_retry

logger = logging.getLogger(__name__)


def _is_pre_review_stopped_runner(runner_id: str, redis_client: redis.Redis) -> bool:
    """runner가 검토완료 이전(pre_review) 중지 상태인지 판별."""
    try:
        stop_stage = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage")
        if stop_stage == "pre_review":
            return True
        if stop_stage == "post_review":
            return False
    except Exception:
        pass

    try:
        exit_reason = _normalize_exit_reason(
            redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")
        )
    except Exception:
        exit_reason = ""
    if exit_reason != "stopped":
        return False

    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
            return False
        stage = classify_plan_stage(read_plan_status(plan_file))
        if stage in ("pre_review", "post_review"):
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage", stage)
            except Exception:
                pass
        return stage == "pre_review"
    except Exception:
        return False


def _evict_stale_cleanup_done(max_age: int = 300) -> None:
    """_cleanup_done에서 max_age초 이상 된 항목 제거 (메모리 누수 방지)"""
    _cleanup_done = get_cleanup_done()
    now = time.time()
    expired = [rid for rid, ts in list(_cleanup_done.items()) if now - ts > max_age]
    if expired:
        logger.debug(f"heartbeat: _cleanup_done TTL 소거 {len(expired)}개: {expired}")
        for rid in expired:
            _cleanup_done.pop(rid, None)


def _evict_stale_dead_process(max_age: int = 300) -> None:
    """_dead_process_first_seen에서 max_age초 이상 된 항목 제거 (메모리 누수 방지)"""
    _dead_process_first_seen = get_dead_process_first_seen()
    now = time.time()
    expired = [rid for rid, ts in list(_dead_process_first_seen.items()) if now - ts > max_age]
    if expired:
        logger.debug(f"heartbeat: _dead_process_first_seen TTL 소거 {len(expired)}개: {expired}")
        for rid in expired:
            _dead_process_first_seen.pop(rid, None)


def _is_pid_alive(pid: int) -> bool:
    """PID가 실제로 살아있는지 OS 레벨 확인 (Windows)"""
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


def _parse_start_elapsed_seconds(start_time_raw, now_ts: Optional[float] = None) -> Optional[float]:
    """start_time 값(epoch/isoformat)을 경과 초로 변환. 변환 불가 시 None."""
    if start_time_raw in (None, ""):
        return None

    raw = str(start_time_raw).strip()
    if not raw:
        return None

    current_ts = time.time() if now_ts is None else now_ts

    # 1) epoch seconds/milliseconds 처리
    try:
        start_ts = float(raw)
        if start_ts > 1e12:  # milliseconds
            start_ts = start_ts / 1000.0
        return max(0.0, current_ts - start_ts)
    except Exception:
        pass

    # 2) ISO8601 문자열 처리 (naive datetime 포함)
    try:
        start_dt = datetime.fromisoformat(raw)
        return max(0.0, current_ts - start_dt.timestamp())
    except Exception:
        return None


def _is_recent_runner_without_hb(
    redis_client: redis.Redis,
    runner_id: str,
    startup_grace_seconds: int = 600,
) -> tuple[bool, Optional[float]]:
    """subprocess_heartbeat 미존재 시, start_time 기준으로 최근 실행 runner인지 판정."""
    try:
        start_time_raw = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")
    except Exception:
        return False, None

    start_elapsed = _parse_start_elapsed_seconds(start_time_raw)
    if start_elapsed is None:
        return False, None
    return start_elapsed < startup_grace_seconds, start_elapsed


def get_plan_git_root(plan_file: str) -> Path:
    """plan 파일의 git root를 동적으로 감지한다."""
    import subprocess
    try:
        plan_path = Path(plan_file)
        cwd = str(plan_path.parent) if plan_path.parent.is_dir() else str(plan_path.parent.parent)
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception as e:
        logger.warning(f"get_plan_git_root: git rev-parse 실패 (plan={plan_file}): {e}")
    logger.warning(f"get_plan_git_root: fallback to PROJECT_ROOT (plan={plan_file})")
    return PROJECT_ROOT


def _cleanup_process_state(runner_id: str, redis_client: redis.Redis, reason: str = "process_cleanup"):
    """전역 프로세스 변수 + Redis 상태 정리 (per-runner) + Workflow DB 갱신"""
    _running_processes = get_running_processes()
    _running_log_files = get_running_log_files()
    _stream_threads = get_stream_threads()
    _cleanup_done = get_cleanup_done()
    _dead_process_first_seen = get_dead_process_first_seen()
    _wf_manager = get_wf_manager()

    # pre-review 중지 케이스는 별도 태그로 기록 (reconnect/heartbeat 공통)
    if reason and reason.startswith(("reconnect_", "heartbeat_", "no_log_file")):
        if _is_pre_review_stopped_runner(runner_id, redis_client):
            reason = "pre_review_stopped"

    # 🔴 머지 보호 가드: reconnect_* / heartbeat_* 계열 reason이면 머지 진행 중 cleanup 거부
    if reason and reason.startswith(("reconnect_", "heartbeat_")):
        try:
            merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            if merge_status in MERGE_ACTIVE_STATUSES:
                logger.warning(
                    f"[cleanup] 머지 진행중 runner {runner_id} cleanup 거부 "
                    f"(reason={reason}, merge_status={merge_status}, elapsed=확인불가)"
                )
                return
        except Exception as _guard_err:
            logger.debug(f"[cleanup] 머지 가드 조회 실패 (무시): {_guard_err}")

    # 프로세스 사망 시 merge lock 안전 해제 (wtools subprocess 사망 fallback)
    _repo_id = None
    try:
        from merge_queue import release_merge_turn, _get_repo_id
        _repo_id = _get_repo_id(PROJECT_ROOT)
        release_merge_turn(redis_client, runner_id, repo_id=_repo_id)
    except Exception:
        pass

    # 대기 큐에서 이 runner 제거 (crash/정상종료 모두, 고아 엔트리 방지)
    try:
        # defense-in-depth: release_merge_turn이 이미 LREM, 여기선 잔존 방어
        from merge_queue import get_queue_key, _get_repo_id
        if _repo_id is None:
            _repo_id = _get_repo_id(PROJECT_ROOT)
        redis_client.lrem(get_queue_key(_repo_id), 0, runner_id)
    except Exception:
        pass

    _running_processes.pop(runner_id, None)
    _running_log_files.pop(runner_id, None)
    _dead_process_first_seen.pop(runner_id, None)
    _cleanup_done[runner_id] = time.time()
    if runner_id in _stream_threads:
        t = _stream_threads.pop(runner_id)
        if t.is_alive() and t != threading.current_thread():
            t.join(timeout=3)
        elif t == threading.current_thread():
            logger.debug(f"[cleanup] self-join 스킵 (runner_id={runner_id})")

    # 1) 종료된 runner를 RECENT_RUNNERS에 등록하여 탭 이력 보존 (worktree 정리보다 먼저)
    try:
        from _dr_constants import RECENT_RUNNERS_KEY
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if suffix in ("plan_file", "branch"):
                continue  # 불변 속성: TTL 없이 영구 보존 (종료 후에도 탭 표시용)
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            redis_client.expire(key, RECENT_RUNNERS_TTL)
        redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
        redis_client.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
        logger.info(f"[cleanup] RECENT 등록 완료: {runner_id}")
    except Exception as e:
        logger.warning(f"[cleanup] RECENT 등록 실패 (runner_id={runner_id}): {e}")

    # RECENT/stopped 반영 이후 완료 신호 publish (SSE 상태/완료 순서 충돌 방지)
    try:
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        exit_reason = _normalize_exit_reason(
            redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")
        )
        _publish_with_retry(redis_client, log_channel, f"__COMPLETED::{exit_reason}__")
    except Exception:
        pass

    # 2) worktree 정리 (RECENT 등록과 분리하여 worktree 실패가 탭 보존을 깨지 않도록)
    try:
        from worktree_manager import WorktreeManager
        from plan_worktree_helpers import is_plan_in_progress as _is_plan_in_progress

        merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        plan_file_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if plan_file_val in (PLAN_FILE_ALL, _LEGACY_ALL):
            plan_file_val = None
        _cleanup_worktree_base = (get_plan_git_root(plan_file_val) / ".worktrees") if plan_file_val else WORKTREE_BASE_DIR

        _preserve_worktree = False
        if plan_file_val and _is_plan_in_progress(plan_file_val):
            _preserve_worktree = True
            logger.info(f"워크트리 보존 (plan 구현중): {runner_id}")
            # 워크트리 보존 시 worktree_path TTL 제거 (영구 보존)
            redis_client.persist(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")

        if not _preserve_worktree and merge_status not in ("pending_merge", "conflict", "queued"):
            try:
                WorktreeManager.remove(runner_id, _cleanup_worktree_base, plan_file=plan_file_val or None)
            except Exception as wt_e:
                logger.warning(f"worktree 정리 실패 (runner_id: {runner_id}): {wt_e}")
        elif not _preserve_worktree and merge_status in ("merging", "testing"):
            try:
                WorktreeManager.remove(runner_id, _cleanup_worktree_base, plan_file=plan_file_val or None)
                logger.info(f"stale 중간 상태 worktree 정리: {runner_id} (merge_status={merge_status})")
            except Exception as wt_e:
                logger.warning(f"stale worktree 정리 실패 (runner_id: {runner_id}): {wt_e}")
    except Exception as e:
        logger.warning(f"[cleanup] worktree 정리 중 오류 (무시, runner_id={runner_id}): {e}")

    # Workflow DB: running 상태인 경우 failed로 전이
    try:
        if _wf_manager:
            wf = _wf_manager.get_by_runner_id(runner_id)
            if wf and wf["status"] in ("running", "merge_pending", "merging"):
                _wf_manager.update_status(wf["id"], "failed", error_message=f"Cleanup: {reason}")
                logger.info(f"[cleanup] workflow {wf['id']} → failed (reason: {reason})")
    except Exception as e:
        logger.warning(f"[cleanup] workflow DB 갱신 실패 (무시): {e}")

    logger.info(f"[cleanup] _cleanup_process_state 완료: {runner_id} (reason={reason})")


class _DummyProcess:
    """재연결된 plan-runner 프로세스를 위한 래퍼.

    기존 코드의 ``proc.poll()`` 호출과 호환되도록 poll() / wait() 인터페이스를 제공한다.
    실제 stdout pipe는 없으므로 로그 tailing은 별도 스레드(_tail_log_and_publish)가 담당한다.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        """프로세스가 살아있으면 None, 종료되었으면 -1 반환."""
        if self.returncode is not None:
            return self.returncode
        if not _is_pid_alive(self.pid):
            self.returncode = -1
        return self.returncode


def _tail_log_and_publish(runner_id: str, log_path: str, redis_client: redis.Redis):
    """로그 파일 끝(EOF)부터 새 줄을 읽어 Redis log channel에 publish하는 스레드.

    재연결된 runner에서 pipe가 없을 때 파일 tailing으로 대체 스트리밍한다.
    PID 종료 + 더 이상 새 줄 없음 → 스레드 종료.
    """
    _running_processes = get_running_processes()
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    frame_buffer = MultilineFrameBuffer(max_chars=8192)
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # 파일 끝으로 이동 (재연결 전 기존 내용은 재발행하지 않음)
            f.seek(0, 2)
            while True:
                # runner가 이미 cleanup됐으면 스레드 종료
                if runner_id not in _running_processes:
                    break
                line = f.readline()
                if line:
                    stripped = _ANSI_ESCAPE.sub('', line.rstrip('\n'))
                    ready_frames, overflow = frame_buffer.push_line(stripped)
                    if overflow:
                        logger.warning(
                            f"[tail_log] 프레임 버퍼 상한(8192 chars) 초과 즉시 flush (runner_id={runner_id})"
                        )
                    for frame in ready_frames:
                        _publish_with_retry(redis_client, log_channel, frame)
                else:
                    # 더 읽을 내용 없음 — PID가 죽었는지 확인
                    proc = _running_processes.get(runner_id)
                    if proc is not None and proc.poll() is not None:
                        # 프로세스 종료 후 파일에 추가된 잔여 라인을 한 번 더 드레인
                        # (plan-runner가 종료 직전 _log()로 기록한 FAIL 로그 등)
                        time.sleep(0.3)  # 파일 flush 대기
                        while True:
                            remaining = f.readline()
                            if not remaining:
                                break
                            _stripped = _ANSI_ESCAPE.sub('', remaining.rstrip('\n'))
                            if _stripped:
                                _ready, _overflow = frame_buffer.push_line(_stripped)
                                if _overflow:
                                    logger.warning(
                                        f"[tail_log] drain 프레임 버퍼 상한 초과 즉시 flush (runner_id={runner_id})"
                                    )
                                for _frame in _ready:
                                    _publish_with_retry(redis_client, log_channel, _frame)
                        pending = frame_buffer.flush()
                        if pending:
                            _publish_with_retry(redis_client, log_channel, pending)
                        break
                    time.sleep(0.2)
            pending = frame_buffer.flush()
            if pending:
                _publish_with_retry(redis_client, log_channel, pending)
    except FileNotFoundError:
        logger.warning(f"[tail_log] 로그 파일 없음: {log_path}")
    except Exception as e:
        logger.error(f"[tail_log] 스레드 오류 (runner_id={runner_id}): {e}")


def _monitor_pid_until_exit(runner_id: str, pid: int, redis_client: redis.Redis):
    """PID 종료를 1초 간격으로 감지하여 _cleanup_process_state()를 호출하는 스레드."""
    _running_processes = get_running_processes()
    _cleanup_done = get_cleanup_done()
    _stream_threads = get_stream_threads()
    while True:
        # 이미 cleanup됐으면 즉시 종료 (중복 cleanup 방지)
        if runner_id not in _running_processes or runner_id in _cleanup_done:
            break
        if not _is_pid_alive(pid):
            # proc.poll()과 교차검증 — _is_pid_alive 단독 판정으로 인한 premature cleanup 방지
            proc = _running_processes.get(runner_id)
            if proc is not None and proc.poll() is None:
                # _is_pid_alive는 dead 신호, poll()은 alive — 일시적 불일치, 3초 후 재확인
                logger.info(
                    f"[monitor_pid] runner {runner_id} PID API dead but poll alive → 3초 재확인"
                )
                time.sleep(3)
                # 재확인 후 _running_processes에 없으면 다른 스레드가 정리함 → 종료
                if runner_id not in _running_processes or runner_id in _cleanup_done:
                    break
                if _running_processes.get(runner_id, proc).poll() is None:
                    time.sleep(1)
                    continue  # 다음 루프에서 재판정
            # _cleanup_done 재확인 (교차검증 대기 사이에 다른 스레드가 cleanup했을 수 있음)
            if runner_id in _cleanup_done:
                break
            logger.info(f"[monitor_pid] runner {runner_id} PID {pid} 종료 감지 → tail 스레드 완료 대기")
            # tail 스레드가 파일 끝까지 drain 하도록 최대 5초 대기
            tail_thread = _stream_threads.get(runner_id)
            if tail_thread and tail_thread.is_alive():
                tail_thread.join(timeout=5)
            if runner_id in _cleanup_done:
                break
            logger.info(f"[monitor_pid] runner {runner_id} → cleanup")
            # v2 merge fallback: merge_requested 없어도 merge 후처리 누락 여부 확인
            try:
                from _dr_merge import detect_merged_but_not_done as _dmnd, _handle_post_merge_done as _hpmd, _pub_and_log as _pal
                _mp_detect = _dmnd(runner_id, redis_client)
                if _mp_detect:
                    logger.info(f"[monitor_pid] v2 merge fallback 실행 (runner_id={runner_id})")
                    try:
                        def _mp_pub(msg: str, _rid=runner_id) -> None:
                            _pal(_rid, msg, redis_client, "MERGE-FALLBACK")
                        _hpmd(_mp_detect["plan_file"], runner_id, _mp_pub, redis_client)
                    except Exception as _mp_fb_err:
                        logger.warning(f"[monitor_pid] v2 merge fallback 실패 (cleanup 계속): {_mp_fb_err}")
            except Exception as _mp_det_err:
                logger.debug(f"[monitor_pid] v2 detect 실패 (무시): {_mp_det_err}")
            _cleanup_process_state(runner_id, redis_client, reason="heartbeat_pid_exit")
            break
        time.sleep(1)


def _attach_to_running_process(runner_id: str, pid: int, redis_client: redis.Redis):
    """listener 재시작 시 이미 살아있는 plan-runner에 재연결.

    pipe가 없으므로 로그 파일 tailing + PID 모니터 스레드로 대체 연결한다.
    """
    _running_processes = get_running_processes()
    _running_log_files = get_running_log_files()
    _stream_threads = get_stream_threads()

    # 로그 파일 경로 조회
    log_file_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
    if not log_file_path:
        log_file_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
    if not log_file_path or not Path(log_file_path).exists():
        logger.warning(f"[attach] runner {runner_id} 로그 파일 없음 → cleanup")
        # v2 merge fallback: 로그 없어도 merge 완료 여부 확인
        try:
            from _dr_merge import detect_merged_but_not_done as _dmnd, _handle_post_merge_done as _hpmd, _pub_and_log as _pal
            _nl_detect = _dmnd(runner_id, redis_client)
            if _nl_detect:
                logger.info(f"[attach] v2 merge fallback 실행 (runner_id={runner_id})")
                try:
                    def _nl_pub(msg: str, _rid=runner_id) -> None:
                        _pal(_rid, msg, redis_client, "MERGE-FALLBACK")
                    _hpmd(_nl_detect["plan_file"], runner_id, _nl_pub, redis_client)
                except Exception as _nl_fb_err:
                    logger.warning(f"[attach] v2 merge fallback 실패 (cleanup 계속): {_nl_fb_err}")
        except Exception as _nl_det_err:
            logger.debug(f"[attach] v2 detect 실패 (무시): {_nl_det_err}")
        _cleanup_process_state(runner_id, redis_client, reason="no_log_file")
        return

    # _DummyProcess 등록 (기존 heartbeat 루프의 proc.poll() 호환)
    dummy = _DummyProcess(pid)
    _running_processes[runner_id] = dummy
    _running_log_files[runner_id] = Path(log_file_path)

    # tailing 스레드 시작
    tail_thread = threading.Thread(
        target=_tail_log_and_publish,
        args=(runner_id, log_file_path, redis_client),
        daemon=True,
    )
    tail_thread.start()
    _stream_threads[runner_id] = tail_thread

    # PID 모니터 스레드 시작
    monitor_thread = threading.Thread(
        target=_monitor_pid_until_exit,
        args=(runner_id, pid, redis_client),
        daemon=True,
    )
    monitor_thread.start()

    logger.info(f"[listener] 재시작 감지: runner {runner_id} PID {pid} 생존 → 재연결")


def _recover_pending_merge(runner_id: str, redis_client: redis.Redis, merge_status) -> None:
    """리스너 재시작 시 미완료 머지 복구."""
    from merge_queue import release_merge_turn, _get_repo_id  # noqa: F401

    logger.info(f"[recover_merge] runner {runner_id} 머지 복구 시작 (merge_status={merge_status})")

    try:
        if merge_status in ("merging", "resolving"):
            # stale lock 해제 후 merge_status 삭제. _do_inline_merge가 acquire 시 queued로 재설정
            try:
                release_merge_turn(redis_client, runner_id, repo_id=_get_repo_id(PROJECT_ROOT))
                logger.info(f"[recover_merge] runner {runner_id} stale merge lock 해제 (merge_status={merge_status})")
            except Exception as _e:
                logger.debug(f"[recover_merge] lock 해제 실패 (무시): {_e}")
            redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            # merge_requested 플래그가 없으면 새로 설정 (재진입 용)
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            if not _mr:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")

        elif merge_status in ("queued", "pending_merge") or merge_status is None:
            # merge_requested가 있으면 그대로 _do_inline_merge 호출
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            if not _mr:
                # merge_requested 없으면 새로 설정
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
        else:
            logger.info(f"[recover_merge] runner {runner_id} merge_status={merge_status} → 복구 불필요")
            return

        from _dr_plan_runner import _do_inline_merge
        _do_inline_merge(runner_id, redis_client)

    except Exception as e:
        logger.warning(f"[recover_merge] runner {runner_id} 머지 복구 실패: {e}")


def _reconnect_surviving_runners(redis_client: redis.Redis):
    """listener 시작(또는 재시작) 시 한 번 호출."""
    _running_processes = get_running_processes()
    _stream_threads = get_stream_threads()
    try:
        runner_ids = redis_client.smembers(ACTIVE_RUNNERS_KEY)
    except Exception as e:
        logger.warning(f"[reconnect] active_runners 조회 실패: {e}")
        return

    for runner_id in runner_ids:
        pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        if not pid_str:
            try:
                _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            except Exception:
                _mr, _ms = None, None
            if _mr or _ms in MERGE_ACTIVE_STATUSES:
                logger.warning(
                    f"[reconnect] runner {runner_id} PID 없으나 머지 대기중 "
                    f"(merge_requested={bool(_mr)}, merge_status={_ms}) → _recover_pending_merge"
                )
                if not (runner_id in _stream_threads and _stream_threads[runner_id].is_alive()):
                    t = threading.Thread(
                        target=_recover_pending_merge,
                        args=(runner_id, redis_client, _ms),
                        daemon=True,
                    )
                    t.start()
            else:
                logger.info(f"[listener] runner {runner_id} PID 정보 없음 → cleanup")
                # v2 merge fallback: PID 없어도 merge 완료 여부 확인
                try:
                    from _dr_merge import detect_merged_but_not_done as _dmnd, _handle_post_merge_done as _hpmd, _pub_and_log as _pal
                    _np_detect = _dmnd(runner_id, redis_client)
                    if _np_detect:
                        logger.info(f"[reconnect] v2 merge fallback 실행 (no-pid, runner_id={runner_id})")
                        try:
                            def _np_pub(msg: str, _rid=runner_id) -> None:
                                _pal(_rid, msg, redis_client, "MERGE-FALLBACK")
                            _hpmd(_np_detect["plan_file"], runner_id, _np_pub, redis_client)
                        except Exception as _np_fb_err:
                            logger.warning(f"[reconnect] v2 merge fallback 실패 (cleanup 계속): {_np_fb_err}")
                except Exception as _np_det_err:
                    logger.debug(f"[reconnect] v2 detect 실패 (무시): {_np_det_err}")
                _cleanup_process_state(runner_id, redis_client, reason="reconnect_orphan")
            continue
        try:
            pid = int(pid_str)
        except ValueError:
            logger.warning(f"[reconnect] runner {runner_id} 잘못된 PID 값: {pid_str!r} → cleanup")
            _cleanup_process_state(runner_id, redis_client, reason="reconnect_orphan")
            continue

        # 이미 _running_processes에 등록된 경우(Redis 재연결 상황) 스킵
        if runner_id in _running_processes:
            continue

        if _is_pid_alive(pid):
            # 좀비 감지: PID alive + subprocess_heartbeat 만료 → reconnect 대신 cleanup
            _reconnect_zombie = False
            try:
                subprocess_hb = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat")
                if subprocess_hb is None:
                    # Phase 4: 레거시 runner 보호 — start_time < 600초이면 fallback
                    _rc_legacy, _rc_elapsed = _is_recent_runner_without_hb(redis_client, runner_id)
                    if _rc_legacy:
                        logger.debug(
                            f"[reconnect] runner {runner_id} heartbeat 없음 but start_time "
                            f"{_rc_elapsed:.0f}s 경과 → 레거시 보호 fallback"
                        )
                    if not _rc_legacy:
                        _reconnect_zombie = True
            except Exception:
                pass  # Redis 오류 시 기존 로직 유지
            if _reconnect_zombie:
                try:
                    from _dr_merge import _pub_and_log as _pal
                    _pal(runner_id, f"runner {runner_id} PID {pid} alive but subprocess_heartbeat 없음 → reconnect_zombie cleanup", redis_client, "ZOMBIE")
                except Exception:
                    pass
                logger.warning(f"[reconnect] zombie runner {runner_id} PID={pid} subprocess_heartbeat 없음 → cleanup")
                _cleanup_process_state(runner_id, redis_client, reason="reconnect_zombie")
            else:
                _attach_to_running_process(runner_id, pid, redis_client)
        else:
            try:
                _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            except Exception:
                _mr, _ms = None, None

            if _mr or _ms in MERGE_ACTIVE_STATUSES:
                logger.warning(
                    f"[reconnect] runner {runner_id} PID {pid} 죽었으나 머지 대기중 "
                    f"(merge_requested={bool(_mr)}, merge_status={_ms}) → cleanup 스킵"
                )
                if not (runner_id in _stream_threads and _stream_threads[runner_id].is_alive()):
                    t = threading.Thread(
                        target=_recover_pending_merge,
                        args=(runner_id, redis_client, _ms),
                        daemon=True,
                    )
                    t.start()
            else:
                logger.info(f"[listener] 재시작 감지: runner {runner_id} PID {pid} 종료됨 → cleanup")
                # v2 merge fallback: merge_requested 없어도 merge 후처리 누락 여부 확인
                try:
                    from _dr_merge import detect_merged_but_not_done as _dmnd, _handle_post_merge_done as _hpmd, _pub_and_log as _pal
                    _rc_detect = _dmnd(runner_id, redis_client)
                    if _rc_detect:
                        logger.info(f"[reconnect] v2 merge fallback 실행 (runner_id={runner_id})")
                        try:
                            def _rc_pub(msg: str, _rid=runner_id) -> None:
                                _pal(_rid, msg, redis_client, "MERGE-FALLBACK")
                            _hpmd(_rc_detect["plan_file"], runner_id, _rc_pub, redis_client)
                        except Exception as _rc_fb_err:
                            logger.warning(f"[reconnect] v2 merge fallback 실패 (cleanup 계속): {_rc_fb_err}")
                except Exception as _rc_det_err:
                    logger.debug(f"[reconnect] v2 detect 실패 (무시): {_rc_det_err}")
                _cleanup_process_state(runner_id, redis_client, reason="reconnect_orphan")

    # --- 고아 키 탐색: active_runners set에 없지만 runners:*:status 키가 존재하는 경우 ---
    try:
        for key in redis_client.scan_iter(f"{RUNNER_KEY_PREFIX}:*:status"):
            prefix = f"{RUNNER_KEY_PREFIX}:"
            suffix = ":status"
            if not (key.startswith(prefix) and key.endswith(suffix)):
                continue
            orphan_id = key[len(prefix):-len(suffix)]
            if not orphan_id:
                continue
            if orphan_id in runner_ids:
                continue  # active_runners에 이미 있음 → 위에서 처리됨
            logger.info(f"[reconnect] orphan key found (not in active_runners): {orphan_id}")
            pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:pid")
            if not pid_str:
                try:
                    _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_requested")
                    _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_status")
                except Exception:
                    _mr, _ms = None, None
                if _mr or _ms in MERGE_ACTIVE_STATUSES:
                    logger.warning(
                        f"[reconnect] orphan {orphan_id} PID 없으나 머지 대기중 "
                        f"(merge_requested={bool(_mr)}, merge_status={_ms}) → _recover_pending_merge"
                    )
                    if not (orphan_id in _stream_threads and _stream_threads[orphan_id].is_alive()):
                        t = threading.Thread(
                            target=_recover_pending_merge,
                            args=(orphan_id, redis_client, _ms),
                            daemon=True,
                        )
                        t.start()
                else:
                    logger.info(f"[reconnect] orphan {orphan_id} PID 없음 → cleanup")
                    _cleanup_process_state(orphan_id, redis_client, reason="reconnect_orphan_scan")
                continue
            try:
                pid = int(pid_str)
            except ValueError:
                logger.warning(f"[reconnect] orphan {orphan_id} 잘못된 PID: {pid_str!r} → cleanup")
                _cleanup_process_state(orphan_id, redis_client, reason="reconnect_orphan_scan")
                continue
            if _is_pid_alive(pid):
                # 좀비 감지: PID alive + subprocess_heartbeat 만료 → 재연결 대신 cleanup
                _orphan_zombie = False
                try:
                    subprocess_hb = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:subprocess_heartbeat")
                    if subprocess_hb is None:
                        _op_legacy, _op_elapsed = _is_recent_runner_without_hb(redis_client, orphan_id)
                        if _op_legacy:
                            logger.debug(
                                f"[reconnect] orphan {orphan_id} heartbeat 없음 but start_time "
                                f"{_op_elapsed:.0f}s 경과 → 레거시 보호 fallback"
                            )
                        if not _op_legacy:
                            _orphan_zombie = True
                except Exception:
                    pass
                if _orphan_zombie:
                    try:
                        from _dr_merge import _pub_and_log as _pal
                        _pal(orphan_id, f"orphan {orphan_id} PID {pid} alive but subprocess_heartbeat 없음 → reconnect_zombie cleanup", redis_client, "ZOMBIE")
                    except Exception:
                        pass
                    logger.warning(f"[reconnect] zombie orphan {orphan_id} PID={pid} subprocess_heartbeat 없음 → cleanup")
                    _cleanup_process_state(orphan_id, redis_client, reason="reconnect_zombie")
                else:
                    logger.info(f"[reconnect] orphan {orphan_id} PID {pid} 생존 → 재연결")
                    _attach_to_running_process(orphan_id, pid, redis_client)
            else:
                try:
                    _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_requested")
                    _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_status")
                except Exception:
                    _mr, _ms = None, None

                if _mr or _ms in MERGE_ACTIVE_STATUSES:
                    logger.warning(
                        f"[reconnect] orphan {orphan_id} PID {pid} 죽었으나 머지 대기중 "
                        f"(merge_requested={bool(_mr)}, merge_status={_ms}) → cleanup 스킵"
                    )
                    if not (orphan_id in _stream_threads and _stream_threads[orphan_id].is_alive()):
                        t = threading.Thread(
                            target=_recover_pending_merge,
                            args=(orphan_id, redis_client, _ms),
                            daemon=True,
                        )
                        t.start()
                else:
                    logger.info(f"[reconnect] orphan {orphan_id} PID {pid} 종료됨 → cleanup")
                    # v2 merge fallback: merge_requested 없어도 merge 후처리 누락 여부 확인
                    try:
                        from _dr_merge import detect_merged_but_not_done as _dmnd2, _handle_post_merge_done as _hpmd2, _pub_and_log as _pal2
                        _os_detect = _dmnd2(orphan_id, redis_client)
                        if _os_detect:
                            logger.info(f"[reconnect] v2 merge fallback 실행 (orphan_id={orphan_id})")
                            try:
                                def _os_pub(msg: str, _rid=orphan_id) -> None:
                                    _pal2(_rid, msg, redis_client, "MERGE-FALLBACK")
                                _hpmd2(_os_detect["plan_file"], orphan_id, _os_pub, redis_client)
                            except Exception as _os_fb_err:
                                logger.warning(f"[reconnect] v2 merge fallback 실패 (cleanup 계속): {_os_fb_err}")
                    except Exception as _os_det_err:
                        logger.debug(f"[reconnect] v2 detect 실패 (무시): {_os_det_err}")
                    _cleanup_process_state(orphan_id, redis_client, reason="reconnect_orphan_scan")
    except Exception as e:
        logger.warning(f"[reconnect] orphan scan 실패: {e}")


def _detect_orphan_workflows(redis_client: redis.Redis) -> int:
    """listener 시작 시 DB↔Redis 교차검증: running/merge_pending 워크플로우 중 active_runners에 없는 것을 failed로 전이"""
    _wf_manager = get_wf_manager()
    if _wf_manager is None:
        return 0
    cleaned = 0
    try:
        for status in ("running", "merge_pending"):
            workflows = _wf_manager.list_workflows(status=status)
            for wf in workflows:
                runner_id = wf.get("runner_id")
                if not runner_id:
                    continue
                if redis_client.sismember(ACTIVE_RUNNERS_KEY, runner_id):
                    continue
                # 머지 대기중인 러너는 failed 전이 스킵
                try:
                    _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                    _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
                except Exception:
                    _mr, _ms = None, None
                if _mr or _ms in MERGE_ACTIVE_STATUSES:
                    logger.info(
                        f"[orphan] workflow {wf['id']} slug={wf.get('slug', '?')} (runner={runner_id}) "
                        f"머지 대기중 (merge_requested={bool(_mr)}, merge_status={_ms}) → failed 전이 스킵"
                    )
                    continue
                _wf_manager.update_status(
                    wf["id"], "failed",
                    error_message="orphan: listener 재시작 시 active_runners에 없음"
                )
                logger.warning(f"[orphan] workflow {wf['id']} slug={wf.get('slug', '?')} (runner={runner_id}) → failed")
                cleaned += 1
    except Exception as e:
        logger.warning(f"[orphan] workflow 고아 탐지 실패: {e}")
    return cleaned


def _cleanup_orphan_plans(redis_client: redis.Redis) -> int:
    """plan 파일 교차검증: Workflow DB에 running 레코드 없으면 경고 + 독자 커밋 없는 worktree/branch 자동 삭제"""
    import re as _re
    import subprocess as _sp
    from plan_worktree_helpers import is_worktree_active, has_unmerged_commits
    from worktree_manager import WorktreeManager
    from plan_worktree_helpers import remove_plan_header_fields as _remove_plan_header_fields

    _wf_manager = get_wf_manager()
    if _wf_manager is None:
        return 0
    cleaned_count = 0
    scan_dirs = []
    plan_dir = PROJECT_ROOT / "docs" / "plan"
    # archive_dir 스캔 제외: 아카이브된 plan은 이미 완료 처리되어 cleanup 불필요.
    # archive 파일 수가 많아질수록(722+개) 리스너 시작 시 BRPOP 루프 진입을 수백 ms~수십 초 지연시킴.
    # 활성 plan(docs/plan/)만 검사하여 리스너 시작 시간을 단축한다.
    if plan_dir.is_dir():
        scan_dirs.append(plan_dir)
    if not scan_dirs:
        return 0
    try:
        all_workflows = _wf_manager.list_workflows()
        for scan_dir in scan_dirs:
            for plan_file in scan_dir.glob("*.md"):
                try:
                    with open(plan_file, "r", encoding="utf-8") as f:
                        head_lines = [f.readline() for _ in range(20)]
                except Exception:
                    continue
                status = ""
                for line in head_lines:
                    _m = _re.search(r">\s*상태:\s*(.+)", line or "")
                    if _m:
                        status = _m.group(1).strip()
                        break
                stage = classify_plan_stage(status)
                is_impl = status in ("구현중", "구현완료")
                if not is_impl and stage != "pre_review":
                    continue
                filename = plan_file.name
                # Workflow DB에서 이 plan에 대한 running 레코드 찾기
                matching = [
                    w for w in all_workflows
                    if w.get("plan_file") and filename in w["plan_file"] and w.get("status") == "running"
                ]
                is_orphan = False
                if not matching:
                    logger.warning(f"[orphan-plan] {filename}: 상태=구현중/완료이지만 Workflow DB에 running 레코드 없음")
                    is_orphan = True
                else:
                    for w in matching:
                        rid = w.get("runner_id")
                        if rid and not redis_client.sismember(ACTIVE_RUNNERS_KEY, rid):
                            logger.warning(f"[orphan-plan] {filename}: runner {rid}가 active_runners에 없음")
                            is_orphan = True

                # orphan이면 worktree/branch 정리 시도
                if is_orphan:
                    if stage == "pre_review":
                        logger.info(
                            f"[resumable_pre_review] {filename}: 상태={status} orphan 감지 — 자동 삭제 스킵"
                        )
                        continue
                    try:
                        active, branch, wt_abs = is_worktree_active(str(plan_file), PROJECT_ROOT)
                        if active and branch:
                            if has_unmerged_commits(branch, PROJECT_ROOT):
                                r = _sp.run(
                                    ["git", "log", f"main..{branch}", "--oneline"],
                                    capture_output=True, text=True, cwd=str(PROJECT_ROOT)
                                )
                                n = len(r.stdout.strip().splitlines()) if r.stdout.strip() else "?"
                                logger.warning(
                                    f"[orphan-plan] {filename}: 독자 커밋 {n}개 존재 — 수동 확인 필요 (branch={branch})"
                                )
                            else:
                                # 독자 커밋 없음 → 안전하게 정리
                                try:
                                    _orphan_base = get_plan_git_root(str(plan_file)) / ".worktrees"
                                    WorktreeManager.remove("", _orphan_base, plan_file=str(plan_file))
                                    _remove_plan_header_fields(str(plan_file))
                                    logger.info(f"[orphan-plan] {filename}: worktree/branch 정리 완료 (branch={branch})")
                                    cleaned_count += 1
                                except Exception as rm_err:
                                    logger.warning(f"[orphan-plan] {filename}: 정리 실패 — {rm_err}")
                    except Exception as check_err:
                        logger.warning(f"[orphan-plan] {filename}: worktree 확인 중 오류 — {check_err}")
    except Exception as e:
        logger.warning(f"[orphan-plan] plan 고아 탐지 실패: {e}")
    return cleaned_count
