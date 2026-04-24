"""
운영용 탭 풀 진단 CLI

실행 중인 워커의 /api/v1/worker/browser-status와 /api/v1/system/status를 쿼리해
실제 pool 상태를 출력한다. ContextManager/TabPoolManager 직접 인스턴스 방식은
항상 빈 상태를 반환하므로 사용하지 않는다.

주의: in_use_count/waiter_count는 worker 내부 메트릭으로 이 API에서 제공하지 않는다.
추정치로 대체하지 않는다.

사용법:
    python scripts/diagnostics/diagnose_naver_tab_pool.py
    python scripts/diagnostics/diagnose_naver_tab_pool.py --watch 5   # 5초 간격 반복
"""
import argparse
import sys
import time

import httpx

_BASE_URL = "http://localhost:8001"
_TIMEOUT = 5.0


def _fetch_status() -> dict:
    """browser-status + system/status를 조합해 반환한다."""
    browser = httpx.get(f"{_BASE_URL}/api/v1/worker/browser-status", timeout=_TIMEOUT).json()
    system = httpx.get(f"{_BASE_URL}/api/v1/system/status", timeout=_TIMEOUT).json()
    return {"browser": browser, "system": system}


def _dump_once() -> None:
    """한 번 상태를 출력한다."""
    try:
        data = _fetch_status()
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPError):
        print("API 미응답 (localhost:8001) — 서버가 실행 중인지 확인하세요", file=sys.stderr)
        sys.exit(1)

    browser = data["browser"]
    system = data["system"]

    print(f"available           : {browser.get('available', 'N/A')}")
    print(f"last_heartbeat      : {browser.get('last_heartbeat', 'N/A')}")
    print(f"worker_status       : {system.get('worker_status', 'N/A')}")
    print(f"active_tabs         : {system.get('active_tabs', 'N/A')}")
    print(f"browser_contexts    : {system.get('browser_contexts', 'N/A')}")
    # in_use_count/waiter_count는 worker 내부 메트릭으로 이 API에서 제공되지 않음


def main() -> None:
    parser = argparse.ArgumentParser(description="탭 풀 진단 CLI (API 기반)")
    parser.add_argument("--watch", type=int, metavar="INTERVAL",
                        help="N초 간격으로 반복 출력 (Ctrl+C로 중단)")
    args = parser.parse_args()

    if args.watch:
        print(f"[TAB-POOL-DIAG] {args.watch}초 간격 반복 출력 (Ctrl+C로 중단)")
        try:
            while True:
                print("=" * 60)
                _dump_once()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n중단됨")
    else:
        _dump_once()


if __name__ == "__main__":
    main()
