"""_dr_merge.py — dev-runner merge 실행 헬퍼 모듈"""
import functools
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote as _url_quote

import requests
import redis

from _dr_constants import (
    RUNNER_KEY_PREFIX, PLAN_FILE_ALL, _LEGACY_ALL, LOG_CHANNEL_PREFIX,
    PLAN_RUNNER_PYTHON, PLAN_RUNNER_MODULE_PATH, get_redis_db, get_admin_api_base,
)
from _dr_subprocess import _get_fix_engine, _launch_conflict_resolver_process, _launch_auto_impl_post_merge_process, _launch_general_merge_resolver_process, PROJECT_ROOT

logger = logging.getLogger(__name__)


def is_done_completed(runner_id: str, redis_client: redis.Redis) -> bool:
    """plan-runner가 이미 done을 완료했는지 확인 (이중 done 방지).

    plan-runner loop의 auto-done 성공 후 설정되는 플래그를 확인한다.
    (fix: v2-pipeline-transition-safety Phase 2)
    """
    try:
        val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_completed")
        return val == "1"
    except Exception:
        return False


def detect_merged_but_not_done(runner_id: str, redis_client: redis.Redis) -> Optional[dict]:
    """v2 merge 성공 후 후처리(done/archive/cleanup)가 누락된 runner를 감지한다.

    v2 파이프라인에서 handle_merge_stage()가 merge 성공 후 plan-runner 프로세스가 죽으면
    dev-runner가 후처리를 놓치는 버그의 fallback 감지 함수.

    감지 경로:
    1. Redis merge_status == "merged" (v2에서 세팅 시)
    2. git log에서 branch merge commit이 main에 존재
    3. plan 파일이 docs/plan/에 잔존하고 상태가 머지대기/통합테스트중

    Args:
        runner_id: plan-runner ID
        redis_client: Redis 클라이언트

    Returns:
        감지 시 {"plan_file": str, "branch": str}, 미감지 시 None
    """
    from plan_worktree_helpers import is_plan_archived

    # done_completed 플래그 확인 — plan-runner가 이미 done 완료 시 fallback 불필요
    # (fix: v2-pipeline-transition-safety Phase 2)
    if is_done_completed(runner_id, redis_client):
        logger.debug(f"[detect_merged] runner {runner_id}: done_completed=1 → 스킵")
        return None

    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        branch = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
    except Exception as e:
        logger.debug(f"[detect_merged] runner {runner_id}: Redis 조회 실패 (무시) — {e}")
        return None

    # plan_file 없음 또는 ALL 모드이면 스킵
    if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
        logger.debug(f"[detect_merged] runner {runner_id}: plan_file 없음 또는 ALL → 스킵")
        return None

    # 이미 archive됐으면 중복 방지
    try:
        if is_plan_archived(plan_file):
            logger.debug(f"[detect_merged] runner {runner_id}: plan이 이미 archive됨 → 스킵")
            return None
    except Exception:
        pass

    # plan 파일이 존재하고 상태가 머지대기/통합테스트중인지 확인
    plan_path = Path(plan_file)
    if not plan_path.exists():
        logger.info(f"[detect_merged] runner {runner_id}: plan 이미 archive됨 — fallback 불필요")
        return None

    try:
        head = plan_path.read_text(encoding="utf-8", errors="replace")[:2000]
        if not re.search(r">\s*상태:\s*(머지대기|통합테스트중)", head):
            logger.debug(f"[detect_merged] runner {runner_id}: plan 상태가 머지대기/통합테스트중 아님 → 스킵")
            return None
    except Exception as e:
        logger.debug(f"[detect_merged] runner {runner_id}: plan 상태 확인 실패 (무시) — {e}")
        return None

    # 감지 경로 1: Redis merge_status == "merged"
    redis_merged = False
    try:
        ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        if ms == "merged":
            redis_merged = True
            logger.info(f"[detect_merged] runner {runner_id}: Redis merge_status=merged 감지")
    except Exception:
        pass

    # 감지 경로 2: git log에서 branch merge commit이 main에 존재
    git_merged = False
    if branch:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--merges",
                 f"--grep=Merge branch '{branch}'", "main", "-1"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                git_merged = True
                logger.info(f"[detect_merged] runner {runner_id}: git log merge commit 감지 (branch={branch})")
            else:
                # grep 패턴 대안: --grep="plan/{branch-tail}"
                branch_tail = branch.split("/")[-1] if "/" in branch else branch
                result2 = subprocess.run(
                    ["git", "log", "--oneline", "--merges",
                     f"--grep={branch_tail}", "main", "-3"],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
                )
                if result2.returncode == 0 and result2.stdout.strip():
                    git_merged = True
                    logger.info(
                        f"[detect_merged] runner {runner_id}: git log merge commit 감지 (branch_tail={branch_tail})"
                    )
        except Exception as e:
            logger.debug(f"[detect_merged] runner {runner_id}: git log 확인 실패 (무시) — {e}")

    if redis_merged or git_merged:
        logger.info(
            f"[detect_merged] runner {runner_id}: merge 후 후처리 누락 감지 "
            f"(redis_merged={redis_merged}, git_merged={git_merged}, plan={plan_file})"
        )
        return {"plan_file": plan_file, "branch": branch or ""}

    logger.debug(
        f"[detect_merged] runner {runner_id}: merge 감지 안됨 "
        f"(redis_merged={redis_merged}, git_merged={git_merged})"
    )
    return None


