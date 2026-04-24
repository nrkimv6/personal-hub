"""
운영용 탭 풀 진단 CLI

사용법:
    python scripts/diagnostics/diagnose_naver_tab_pool.py
    python scripts/diagnostics/diagnose_naver_tab_pool.py --watch 5   # 5초 간격 반복
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def _dump_once():
    from app.core.config import settings
    from app.shared.browser.context_manager import ContextManager
    from app.shared.browser.tab_pool_manager import TabPoolManager

    context_manager = ContextManager()
    tab_pool = TabPoolManager(context_manager)
    status = tab_pool.get_status()

    print(f"TOTAL_MAX_TABS      : {settings.TOTAL_MAX_TABS}  (시간 분할 재사용 전제)")
    print(f"TAB_REQUEST_TIMEOUT : {settings.TAB_REQUEST_TIMEOUT}s  (inner polling gate)")
    print(f"total_active_tabs   : {status['total_active_tabs']}")
    print(f"in_use_count        : {status['in_use_count']}")
    print(f"waiter_count        : {status['waiter_count']}")
    print(f"dead_waiter_count   : {status['dead_waiter_count']}")
    print(f"account_pool_sizes  : {status['account_pool_sizes']}")
    print()

    # last_used 요약
    if tab_pool.tab_last_used:
        import time
        now = time.time()
        for tab_id, last_used in sorted(tab_pool.tab_last_used.items()):
            in_use = tab_pool.tab_in_use.get(tab_id, False)
            use_count = tab_pool.tab_use_count.get(tab_id, 0)
            target = tab_pool.tab_current_target.get(tab_id, "-")
            idle = now - last_used
            print(
                f"  tab={tab_id:<20} in_use={in_use!s:<5} "
                f"uses={use_count:>3}/{settings.MAX_USES_PER_TAB} "
                f"idle={idle:>6.1f}s target={target}"
            )


def main():
    parser = argparse.ArgumentParser(description="탭 풀 진단 CLI")
    parser.add_argument("--watch", type=int, metavar="INTERVAL",
                        help="N초 간격으로 반복 출력 (Ctrl+C로 중단)")
    args = parser.parse_args()

    if args.watch:
        import time
        print(f"[TAB-POOL-DIAG] {args.watch}초 간격 반복 출력 (Ctrl+C로 중단)")
        try:
            while True:
                print("=" * 60)
                asyncio.run(_dump_once())
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n중단됨")
    else:
        asyncio.run(_dump_once())


if __name__ == "__main__":
    main()
