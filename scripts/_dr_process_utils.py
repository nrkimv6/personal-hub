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
from _dr_runner_predicates import (
    _is_user_visible_trigger,
    _is_pre_review_stopped_runner,
    _is_pid_alive,
    _parse_start_elapsed_seconds,
    _is_recent_runner_without_hb,
)

logger = logging.getLogger(__name__)




def _try_v2_merge_fallback(runner_id: str, redis_client: redis.Redis, reason_tag: str) -> bool:
    """v2 merge fallback 공통 헬퍼 — detect → handle 패턴.

    detect_merged_but_not_done이 양성이면 _handle_post_merge_done을 실행하고 True 반환.
    detect 실패, 양성 없음, handle 실패 시 False 반환 (호출자의 cleanup은 계속 진행).
    """
    try:
        from _dr_merge import detect_merged_but_not_done as _dmnd, _handle_post_merge_done as _hpmd, _pub_and_log as _pal
        detect_result = _dmnd(runner_id, redis_client)
        if detect_result:
            logger.info(f"[{reason_tag}] v2 merge fallback 실행 (runner_id={runner_id})")
            try:
                def _pub(msg: str, _rid=runner_id) -> None:
                    _pal(_rid, msg, redis_client, "MERGE-FALLBACK")
                _hpmd(detect_result["plan_file"], runner_id, _pub, redis_client)
            except Exception as _handle_err:
                logger.warning(f"[{reason_tag}] v2 merge fallback 실패 (cleanup 계속): {_handle_err}")
            return False
        return False
    except Exception as _det_err:
        logger.debug(f"[{reason_tag}] v2 detect 실패 (무시): {_det_err}")
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

    # cleanup 진행 중 표시 — 재실행 attach 감지 시 이 플래그를 확인함 (TTL 30초)
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress", "1", ex=30)
    except Exception:
        pass

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
        # 보존 계약 (runner_state.py _PERSIST_SUFFIXES와 동일): dismiss 전까지 TTL 없이 영구 보존
        _PERSIST_SUFFIXES_LOCAL = frozenset({"plan_file", "branch", "trigger"})
        for suffix in RUNNER_KEY_SUFFIXES:
            if suffix in _PERSIST_SUFFIXES_LOCAL:
                continue  # dismiss 전까지 영구 보존 (종료 후에도 탭 표시 + visible_only 판별용)
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            redis_client.expire(key, RECENT_RUNNERS_TTL)
        redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
        _trigger_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")

        # [fix] recent-meta: cleanup 후에도 trigger/accepted_at/started_at 조회 가능하도록 보존 (키 삭제 전에 수행)
        try:
            import json as _json
            from _dr_constants import RECENT_META_TTL
            _meta = {}
            # trigger는 이미 _trigger_val로 조회했으므로 재사용
            if _trigger_val is not None:
                _meta["trigger"] = _trigger_val
            # 나머지 필드 조회
            for _field in ("accepted_at", "started_at"):
                _val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:{_field}")
                if _val is not None:
                    _meta[_field] = _val
            if _meta:
                redis_client.setex(
                    f"plan-runner:recent-meta:{runner_id}",
                    RECENT_META_TTL,
                    _json.dumps(_meta, ensure_ascii=False),
                )
                logger.debug(f"[cleanup] recent-meta 저장 (runner_id={runner_id}, fields={list(_meta.keys())})")
        except Exception as _rmeta_err:
            logger.warning(f"[cleanup] recent-meta 저장 실패 (무시, runner_id={runner_id}): {_rmeta_err}")

        # invisible runner(trigger 미설정/비사용자)는 RECENT에 등록하지 않고 키 즉시 삭제
        if _trigger_val in ("user", "user:all"):
            redis_client.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
            logger.info(f"[cleanup] RECENT 등록 완료: {runner_id}")
        else:
            for _suffix in RUNNER_KEY_SUFFIXES:
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{_suffix}")
            logger.debug(f"[cleanup] invisible runner — RECENT 스킵, 키 삭제: {runner_id} (trigger={_trigger_val!r})")
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
        from plan_worktree_helpers import has_unmerged_commits as _has_unmerged_commits

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

        # 미머지 커밋 보호: 브랜치에 독자 커밋이 있으면 삭제 금지
        if not _preserve_worktree:
            _branch = (
                f"plan/{Path(plan_file_val).stem}" if plan_file_val
                else f"runner/{runner_id}"
            )
            if _has_unmerged_commits(_branch, get_plan_git_root(plan_file_val) if plan_file_val else WORKTREE_BASE_DIR.parent):
                _preserve_worktree = True
                logger.warning(
                    f"[cleanup] 워크트리 보존 (미머지 커밋 존재): runner={runner_id}, branch={_branch}"
                )
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

    # cleanup 완료 — 진행 중 플래그 제거
    try:
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress")
    except Exception:
        pass


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


