#!/usr/bin/env python
"""cleanup_invisible_recent_runners.py — 누적된 invisible runner 일회성 정리 스크립트

기본 동작(dry-run): RECENT_RUNNERS_KEY를 순회하여 invisible runner(trigger 미설정/비사용자) 목록과
개수를 출력한다.

--apply 시: 해당 rid를 RECENT_RUNNERS_KEY에서 제거하고 per-runner 키 전체를 삭제한다.

사용법:
  python scripts/cleanup_invisible_recent_runners.py            # dry-run (기본)
  python scripts/cleanup_invisible_recent_runners.py --apply   # 실제 삭제
"""
import argparse
import sys
from pathlib import Path

# monitor-page 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import redis


RUNNER_KEY_PREFIX = "plan-runner:runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"
RUNNER_KEY_SUFFIXES = (
    "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
    "engine", "fix_engine", "worktree_path", "branch", "merge_status", "merge_requested",
    "current_cycle", "execution_count", "quota_stopped", "error", "restart_after_merge",
    "test_source", "trigger", "exit_reason", "subprocess_heartbeat",
    "pid_create_time", "process_cmdline_hash",
    "reflect_final_path", "accepted_at", "accepted_source", "started_at",
)


def is_visible_runner(trigger: str | None, runner_id: str) -> bool:
    """trigger 값이 user 전용 트리거인지 확인 (visibility.py와 동일 로직)"""
    return trigger in ("user", "user:all")


def main():
    parser = argparse.ArgumentParser(description="invisible recent runner 정리")
    parser.add_argument("--apply", action="store_true", help="실제 삭제 실행 (기본: dry-run)")
    parser.add_argument("--host", default="localhost", help="Redis host (기본: localhost)")
    parser.add_argument("--port", type=int, default=6379, help="Redis port (기본: 6379)")
    parser.add_argument("--db", type=int, default=0, help="Redis DB (기본: 0)")
    args = parser.parse_args()

    r = redis.Redis(host=args.host, port=args.port, db=args.db, decode_responses=True)

    try:
        r.ping()
    except redis.ConnectionError as e:
        print(f"Redis 연결 실패: {e}", file=sys.stderr)
        sys.exit(1)

    before_count = r.zcard(RECENT_RUNNERS_KEY)
    print(f"[before] RECENT_RUNNERS_KEY 크기: {before_count}")

    all_recent = r.zrange(RECENT_RUNNERS_KEY, 0, -1, withscores=True)
    invisible = []
    visible = []

    for rid, score in all_recent:
        trigger = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:trigger")
        if is_visible_runner(trigger, rid):
            visible.append((rid, score, trigger))
        else:
            invisible.append((rid, score, trigger))

    print(f"\nvisible runner ({len(visible)}개):")
    for rid, score, trigger in visible:
        print(f"  {rid}  trigger={trigger!r}  score={score:.0f}")

    print(f"\ninvisible runner ({len(invisible)}개) — {'삭제 예정' if args.apply else 'dry-run'}:")
    for rid, score, trigger in invisible:
        print(f"  {rid}  trigger={trigger!r}  score={score:.0f}")

    if not invisible:
        print("\n정리할 invisible runner 없음.")
        return

    if not args.apply:
        print(f"\n[dry-run] --apply 플래그 없이 실행 중 → 실제 삭제 없음.")
        print(f"실제 삭제: python {Path(__file__).name} --apply")
        return

    # --apply: 실제 삭제
    deleted_count = 0
    for rid, score, trigger in invisible:
        r.zrem(RECENT_RUNNERS_KEY, rid)
        for suffix in RUNNER_KEY_SUFFIXES:
            r.delete(f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}")
        deleted_count += 1
        print(f"  [삭제] {rid}")

    after_count = r.zcard(RECENT_RUNNERS_KEY)
    print(f"\n[완료] 삭제: {deleted_count}개 | before: {before_count} → after: {after_count}")


if __name__ == "__main__":
    main()
