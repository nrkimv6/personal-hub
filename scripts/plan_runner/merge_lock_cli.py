"""
merge_lock_cli.py — PowerShell에서 호출 가능한 merge turn lock CLI wrapper

사용법:
  python merge_lock_cli.py acquire <runner_id> [--timeout <초>]
  python merge_lock_cli.py release <runner_id>

Exit codes:
  0  성공 (acquire 획득 / release 완료)
  2  acquire timeout (MERGE_LOCK_TIMEOUT)
  3  redis 연결 실패 (REDIS_UNAVAILABLE)

환경변수:
  MERGE_TEST_LOCK_TIMEOUT  acquire timeout 초(기본 86400). CLI --timeout보다 우선.
"""

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS = 86400

# merge_queue.py가 같은 디렉토리에 있으므로 경로 삽입
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _get_redis_client():
    """Redis 클라이언트를 반환한다.

    연결 실패 시 exit 3 + stderr REDIS_UNAVAILABLE을 출력하고 종료한다.
    호출자가 exit code 3을 받으면 lock 없이 merge를 진행하지 않아야 한다.
    """
    try:
        import redis as redis_lib
    except ImportError:
        print("REDIS_UNAVAILABLE: redis 패키지 미설치", file=sys.stderr)
        sys.exit(3)

    # monitor-page RedisClient 패턴 우선 시도
    try:
        _app_path = Path(__file__).resolve().parents[2]  # monitor-page root
        if str(_app_path) not in sys.path:
            sys.path.insert(0, str(_app_path))
        from app.shared.redis_client import RedisClient  # type: ignore

        client = RedisClient.get_client()
        # ping으로 실제 연결 확인
        client.ping()
        return client
    except Exception:
        pass

    # 직접 연결 폴백
    host = os.environ.get("PLAN_RUNNER_REDIS_HOST", "localhost")
    port = int(os.environ.get("PLAN_RUNNER_REDIS_PORT", "6379"))
    db = int(os.environ.get("PLAN_RUNNER_REDIS_DB", "0"))

    try:
        client = redis_lib.Redis(host=host, port=port, db=db, socket_connect_timeout=3)
        client.ping()
        return client
    except Exception as e:
        print(f"REDIS_UNAVAILABLE: {e}", file=sys.stderr)
        sys.exit(3)


def _resolve_timeout(cli_timeout: int | None) -> int:
    """timeout 우선순위: env MERGE_TEST_LOCK_TIMEOUT > CLI --timeout > 기본 86400."""
    env_val = os.environ.get("MERGE_TEST_LOCK_TIMEOUT")
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            pass
    if cli_timeout is not None:
        return cli_timeout
    return DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS


def cmd_acquire(runner_id: str, timeout: int) -> None:
    """acquire 서브커맨드 — merge turn을 획득한다.

    성공: exit 0 + stdout ACQUIRED {runner_id}
    timeout: exit 2 + stderr MERGE_LOCK_TIMEOUT {elapsed}s holder={front_id}
    redis 실패: exit 3 + stderr REDIS_UNAVAILABLE (get_redis_client에서 처리)
    대기 중: 5초마다 stderr에 WAITING runner={runner_id} elapsed={s}s front={front_id}
    """
    try:
        from merge_queue import (  # type: ignore
            acquire_merge_turn,
            _get_repo_id,
            get_queue_key,
        )
    except ImportError as e:
        print(f"REDIS_UNAVAILABLE: merge_queue import 실패: {e}", file=sys.stderr)
        sys.exit(3)

    redis_client = _get_redis_client()

    # 프로젝트 루트 = merge_lock_cli.py 위치에서 두 단계 위 (scripts/plan_runner → monitor-page)
    project_root = Path(__file__).resolve().parents[2]
    repo_id = _get_repo_id(project_root)
    queue_key = get_queue_key(repo_id)

    # acquire_merge_turn을 직접 호출하면 내부 BRPOP이 블로킹되므로
    # 진행 로그(WAITING ...)를 출력하는 래퍼를 threading으로 구현한다.
    import threading

    acquired_event = threading.Event()
    result_holder: dict = {"value": None, "elapsed": 0, "front": "unknown"}
    start_time = time.time()

    def _log_waiting():
        """백그라운드에서 5초마다 WAITING 로그를 stderr에 출력한다."""
        interval = 5
        while not acquired_event.wait(timeout=interval):
            elapsed = int(time.time() - start_time)
            # 현재 front runner 확인
            try:
                raw = redis_client.lindex(queue_key, 0)
                front = raw.decode() if isinstance(raw, bytes) else (raw or "unknown")
            except Exception:
                front = "unknown"
            result_holder["front"] = front
            print(
                f"WAITING runner={runner_id} elapsed={elapsed}s front={front}",
                file=sys.stderr,
                flush=True,
            )

    log_thread = threading.Thread(target=_log_waiting, daemon=True)
    log_thread.start()

    try:
        success = acquire_merge_turn(
            redis_client,
            runner_id=runner_id,
            repo_id=repo_id,
            timeout=timeout,
        )
    finally:
        acquired_event.set()  # 로그 스레드 종료
        result_holder["elapsed"] = int(time.time() - start_time)

    if success:
        print(f"ACQUIRED {runner_id}")
        sys.exit(0)
    else:
        # timeout 케이스
        front = result_holder.get("front", "unknown")
        elapsed = result_holder.get("elapsed", timeout)
        print(
            f"MERGE_LOCK_TIMEOUT {elapsed}s holder={front}",
            file=sys.stderr,
        )
        sys.exit(2)


def cmd_release(runner_id: str) -> None:
    """release 서브커맨드 — merge turn을 해제한다.

    성공: exit 0 + stdout RELEASED {runner_id}
    큐에 없는 경우: exit 0 (no-op)
    redis 실패: exit 3 (get_redis_client에서 처리)
    """
    try:
        from merge_queue import release_merge_turn, _get_repo_id  # type: ignore
    except ImportError as e:
        print(f"REDIS_UNAVAILABLE: merge_queue import 실패: {e}", file=sys.stderr)
        sys.exit(3)

    redis_client = _get_redis_client()

    project_root = Path(__file__).resolve().parents[2]
    repo_id = _get_repo_id(project_root)

    release_merge_turn(redis_client, runner_id=runner_id, repo_id=repo_id)
    print(f"RELEASED {runner_id}")
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge turn lock CLI — acquire/release merge queue turn"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # acquire 서브커맨드
    acq = subparsers.add_parser("acquire", help="Acquire merge turn (blocking wait)")
    acq.add_argument("runner_id", help="Runner ID (예: manual-20260425123000-1234-slug)")
    acq.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="최대 대기 시간(초). env MERGE_TEST_LOCK_TIMEOUT > 이 값 > 기본 86400",
    )

    # release 서브커맨드
    rel = subparsers.add_parser("release", help="Release merge turn")
    rel.add_argument("runner_id", help="Runner ID (acquire와 동일)")

    args = parser.parse_args()

    if args.command == "acquire":
        timeout = _resolve_timeout(args.timeout)
        cmd_acquire(args.runner_id, timeout)
    elif args.command == "release":
        cmd_release(args.runner_id)


if __name__ == "__main__":
    main()