def _tail_log_and_publish(runner_id: str, log_path: str, redis_client: redis.Redis, replay_from_start: bool = False):
    """로그 파일을 읽어 Redis log channel에 publish하는 스레드.

    재연결된 runner에서 pipe가 없을 때 파일 tailing으로 대체 스트리밍한다.
    replay_from_start=True이면 파일 처음부터 읽어 기존 로그를 전부 재발행한다.
    PID 종료 + 더 이상 새 줄 없음 → 스레드 종료.
    """
    _running_processes = get_running_processes()
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    frame_buffer = MultilineFrameBuffer(max_chars=8192)
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # replay_from_start=False일 때만 파일 끝으로 이동 (기존 내용 재발행 안 함)
            if not replay_from_start:
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
            _try_v2_merge_fallback(runner_id, redis_client, "monitor_pid")
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
        _try_v2_merge_fallback(runner_id, redis_client, "attach_no_log")
        _cleanup_process_state(runner_id, redis_client, reason="no_log_file")
        return

    # _DummyProcess 등록 (기존 heartbeat 루프의 proc.poll() 호환)
    dummy = _DummyProcess(pid)
    _running_processes[runner_id] = dummy
    _running_log_files[runner_id] = Path(log_file_path)

    # tailing 스레드 시작 — replay_from_start=True: 리스너 재시작 시 기존 로그 전체 재발행
    tail_thread = threading.Thread(
        target=_tail_log_and_publish,
        args=(runner_id, log_file_path, redis_client, True),
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


def _process_runner_entry(
    runner_id: str,
    pid_str: Optional[str],
    redis_client: redis.Redis,
    *,
    is_orphan: bool = False,
) -> None:
    """active runner 또는 orphan 키 1개의 reconnect 처리 공통 로직.

    is_orphan=False: active_runners set 소속 (cleanup reason="reconnect_orphan")
    is_orphan=True:  orphan scan 소속 (cleanup reason="reconnect_orphan_scan", no-pid merge fallback 없음)
    """
    _running_processes = get_running_processes()
    _stream_threads = get_stream_threads()
    cleanup_reason = "reconnect_orphan_scan" if is_orphan else "reconnect_orphan"
    label = "orphan" if is_orphan else "runner"
    dead_pid_tag = "reconnect_orphan_dead_pid" if is_orphan else "reconnect_dead_pid"

    if not pid_str:
        try:
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        except Exception:
            _mr, _ms = None, None
        if _mr or _ms in MERGE_ACTIVE_STATUSES:
            logger.warning(
                f"[reconnect] {label} {runner_id} PID 없으나 머지 대기중 "
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
            logger.info(f"[reconnect] {label} {runner_id} PID 없음 → cleanup")
            if not is_orphan:
                # active loop에서만 merge fallback 적용 (orphan no-pid는 기존 동작 유지)
                _try_v2_merge_fallback(runner_id, redis_client, "reconnect_no_pid")
            _cleanup_process_state(runner_id, redis_client, reason=cleanup_reason)
        return

    try:
        pid = int(pid_str)
    except ValueError:
        logger.warning(f"[reconnect] {label} {runner_id} 잘못된 PID: {pid_str!r} → cleanup")
        _cleanup_process_state(runner_id, redis_client, reason=cleanup_reason)
        return

    # active runner가 이미 _running_processes에 등록된 경우(Redis 재연결 상황) 스킵
    if not is_orphan and runner_id in _running_processes:
        return

    if _is_pid_alive(pid):
        # 좀비 감지: PID alive + subprocess_heartbeat 만료 → reconnect 대신 cleanup
        _is_zombie = False
        try:
            subprocess_hb = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat")
            if subprocess_hb is None:
                _legacy, _elapsed = _is_recent_runner_without_hb(redis_client, runner_id)
                if _legacy:
                    logger.debug(
                        f"[reconnect] {label} {runner_id} heartbeat 없음 but start_time "
                        f"{_elapsed:.0f}s 경과 → 레거시 보호 fallback"
                    )
                if not _legacy:
                    _is_zombie = True
        except Exception:
            pass
        if _is_zombie:
            try:
                from _dr_merge import _pub_and_log as _pal
                _pal(runner_id, f"{label} {runner_id} PID {pid} alive but subprocess_heartbeat 없음 → reconnect_zombie cleanup", redis_client, "ZOMBIE")
            except Exception:
                pass
            logger.warning(f"[reconnect] zombie {label} {runner_id} PID={pid} subprocess_heartbeat 없음 → cleanup")
            _cleanup_process_state(runner_id, redis_client, reason="reconnect_zombie")
        else:
            if is_orphan:
                logger.info(f"[reconnect] {label} {runner_id} PID {pid} 생존 → 재연결")
            _attach_to_running_process(runner_id, pid, redis_client)
    else:
        try:
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        except Exception:
            _mr, _ms = None, None

        if _mr or _ms in MERGE_ACTIVE_STATUSES:
            logger.warning(
                f"[reconnect] {label} {runner_id} PID {pid} 죽었으나 머지 대기중 "
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
            logger.info(f"[reconnect] {label} {runner_id} PID {pid} 종료됨 → cleanup")
            _try_v2_merge_fallback(runner_id, redis_client, dead_pid_tag)
            _cleanup_process_state(runner_id, redis_client, reason=cleanup_reason)


def _reconnect_surviving_runners(redis_client: redis.Redis):
    """listener 시작(또는 재시작) 시 한 번 호출."""
    _running_processes = get_running_processes()
    try:
        runner_ids = redis_client.smembers(ACTIVE_RUNNERS_KEY)
    except Exception as e:
        logger.warning(f"[reconnect] active_runners 조회 실패: {e}")
        return

    for runner_id in runner_ids:
        # stopped+user/user:all: dismiss 전까지 재정리하지 않는다
        _r_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        if _r_status == "stopped":
            _r_trigger = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")
            if _is_user_visible_trigger(_r_trigger, runner_id):
                logger.info(
                    f"[reconnect] runner {runner_id} stopped+user trigger → cleanup 스킵 "
                    f"(trigger={_r_trigger}, 미확인 종료 로그 보존)"
                )
                continue
        pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        _process_runner_entry(runner_id, pid_str, redis_client, is_orphan=False)

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
            # stopped+user/user:all orphan: dismiss 전까지 재정리하지 않는다
            _o_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:status")
            if _o_status == "stopped":
                _o_trigger = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:trigger")
                if _is_user_visible_trigger(_o_trigger, orphan_id):
                    logger.info(
                        f"[reconnect] orphan {orphan_id} stopped+user trigger → cleanup 스킵 "
                        f"(trigger={_o_trigger}, 미확인 종료 로그 보존)"
                    )
                    continue
            logger.info(f"[reconnect] orphan key found (not in active_runners): {orphan_id}")
            pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:pid")
            _process_runner_entry(orphan_id, pid_str, redis_client, is_orphan=True)
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
