"""
cleanup_test_runners.py - plan-runner:runners:* 중 PID가 죽은 키를 스캔·삭제하는 CLI 유틸리티

사용법:
  python scripts/cleanup_test_runners.py [--dry-run|--force] [--test-only] [--db <n>]

옵션:
  --dry-run    삭제 대상만 출력, 실제 삭제 없음 (기본값)
  --force      실제 삭제 실행
  --test-only  branch 값에 'test_' 포함된 것만 대상
  --db <n>     대상 Redis DB 번호 (기본: 0)
"""

import argparse
import os
import sys

import redis


REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
KEY_PREFIX = "plan-runner:runners:"
ACTIVE_SET_KEY = "plan-runner:active_runners"


def _is_pid_alive(pid: int) -> bool:
    """PID가 살아있는지 확인 (Windows / Unix 모두 지원)."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if handle == 0:
                return False
            exit_code = ctypes.c_ulong(0)
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            STILL_ACTIVE = 259
            return exit_code.value == STILL_ACTIVE
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


def scan_dead_runners(
    r: redis.Redis,
    test_only: bool = False,
) -> list:
    """
    plan-runner:runners:*:pid 키를 스캔하여 PID가 죽은 runner 정보를 반환한다.

    반환값:
        [{"runner_id": ..., "pid": ..., "branch": ..., "status": ..., "keys": [...]}]
    """
    dead = []
    pid_pattern = f"{KEY_PREFIX}*:pid"

    for key in r.scan_iter(pid_pattern):
        # key 예: plan-runner:runners:<runner_id>:pid
        parts = key.split(":")
        if len(parts) < 4:
            continue
        runner_id = parts[2]

        pid_val = r.get(key)
        try:
            pid = int(pid_val) if pid_val else 0
        except (ValueError, TypeError):
            pid = 0

        # branch 필터
        branch_key = f"{KEY_PREFIX}{runner_id}:branch"
        branch = r.get(branch_key) or ""
        if test_only and "test_" not in branch:
            continue

        # PID alive 체크
        if pid > 0 and _is_pid_alive(pid):
            continue  # 살아있는 프로세스 - 건드리지 않음

        # 관련 키 목록 수집
        status_key = f"{KEY_PREFIX}{runner_id}:status"
        plan_file_key = f"{KEY_PREFIX}{runner_id}:plan_file"
        start_time_key = f"{KEY_PREFIX}{runner_id}:start_time"
        related_keys = []
        for k in [key, status_key, branch_key, plan_file_key, start_time_key]:
            if r.exists(k):
                related_keys.append(k)

        status = r.get(status_key) or ""

        dead.append(
            {
                "runner_id": runner_id,
                "pid": pid,
                "branch": branch,
                "status": status,
                "keys": related_keys,
            }
        )

    return dead


def scan_incomplete_runners(r: redis.Redis, test_only: bool = False) -> list:
    """
    PID 키는 없지만 status 키가 남아있는 불완전 runner를 반환한다.
    """
    seen = set()
    for pid_key in r.scan_iter(f"{KEY_PREFIX}*:pid"):
        parts = pid_key.split(":")
        if len(parts) >= 3:
            seen.add(parts[2])

    incomplete = []
    for status_key in r.scan_iter(f"{KEY_PREFIX}*:status"):
        parts = status_key.split(":")
        if len(parts) < 3:
            continue
        runner_id = parts[2]
        if runner_id in seen:
            continue

        branch_key = f"{KEY_PREFIX}{runner_id}:branch"
        branch = r.get(branch_key) or ""
        status = r.get(status_key) or ""

        if test_only and "test_" not in branch:
            continue

        all_keys = []
        for field in ["status", "pid", "plan_file", "start_time", "branch"]:
            k = f"{KEY_PREFIX}{runner_id}:{field}"
            if r.exists(k):
                all_keys.append(k)

        incomplete.append({
            "runner_id": runner_id,
            "pid": None,
            "branch": branch,
            "status": status,
            "keys": all_keys,
        })

    return incomplete


def print_table(entries: list) -> None:
    """결과를 테이블 형태로 출력한다."""
    if not entries:
        print("(대상 없음)")
        return

    col_id = max(len(e["runner_id"]) for e in entries)
    col_pid = max(len(str(e["pid"])) for e in entries)
    col_branch = max(len(e["branch"]) for e in entries)
    col_status = max(len(e["status"]) for e in entries)

    col_id = max(col_id, 10)
    col_pid = max(col_pid, 5)
    col_branch = max(col_branch, 6)
    col_status = max(col_status, 6)

    header = (
        f"{'runner_id':<{col_id}}  {'PID':<{col_pid}}  {'branch':<{col_branch}}  "
        f"{'status':<{col_status}}  keys"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)
    for e in entries:
        pid_str = str(e["pid"]) if e["pid"] is not None else "N/A"
        print(
            f"{e['runner_id']:<{col_id}}  {pid_str:<{col_pid}}  {e['branch']:<{col_branch}}  "
            f"{e['status']:<{col_status}}  {len(e['keys'])}"
        )


def delete_runner_keys(r: redis.Redis, entries: list) -> int:
    """dead runner 키를 실제로 삭제한다. 삭제된 키 수를 반환한다."""
    pipe = r.pipeline()
    for e in entries:
        for k in e["keys"]:
            pipe.delete(k)
        pipe.srem(ACTIVE_SET_KEY, e["runner_id"])
    results = pipe.execute()
    return sum(1 for result in results if result)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="plan-runner:runners:* 중 PID가 죽은 키를 정리합니다."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="삭제 대상만 출력 (기본값)",
    )
    mode_group.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="실제 삭제 실행",
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        default=False,
        help="branch 값에 'test_' 포함된 것만 대상",
    )
    parser.add_argument(
        "--db",
        type=int,
        default=0,
        help="대상 Redis DB 번호 (기본: 0)",
    )
    args = parser.parse_args()

    dry_run = not args.force

    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=args.db,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        r.ping()
    except redis.exceptions.ConnectionError as e:
        print(f"[ERROR] Redis 연결 실패 (db={args.db}): {e}", file=sys.stderr)
        return 1

    print(f"Redis db={args.db} 스캔 중 (test_only={args.test_only}) ...")
    dead = scan_dead_runners(r, test_only=args.test_only)
    incomplete = scan_incomplete_runners(r, test_only=args.test_only)
    all_targets = dead + incomplete

    if not all_targets:
        print("정리 대상 고아 키 없음.")
        return 0

    if dead:
        print(f"\n[PID dead runner] {len(dead)}개 발견:")
        print_table(dead)

    if incomplete:
        print(f"\n[불완전 runner (pid 없음)] {len(incomplete)}개 발견:")
        print_table(incomplete)

    total_keys = sum(len(e["keys"]) for e in all_targets)
    print(f"\n총 {len(all_targets)}개 runner, {total_keys}개 키 대상")

    if dry_run:
        print("\n[dry-run] 실제 삭제하려면 --force 옵션을 사용하세요.")
    else:
        deleted = delete_runner_keys(r, all_targets)
        print(f"\n[force] {deleted}개 키 삭제 완료.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
