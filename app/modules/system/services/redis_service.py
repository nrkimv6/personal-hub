"""
Redis 연결 상태 조회 및 재시작 관리
"""
import asyncio
from pathlib import Path


class RedisService:
    """Redis 연결 상태 조회 및 컨테이너 재시작 관리"""

    async def get_redis_status(self) -> dict:
        """Redis 연결 상태 및 info 조회"""
        result = {
            "connected": False,
            "container_running": None,
            "uptime_seconds": None,
            "used_memory_mb": None,
            "connected_clients": None,
        }

        # 1. Redis ping + info (동기 라이브러리이므로 executor에서 실행)
        def _sync_redis_check():
            import redis as redis_lib
            r = redis_lib.Redis(host="localhost", port=6379, socket_connect_timeout=1, decode_responses=True)
            try:
                r.ping()
                info = r.info(section="server")
                mem_info = r.info(section="memory")
                clients_info = r.info(section="clients")
                return {
                    "connected": True,
                    "uptime_seconds": info.get("uptime_in_seconds"),
                    "used_memory_mb": round(mem_info.get("used_memory", 0) / 1024 / 1024, 1),
                    "connected_clients": clients_info.get("connected_clients"),
                }
            finally:
                r.close()

        try:
            loop = asyncio.get_event_loop()
            redis_info = await loop.run_in_executor(None, _sync_redis_check)
            result.update(redis_info)
        except Exception:
            pass

        # 2. Podman 컨테이너 상태 (실패해도 무시)
        try:
            proc = await asyncio.create_subprocess_exec(
                "podman", "inspect", "--format", "{{.State.Running}}", "monitor-redis",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                result["container_running"] = stdout.decode().strip().lower() == "true"
        except Exception:
            pass

        return result

    async def restart_redis(self) -> dict:
        """Redis 컨테이너 재시작 (podman-compose 경유)"""
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        compose_path = project_root / ".venv" / "Scripts" / "podman-compose.exe"
        if not compose_path.exists():
            compose_path = "podman-compose"
        else:
            compose_path = str(compose_path)

        try:
            # Podman 소켓 검증 — Session 0에서는 Machine 복구 불가, CLI 안내만 반환
            check_proc = await asyncio.create_subprocess_exec(
                "podman", "ps",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(check_proc.communicate(), timeout=5)
            if check_proc.returncode != 0:
                return {
                    "success": False,
                    "message": (
                        "Podman 소켓 연결 실패 (SSH 터널 끊김). "
                        "터미널에서 실행: podman machine stop && podman machine start && podman start monitor-redis"
                    ),
                }

            proc = await asyncio.create_subprocess_exec(
                compose_path, "up", "-d", "redis",
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                return {"success": False, "message": f"podman-compose 실패: {error_msg}"}

            # ping 확인 (3초 대기 후)
            await asyncio.sleep(3)
            try:
                import redis as redis_lib
                r = redis_lib.Redis(host="localhost", port=6379, socket_connect_timeout=3)
                r.ping()
                r.close()
                return {"success": True, "message": "Redis 재시작 완료 (PONG 확인)"}
            except Exception:
                return {"success": True, "message": "Redis 컨테이너 시작됨 (연결 미확인 — 잠시 후 재확인)"}

        except asyncio.TimeoutError:
            return {"success": False, "message": "podman-compose 타임아웃 (30초)"}
        except Exception as e:
            return {"success": False, "message": f"Redis 재시작 실패: {str(e)}"}
