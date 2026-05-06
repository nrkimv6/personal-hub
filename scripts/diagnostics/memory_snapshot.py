"""Frontend watchdog용 메모리 스냅샷 CLI."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import psutil

_SCRIPT_EXTENSIONS = {".py", ".ps1", ".bat", ".cmd"}


def _shorten_path(path: str, max_len: int = 80) -> str:
    if len(path) <= max_len:
        return path
    p = Path(path)
    return f"…\\{p.parent.name}\\{p.name}"


def _extract_script_path(cmdline: list[str]) -> str | None:
    for arg in cmdline:
        try:
            ext = Path(arg).suffix.lower()
        except (TypeError, ValueError):
            continue
        if ext in _SCRIPT_EXTENSIONS:
            return _shorten_path(str(arg))
    return None


def collect_snapshot(top_n: int = 5) -> dict:
    if top_n < 0:
        raise ValueError("top_n must be >= 0")

    vm = psutil.virtual_memory()
    top_processes: list[dict] = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            memory_info = proc.info.get("memory_info")
            rss = memory_info.rss if memory_info is not None else 0
            try:
                cmdline = proc.cmdline()
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                cmdline = []

            top_processes.append(
                {
                    "pid": int(proc.info["pid"]),
                    "name": proc.info.get("name") or "",
                    "memory_mb": round(rss / (1024 * 1024), 1),
                    "script_path": _extract_script_path(cmdline),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, KeyError, ValueError):
            continue

    top_processes.sort(key=lambda item: item["memory_mb"], reverse=True)
    if top_n == 0:
        top_processes = []
    else:
        top_processes = top_processes[:top_n]

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "available_mb": round(vm.available / (1024 * 1024), 1),
        "total_mb": round(vm.total / (1024 * 1024), 1),
        "top_processes": top_processes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="메모리 스냅샷을 JSON으로 출력한다.")
    parser.add_argument("--json", action="store_true", help="compact JSON 출력")
    parser.add_argument("--top", type=int, default=5, help="상위 프로세스 개수")
    args = parser.parse_args()

    snapshot = collect_snapshot(top_n=args.top)
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False))
    else:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