def _pub_and_log(runner_id: str, msg: str, redis_client: redis.Redis, tag: str = "MERGE") -> None:
    """Pub/Sub + Redis list + stream_log_path 파일에 통합 기록하는 헬퍼.

    Args:
        runner_id: plan-runner ID
        msg: 기록할 메시지 (태그 미포함)
        redis_client: Redis 클라이언트
        tag: 로그 태그 (기본값: MERGE)
    """
    tagged = f"[{tag}] {msg}"
    logger.info(tagged)
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    log_list_key = f"plan-runner:logs:list:{runner_id}"
    try:
        redis_client.publish(log_channel, tagged)
    except Exception:
        pass
    try:
        redis_client.rpush(log_list_key, tagged)
        redis_client.expire(log_list_key, 86400)
    except Exception:
        pass
    # stream_log_path → fallback: log_file_path 파일에 append
    try:
        log_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
        if not log_path_str:
            log_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
        if log_path_str:
            log_path = Path(log_path_str)
            if log_path.exists():
                with open(str(log_path), "a", encoding="utf-8") as _f:
                    _f.write(tagged + "\n")
    except Exception as _e:
        logger.debug(f"[_pub_and_log] 파일 기록 실패 (무시): {_e}")


def _handle_merge_success(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge") -> dict:
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
    except Exception:
        pass
    pub_fn("merge 성공 (exit_code=0)")
    result = {"success": True, "message": "merged", "merge_status": "merged", "action": action_name}
    _handle_post_merge_done(plan_file, runner_id, pub_fn, redis_client)
    return result


def _handle_test_failed(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge", _test_fix_attempt: int = 0) -> dict:
    if _test_fix_attempt >= 2 or not plan_file:
        if _test_fix_attempt >= 2:
            pub_fn(f"auto-impl-post-merge 재시도 한도(2회) 초과 — test_failed 상태 유지")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "test_failed")
        except Exception:
            pass
        pub_fn(f"post-merge 테스트 실패 (exit_code=2)")
        return {"success": False, "message": "test_failed", "merge_status": "test_failed", "action": action_name}
    else:
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "fixing")
        except Exception:
            pass
        pub_fn("post-merge 테스트 실패 — auto-impl-post-merge 자동 실행")
        engine = _get_fix_engine(redis_client, runner_id)
        _fix_result = _launch_auto_impl_post_merge_process(
            runner_id=runner_id,
            plan_file=plan_file,
            redis_client=redis_client,
            pub_fn=pub_fn,
            engine=engine,
        )
        if _fix_result["success"]:
            pub_fn("auto-impl-post-merge 성공 — merge 완료")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
            except Exception:
                pass
            result = {"success": True, "message": "test fixed and merged", "merge_status": "merged", "action": action_name}
            _handle_post_merge_done(plan_file, runner_id, pub_fn, redis_client)
            return result
        else:
            pub_fn(f"auto-impl-post-merge 실패: {_fix_result['message']}")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "test_failed")
            except Exception:
                pass
            return {"success": False, "message": "test_failed", "merge_status": "test_failed", "action": action_name}


