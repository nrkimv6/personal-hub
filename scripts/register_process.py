"""PowerShell watchdog에서 Start-Process 직후 호출하는 프로세스 등록 CLI.

Usage:
    python scripts/register_process.py --pid 1234 --ppid 5678 --name worker --exe python.exe --role worker

Exit codes:
    0: 성공 또는 Redis 미연결(graceful)
    1: 인자 오류 등 실패
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.shared.process.registry import ProcessRegistry  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ProcessRegistry에 프로세스를 등록한다."
    )
    parser.add_argument("--pid", type=int, required=True, help="프로세스 ID")
    parser.add_argument("--ppid", type=int, required=True, help="부모 프로세스 ID")
    parser.add_argument("--name", type=str, required=True, help="프로세스 이름")
    parser.add_argument("--exe", type=str, required=True, help="실행 파일 경로")
    parser.add_argument("--role", type=str, required=True, help="역할")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    registry = ProcessRegistry()
    success = await registry.register(
        pid=args.pid,
        ppid=args.ppid,
        name=args.name,
        exe=args.exe,
        role=args.role,
    )
    if not success:
        # Redis 미연결 시 경고 출력 후 정상 종료 (워커 시작을 블로킹하지 않음)
        print(
            f"[register_process] WARNING: Redis 미연결 — pid={args.pid} 등록 스킵",
            file=sys.stderr,
        )
    else:
        print(f"[register_process] OK: pid={args.pid} role={args.role} 등록 완료")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
