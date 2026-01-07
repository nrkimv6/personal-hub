#!/usr/bin/env python3
"""
서버 라이프사이클 관리 유틸리티

테스트 실행 전 서버를 시작하고, 테스트 완료 후 정리합니다.

사용법:
    python with_server.py --server "uvicorn app.main:app --port 8001" --port 8001 \
                          --server "npm run dev --prefix frontend -- --port 6101" --port 6101 \
                          -- pytest tests/e2e/

참조: https://github.com/anthropics/skills/blob/main/skills/webapp-testing/scripts/with_server.py
"""

import argparse
import socket
import subprocess
import sys
import time
from typing import List, Tuple


def is_server_ready(port: int, host: str = "localhost") -> bool:
    """포트가 열려있는지 확인"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def wait_for_server(port: int, timeout: int = 30, host: str = "localhost") -> bool:
    """서버가 준비될 때까지 대기"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_server_ready(port, host):
            return True
        time.sleep(0.5)
    return False


def start_servers(servers: List[Tuple[str, int]], timeout: int) -> List[subprocess.Popen]:
    """서버들을 시작하고 준비될 때까지 대기"""
    processes = []

    for cmd, port in servers:
        print(f"Starting server: {cmd}")
        # Windows에서는 shell=True 필요
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(proc)

    # 모든 서버가 준비될 때까지 대기
    for cmd, port in servers:
        print(f"Waiting for port {port}...")
        if not wait_for_server(port, timeout):
            print(f"ERROR: Server on port {port} did not start within {timeout}s")
            stop_servers(processes)
            sys.exit(1)
        print(f"Port {port} is ready")

    return processes


def stop_servers(processes: List[subprocess.Popen], timeout: int = 5):
    """서버들을 정리"""
    for proc in processes:
        if proc.poll() is None:  # 아직 실행 중
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main():
    parser = argparse.ArgumentParser(
        description="서버를 시작하고, 명령을 실행한 후, 서버를 종료합니다."
    )
    parser.add_argument(
        "--server",
        action="append",
        required=True,
        help="서버 시작 명령 (여러 번 사용 가능)"
    )
    parser.add_argument(
        "--port",
        action="append",
        type=int,
        required=True,
        help="대기할 포트 번호 (--server와 1:1 매칭)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="서버 시작 대기 시간 (초, 기본: 30)"
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="서버 준비 후 실행할 명령"
    )

    args = parser.parse_args()

    # 검증
    if len(args.server) != len(args.port):
        print("ERROR: --server와 --port 개수가 일치해야 합니다")
        sys.exit(1)

    # -- 이후의 명령 추출
    command = args.command
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        print("ERROR: 실행할 명령을 지정하세요 (-- 뒤에)")
        sys.exit(1)

    servers = list(zip(args.server, args.port))
    processes = []

    try:
        processes = start_servers(servers, args.timeout)
        print(f"Running: {' '.join(command)}")
        result = subprocess.run(command, shell=True)
        sys.exit(result.returncode)
    finally:
        print("Stopping servers...")
        stop_servers(processes)


if __name__ == "__main__":
    main()
