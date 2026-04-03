from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path


def _fail(message: str) -> int:
    sys.stderr.write(f"{message}\n")
    return 1


def _device_root(base: Path, serial: str) -> Path:
    return base / serial


def _remote_to_local(base: Path, serial: str, remote_path: str) -> Path:
    normalized = remote_path.replace("\\", "/").lstrip("/")
    return _device_root(base, serial) / Path(*[part for part in normalized.split("/") if part])


def _local_to_remote(local_path: Path, serial_root: Path) -> str:
    rel = local_path.relative_to(serial_root)
    return "/" + rel.as_posix()


def _print_devices(serials: list[str]) -> int:
    print("List of devices attached")
    for idx, serial in enumerate(serials, start=1):
        print(
            f"{serial}\tdevice product:fake_product model:FakePhone{idx} "
            f"device:fake_device transport_id:{idx}"
        )
    return 0


def _handle_shell(base: Path, serial: str, shell_command: str) -> int:
    try:
        tokens = shlex.split(shell_command, posix=True)
    except ValueError:
        return _fail("fake-adb: failed to parse shell command")

    if not tokens:
        return 0

    cmd = tokens[0]

    if cmd == "find" and len(tokens) >= 2:
        remote_root = tokens[1]
        local_root = _remote_to_local(base, serial, remote_root)
        if not local_root.exists():
            return 0
        serial_root = _device_root(base, serial)
        for path in sorted(local_root.rglob("*")):
            if path.is_file():
                print(_local_to_remote(path, serial_root))
        return 0

    if cmd == "stat" and len(tokens) >= 4 and tokens[1] == "-c":
        remote_path = tokens[3]
        local_path = _remote_to_local(base, serial, remote_path)
        if not local_path.exists():
            return _fail("fake-adb: stat target not found")
        stat = local_path.stat()
        print(f"{int(stat.st_mtime)}|{stat.st_size}")
        return 0

    if cmd == "rm":
        if tokens and tokens[-2:] and tokens[-2] == "--":
            remote_path = tokens[-1]
        else:
            remote_path = tokens[-1]
        local_path = _remote_to_local(base, serial, remote_path)
        if local_path.exists():
            local_path.unlink()
        return 0

    return _fail(f"fake-adb: unsupported shell command: {shell_command}")


def _handle_pull(base: Path, serial: str, remote_path: str, target_path: str) -> int:
    local_source = _remote_to_local(base, serial, remote_path)
    if not local_source.exists():
        return _fail("fake-adb: remote file not found")
    destination = Path(target_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_source, destination)
    print(f"{remote_path}: 1 file pulled")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    base = Path(os.environ.get("FAKE_ADB_ROOT", ".")).resolve()
    serials_raw = os.environ.get("FAKE_ADB_SERIALS", "FAKE001,FAKE002")
    serials = [item.strip() for item in serials_raw.split(",") if item.strip()]

    if not argv:
        return _fail("fake-adb: missing command")

    if argv[0] == "devices":
        return _print_devices(serials)

    if len(argv) >= 4 and argv[0] == "-s":
        serial = argv[1]
        command = argv[2]
        if serial not in serials:
            return _fail("fake-adb: unknown device serial")

        if command == "shell":
            shell_command = " ".join(argv[3:])
            return _handle_shell(base, serial, shell_command)

        if command == "pull" and len(argv) >= 5:
            remote_path = argv[3]
            target_path = argv[4]
            return _handle_pull(base, serial, remote_path, target_path)

    return _fail(f"fake-adb: unsupported args: {' '.join(argv)}")


if __name__ == "__main__":
    raise SystemExit(main())