def _handle_conflict(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge", branch_str: str = "") -> dict:
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "resolving")
    except Exception:
        pass
    pub_fn(f"merge 충돌 (exit_code=3) — conflict resolver 자동 실행")
    engine = _get_fix_engine(redis_client, runner_id)
    worktree_path_str = ""
    try:
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path") or ""
    except Exception:
        pass
    _resolve_result = _launch_conflict_resolver_process(
        runner_id=runner_id,
        branch=branch_str or "",
        worktree_path=Path(worktree_path_str) if worktree_path_str else PROJECT_ROOT / ".worktrees" / runner_id,
        redis_client=redis_client,
        pub_fn=pub_fn,
        engine=engine,
        needs_remerge=True,
    )
    if _resolve_result["success"]:
        pub_fn("conflict resolver 성공 — merge 완료")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
        except Exception:
            pass
        result = {"success": True, "message": "conflict resolved", "merge_status": "merged", "action": action_name}
        _handle_post_merge_done(plan_file, runner_id, pub_fn, redis_client)
        return result
    else:
        pub_fn(f"conflict resolver 실패: {_resolve_result['message']}")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict")
        except Exception:
            pass
        return {"success": False, "message": "conflict", "conflict": True, "merge_status": "conflict", "action": action_name}


def _handle_general_error(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge", exit_code: int = 1, error_msg: str = "", branch_str: str = "") -> dict:
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
    except Exception:
        pass
    pub_fn(f"merge 실패 (exit_code={exit_code}) — general resolver 실행")
    engine = _get_fix_engine(redis_client, runner_id)
    _general_result = _launch_general_merge_resolver_process(
        runner_id=runner_id,
        branch=branch_str or "",
        error_msg=f"exit_code={exit_code}",
        redis_client=redis_client,
        pub_fn=pub_fn,
        engine=engine,
    )
    if _general_result["success"]:
        pub_fn("general resolver 성공 — merge 완료")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
        except Exception:
            pass
        return {"success": True, "message": "general resolver merged", "merge_status": "merged", "action": action_name}
    else:
        pub_fn(f"general resolver 실패: {_general_result['message']}")
        return {"success": False, "message": f"exit_code={exit_code}", "merge_status": "error", "action": action_name}


# dispatch table: exit_code → handler
# handler signature: (runner_id, redis_client, plan_file, pub_fn, action_name, **kwargs) -> dict
_EXIT_CODE_HANDLERS = {
    0: _handle_merge_success,
    2: _handle_test_failed,
    3: _handle_conflict,
}


def _execute_merge_with_lock(runner_id: str, redis_client: redis.Redis, action_name: str = "inline-merge", _test_fix_attempt: int = 0) -> dict:
    """lock acquire → plan-runner post-merge subprocess → exit code 분기 → merge-results push 공통 헬퍼.

    _do_inline_merge, _do_retry_merge에서 공유하는 lock+subprocess+결과 패턴을 통합한다.

    exit code 규약: 0=merged, 1=error, 2=test_failed, 3=conflict

    Args:
        _test_fix_attempt: exit_code=2 자동 복구 시도 횟수 (무한루프 방지, 최대 2회)

    Returns:
        dict: {"success": bool, "message": str, "merge_status": str, "action": action_name}
    """
    from merge_queue import acquire_merge_turn, release_merge_turn, _get_repo_id

    def _pub(msg: str) -> None:
        _pub_and_log(runner_id, msg, redis_client, "MERGE")

    branch_str = None
    plan_file = None
    lock_acquired = False
    result = {"success": False, "message": "unknown error", "merge_status": "error", "action": action_name}

    try:
        # 1. merge_status = "queued" + lock 대기
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")
        except Exception:
            pass
        _pub("merge lock 대기 중...")

        lock_acquired = acquire_merge_turn(redis_client, runner_id, repo_id=_get_repo_id(PROJECT_ROOT), timeout=600)
        if not lock_acquired:
            _pub("merge lock 획득 실패 (timeout) — merge 중단")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
            except Exception:
                pass
            result["message"] = "merge lock 획득 실패 (timeout)"
            result["merge_status"] = "error"
            return result

        try:
            branch_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
            plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
            if plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
                plan_file = None
        except Exception:
            pass

        # 2. lock 획득 후 merge_status = "merging"
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merging")
        except Exception:
            pass
        _pub("merge lock 획득 완료 — plan-runner post-merge 실행 중...")

        # 3. subprocess로 plan-runner post-merge 호출
        proc = subprocess.run(
            [str(PLAN_RUNNER_PYTHON), "-m", "plan_runner", "post-merge",
             "--runner-id", runner_id, "--redis-db", str(get_redis_db())],
            cwd=str(PLAN_RUNNER_MODULE_PATH),
        )
        exit_code = proc.returncode

        # 4. exit code dispatch table 분기
        handler = _EXIT_CODE_HANDLERS.get(exit_code)
        if handler is None:
            # else branch: general error handler
            result = _handle_general_error(
                runner_id, redis_client, plan_file, _pub,
                action_name=action_name, exit_code=exit_code,
                error_msg=f"exit_code={exit_code}", branch_str=branch_str or "",
            )
        elif exit_code == 2:
            result = _handle_test_failed(
                runner_id, redis_client, plan_file, _pub,
                action_name=action_name, _test_fix_attempt=_test_fix_attempt,
            )
        elif exit_code == 3:
            result = _handle_conflict(
                runner_id, redis_client, plan_file, _pub,
                action_name=action_name, branch_str=branch_str or "",
            )
        else:
            result = handler(runner_id, redis_client, plan_file, _pub, action_name)

    except Exception as e:
        logger.error(f"[_execute_merge_with_lock] 예외 발생 (runner_id={runner_id}, action={action_name}): {e}")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
        except Exception:
            pass
        result = {"success": False, "message": str(e), "merge_status": "error", "action": action_name}

    finally:
        if lock_acquired:
            try:
                release_merge_turn(redis_client, runner_id, repo_id=_get_repo_id(PROJECT_ROOT))
            except Exception:
                pass
        # merge-results Redis list에 결과 push (merge history API 연동)
        try:
            _merge_status_final = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status") or "unknown"
            _is_success = result.get("success", False)
            redis_client.lpush("plan-runner:merge-results", json.dumps({
                "runner_id": runner_id,
                "branch": branch_str,
                "plan_file": plan_file,
                "timestamp": datetime.now().isoformat(),
                "status": "done" if _is_success else "failed",
                "success": _is_success,
                "message": result.get("message", f"merge_status={_merge_status_final}"),
            }, ensure_ascii=False))
            redis_client.expire("plan-runner:merge-results", 86400 * 7)
        except Exception as _mr_err:
            logger.debug(f"[_execute_merge_with_lock] merge-results push 실패 (무시): {_mr_err}")

    return result


def _handle_post_merge_done(plan_file: str, runner_id: str, pub_fn, redis_client) -> None:
    """머지 성공 후 done flow를 실행한다.

    plan_file에서 branch/worktree 헤더 필드를 제거하고,
    완료율을 체크하여 100%이면 done API를 호출하고,
    미완료 태스크가 있으면 main 추가 사이클을 예약한다.

    Args:
        plan_file: plan 파일 절대 경로 (None 또는 ALL 모드이면 스킵)
        runner_id: 로깅용 runner ID
        pub_fn: 로그 publish 함수 (msg: str) -> None
        redis_client: Redis 클라이언트
    """
    from plan_worktree_helpers import (
        remove_plan_header_fields as _remove_plan_header_fields,
        get_plan_completion as _get_plan_completion,
        is_fix_plan as _is_fix_plan,
        has_phase_r as _has_phase_r,
        has_undefended_paths as _has_undefended_paths,
    )
    if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
        pub_fn("plan_file 없음(--all 모드) — done 스킵")
        return

    # plan 파일 존재 확인 — 이미 archive됨 (fix: v2-pipeline-transition-safety Phase 2)
    if not Path(plan_file).exists():
        pub_fn("plan 이미 처리됨 (파일 없음) — done 스킵")
        logger.info(f"[_handle_post_merge_done] plan 파일 없음, 이미 처리된 것으로 판단: {plan_file}")
        return

    # plan 상태 확인 — "완료"이면 이미 done 처리됨
    try:
        _head = Path(plan_file).read_text(encoding="utf-8", errors="replace")[:2000]
        if re.search(r">\s*상태:\s*완료", _head):
            pub_fn("plan 이미 완료 상태 — done 스킵")
            return
    except Exception:
        pass

    # plan 헤더에서 branch/worktree 필드 제거 — 잔존 시 auto-done 에이전트가 /done 2.5단계에서 차단됨
    _remove_plan_header_fields(plan_file)

    # fallback 경로: plan 상태가 머지대기/통합테스트중이면 구현완료로 전이
    # (v2 handle_merge_stage에서 run_loop 상태 전이가 실행 안 됐을 때 보완)
    try:
        plan_text = Path(plan_file).read_text(encoding="utf-8", errors="replace")
        if re.search(r">\s*상태:\s*(머지대기|통합테스트중)", plan_text[:2000]):
            # fix plan 사전 검증: Phase R 부재/미방어 확인 (branch/worktree는 merge 직후이므로 면제)
            if _is_fix_plan(plan_file, plan_text):
                if not _has_phase_r(plan_text):
                    pub_fn("fix plan 사전 검증 실패 — 구현완료 전이 보류: Phase R 섹션 필수")
                    logger.warning(f"[_handle_post_merge_done] fix plan Phase R 부재, 구현완료 전이 스킵: {plan_file}")
                elif _has_undefended_paths(plan_text):
                    pub_fn("fix plan 사전 검증 실패 — 구현완료 전이 보류: Phase R에 미방어 경로 잔존")
                    logger.warning(f"[_handle_post_merge_done] fix plan Phase R 미방어 잔존, 구현완료 전이 스킵: {plan_file}")
                else:
                    updated = re.sub(
                        r"(>\s*상태:\s*)(머지대기|통합테스트중)",
                        r"\g<1>구현완료",
                        plan_text[:2000],
                    ) + plan_text[2000:]
                    Path(plan_file).write_text(updated, encoding="utf-8")
                    pub_fn("plan 상태 → 구현완료 전이 (fallback)")
                    logger.info(f"[_handle_post_merge_done] plan 상태 구현완료 전이: {plan_file}")
            else:
                updated = re.sub(
                    r"(>\s*상태:\s*)(머지대기|통합테스트중)",
                    r"\g<1>구현완료",
                    plan_text[:2000],
                ) + plan_text[2000:]
                Path(plan_file).write_text(updated, encoding="utf-8")
                pub_fn("plan 상태 → 구현완료 전이 (fallback)")
                logger.info(f"[_handle_post_merge_done] plan 상태 구현완료 전이: {plan_file}")
    except Exception as _st_err:
        logger.debug(f"[_handle_post_merge_done] plan 상태 전이 실패 (무시): {_st_err}")

    # 자동 done 분기: 완료율 체크 → done API 호출 or main 추가 사이클 예약
    done_count, total_count = _get_plan_completion(plan_file)
    if total_count > 0 and done_count == total_count:
        pub_fn(f"완료율 100% ({done_count}/{total_count}) — 자동 done 처리 시작")
        _call_done_api(plan_file, runner_id, pub_fn)
    else:
        pub_fn(f"미완료 태스크 있음 ({done_count}/{total_count}) — main 추가 사이클 예약")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge", "1")
        except Exception:
            pass


def _call_done_api(plan_file: str, runner_id: str, pub_fn) -> bool:
    """plan_file 경로에 대해 Admin API /plans/{path}/done 를 호출한다.

    Args:
        plan_file: plan 파일 절대 경로
        runner_id: 로깅용 runner ID
        pub_fn: 로그 publish 함수 (msg: str) -> None

    Returns:
        True if done API returned 200, False otherwise
    """
    try:
        encoded = _url_quote(plan_file, safe="")
        url = f"{get_admin_api_base()}/plans/{encoded}/done"
        resp = requests.post(url, timeout=60)
        if resp.status_code == 200:
            return True
        pub_fn(f"done API 실패 (status={resp.status_code}) — 수동 처리 필요")
        logger.warning(f"[_call_done_api] done API 실패: runner={runner_id}, status={resp.status_code}, url={url}")
        return False
    except requests.exceptions.RequestException as e:
        pub_fn(f"done API 연결 실패: {e} — 수동 처리 필요")
        logger.warning(f"[_call_done_api] done API 연결 실패: runner={runner_id}, error={e}")
        return False
