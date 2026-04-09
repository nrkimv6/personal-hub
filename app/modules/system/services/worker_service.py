"""
Worker 프로세스 상태 조회 및 관리 (watchdog + worker pairs)
"""
import asyncio
import ctypes
import json
import subprocess
import sys
from pathlib import Path

from app.core.config import PROJECT_ROOT
from ..config import MANAGED_PROJECTS
from .system_utils import send_redis_command


class WorkerService:
    """Worker/watchdog 프로세스 상태 조회 및 재시작 관리"""

    async def get_worker_status(self) -> list:
        """Query worker process status by PID files (watchdog + worker pairs)"""
        result = []

        for project_name, config in MANAGED_PROJECTS.items():
            workers_config = config.get("workers")
            if not workers_config:
                continue

            project_path = Path(config.get("path", ""))
            pid_dir = project_path / workers_config["pid_dir"]

            for worker in workers_config.get("items", []):
                entry = {
                    "name": worker["name"],
                    "label": worker.get("label", worker["name"]),
                    "project": project_name,
                    "tier": worker.get("tier", "worker"),
                    "watchdog": None,
                    "worker": None,
                }

                watchdog_pid_file = worker.get("watchdog_pid_file")
                if watchdog_pid_file:
                    entry["watchdog"] = await self._read_pid_status(pid_dir / watchdog_pid_file)

                worker_pid_file = worker.get("worker_pid_file")
                if worker_pid_file:
                    entry["worker"] = await self._read_pid_status(pid_dir / worker_pid_file)

                result.append(entry)

        return result

    async def _read_pid_status(self, pid_path: Path) -> dict:
        """Read PID file and check process status"""
        pid = None
        running = False

        if pid_path.exists():
            try:
                pid = int(pid_path.read_text(encoding='utf-8-sig').strip())
                running = await self._check_process_exists(pid)
            except (ValueError, IOError):
                pass

        return {"pid": pid, "running": running}

    async def _check_process_exists(self, pid: int) -> bool:
        """Check if a process exists by PID (Windows 크로스세션 호환)

        ctypes.windll.kernel32.OpenProcess를 사용하여
        NSSM Session 0에서 사용자 Session 1 프로세스도 조회 가능.
        """
        try:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False

    async def _kill_pid_file(self, pid_file: Path, label: str) -> tuple[bool, str]:
        """PID 파일을 읽어 프로세스를 kill. (성공여부, 메시지) 반환."""
        if not pid_file.exists():
            return False, f"{label}: PID 파일 없음"
        try:
            pid = int(pid_file.read_text(encoding='utf-8-sig').strip())
            proc = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(pid), "/F",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode == 0:
                return True, f"{label} (PID {pid})"
            else:
                stderr = (await proc.stderr.read()).decode().strip()
                return False, f"{label} (PID {pid}): {stderr}"
        except Exception as e:
            return False, f"{label}: {str(e)}"

    def _get_monitor_page_workers(self) -> tuple[Path, list]:
        """monitor-page 프로젝트의 workers config와 pid_dir 반환."""
        proj = MANAGED_PROJECTS.get("monitor-page", {})
        workers_config = proj.get("workers")
        if not workers_config or not proj.get("path"):
            return Path(), []
        pid_dir = Path(proj["path"]) / workers_config["pid_dir"]
        return pid_dir, workers_config["items"]

    async def restart_worker(self, name: str) -> dict:
        """워커 프로세스를 kill (watchdog가 자동 재시작).
        api_watchdog는 제외. name="all"이면 전체 워커.
        """
        pid_dir, items = self._get_monitor_page_workers()
        if not items:
            return {"success": False, "message": "워커 설정을 찾을 수 없습니다."}

        killed, failed = [], []
        for item in items:
            if not item.get("worker_pid_file"):
                continue
            if item.get("tier") == "infra":
                continue
            if name != "all" and item["name"] != name:
                continue

            if not item.get("watchdog_pid_file"):
                failed.append(f"{item['label']}: watchdog 없음 (재시작 불가)")
                continue

            success, msg = await self._kill_pid_file(
                pid_dir / item["worker_pid_file"], item["label"]
            )
            (killed if success else failed).append(msg)

        if not killed and not failed:
            return {"success": False, "message": "kill 대상 워커가 없습니다."}

        parts = []
        if killed:
            parts.append(f"종료됨: {', '.join(killed)}")
        if failed:
            parts.append(f"실패: {', '.join(failed)}")
        parts.append("watchdog가 자동 재시작합니다.")
        return {"success": len(killed) > 0, "message": " | ".join(parts)}

    async def restart_infra(self, name: str) -> dict:
        """infra tier 프로세스 개별 재시작. browser_workers.py 직접 subprocess 호출."""
        # command_listener는 config 없이 허용 (별도 재시작 경로)
        if name == "command_listener":
            action = "restart-listener"
            extra_args: list[str] = []
        else:
            pid_dir, items = self._get_monitor_page_workers()
            if not items:
                return {"success": False, "message": "워커 설정을 찾을 수 없습니다."}

            infra_item = next(
                (item for item in items if item.get("tier") == "infra" and item["name"] == name),
                None,
            )
            if not infra_item:
                return {"success": False, "message": f"infra 항목 없음: {name}"}

            action = "restart-infra"
            extra_args = [name]

        scripts_dir = PROJECT_ROOT / "scripts"
        browser_workers = scripts_dir / "browser_workers.py"

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(browser_workers), action, *extra_args],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return {"success": True, "message": result.stdout.strip() or f"{action} 완료"}
            else:
                return {"success": False, "message": result.stderr.strip() or f"exit code {result.returncode}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "프로세스 실행 타임아웃 (60초)"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def stop_watchdogs(self) -> dict:
        """worker tier watchdog + 워커 프로세스를 kill. infra tier는 유지."""
        pid_dir, items = self._get_monitor_page_workers()
        if not items:
            return {"success": False, "message": "워커 설정을 찾을 수 없습니다."}

        killed, failed = [], []
        for item in items:
            if item.get("tier") == "infra":
                continue
            if not item.get("watchdog_pid_file"):
                continue
            success, msg = await self._kill_pid_file(
                pid_dir / item["watchdog_pid_file"], f"{item['label']} watchdog"
            )
            (killed if success else failed).append(msg)
            if item.get("worker_pid_file"):
                w_success, w_msg = await self._kill_pid_file(
                    pid_dir / item["worker_pid_file"], f"{item['label']} worker"
                )
                (killed if w_success else failed).append(w_msg)

        if not killed and not failed:
            return {"success": True, "message": "모든 watchdog가 이미 중지 상태입니다."}

        parts = []
        if killed:
            parts.append(f"종료됨: {', '.join(killed)}")
        if failed:
            all_pid_missing = all("PID 파일 없음" in f for f in failed)
            if not all_pid_missing:
                parts.append(f"실패: {', '.join(failed)}")
        infra_names = [item["label"] for item in items if item.get("tier") == "infra"]
        if infra_names:
            parts.append(f"인프라 유지: {', '.join(infra_names)}")
        return {"success": len(killed) > 0 or all("PID 파일 없음" in f for f in failed), "message": " | ".join(parts) if parts else "모든 watchdog가 이미 중지 상태입니다."}

    async def start_watchdogs(self) -> dict:
        """Redis Command Listener를 통해 watchdog 시작 요청.
        GUI 프로세스(Playwright 워커)는 Session 0에서 spawn 불가 → Redis 경유.
        headless 프로세스는 restart_infra()에서 직접 subprocess 호출.
        """
        from app.shared.redis.client import RedisClient

        redis_client = await RedisClient.get_client()
        if not redis_client:
            return {"success": False, "message": "Redis 연결 없음. CLI에서 실행: python scripts/browser_workers.py start"}

        import datetime
        command = json.dumps({
            "action": "start",
            "timestamp": datetime.datetime.now().isoformat(),
            "source": "system-api",
        })

        return await send_redis_command(
            redis_client,
            cmd_key="worker:commands",
            result_key="worker:command_results",
            command=command,
            timeout=30,
            timeout_msg="Command Listener 응답 타임아웃 (30초). CLI에서 실행: python scripts/browser_workers.py start",
        )
