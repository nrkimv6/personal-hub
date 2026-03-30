"""
System service for querying and managing Windows services, startup programs, and scheduled tasks
"""
import asyncio
import ctypes
import json
from pathlib import Path
from typing import Optional
import os

from ..config import MANAGED_PROJECTS


class SystemService:
    """Service for system status queries and management operations"""

    async def get_all_services_status(self) -> dict:
        """Get all services status grouped by project"""
        nssm_services = await self.get_nssm_services()
        startup_programs = await self.get_startup_programs()
        scheduled_tasks = await self.get_scheduled_tasks()
        worker_processes = await self.get_worker_status()

        # Group by project
        projects = {}
        for project_name in MANAGED_PROJECTS.keys():
            projects[project_name] = {
                "nssm_services": [s for s in nssm_services if s.get("project") == project_name],
                "startup_programs": [s for s in startup_programs if s.get("project") == project_name],
                "scheduled_tasks": [s for s in scheduled_tasks if s.get("project") == project_name],
                "worker_processes": [s for s in worker_processes if s.get("project") == project_name]
            }

        return {"projects": projects}

    async def get_nssm_services(self) -> list:
        """Query NSSM services by prefix"""
        result = []

        for project_name, config in MANAGED_PROJECTS.items():
            prefix = config.get("nssm_prefix")
            if prefix:
                services = await self._query_services_by_prefix(prefix, project_name)
                result.extend(services)

            # System services (specific names)
            nssm_services = config.get("nssm_services", [])
            for svc_name in nssm_services:
                service = await self._query_service_by_name(svc_name, project_name)
                result.append(service)

        return result

    async def _query_services_by_prefix(self, prefix: str, project_name: str) -> list:
        """Query Windows services by name prefix"""
        ps_cmd = f"Get-Service -Name '{prefix}*' -ErrorAction SilentlyContinue | Select-Object Name, Status, StartType, DisplayName | ConvertTo-Json -Compress"

        proc = await asyncio.create_subprocess_shell(
            f'powershell -Command "{ps_cmd}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)

        if not stdout:
            return [self._unregistered_sentinel(prefix, project_name)]

        try:
            data = json.loads(stdout.decode('utf-8'))
            if isinstance(data, dict):
                data = [data]

            result = [{
                "name": svc.get("Name", ""),
                "project": project_name,
                "status": self._normalize_status(svc.get("Status")),
                "start_type": str(svc.get("StartType", "Unknown")),
                "display_name": svc.get("DisplayName", "")
            } for svc in data]

            if not result:
                return [self._unregistered_sentinel(prefix, project_name)]
            return result
        except json.JSONDecodeError:
            return [self._unregistered_sentinel(prefix, project_name)]

    async def _query_service_by_name(self, name: str, project_name: str) -> dict:
        """Query a specific Windows service by name"""
        ps_cmd = f"Get-Service -Name '{name}' -ErrorAction SilentlyContinue | Select-Object Name, Status, StartType, DisplayName | ConvertTo-Json -Compress"

        proc = await asyncio.create_subprocess_shell(
            f'powershell -Command "{ps_cmd}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)

        if not stdout:
            return self._unregistered_sentinel(name, project_name)

        try:
            svc = json.loads(stdout.decode('utf-8'))
            return {
                "name": svc.get("Name", ""),
                "project": project_name,
                "status": self._normalize_status(svc.get("Status")),
                "start_type": str(svc.get("StartType", "Unknown")),
                "display_name": svc.get("DisplayName", "")
            }
        except json.JSONDecodeError:
            return self._unregistered_sentinel(name, project_name)

    def _normalize_status(self, status) -> str:
        """Normalize service status to string"""
        if isinstance(status, int):
            status_map = {1: "Stopped", 2: "StartPending", 3: "StopPending", 4: "Running"}
            return status_map.get(status, "Unknown")
        return str(status) if status else "Unknown"

    def _unregistered_sentinel(self, name: str, project_name: str) -> dict:
        """Return a sentinel dict for an unregistered service"""
        return {
            "name": name,
            "project": project_name,
            "status": "Unregistered",
            "start_type": "N/A",
            "display_name": f"{name} (미등록)",
        }

    async def get_startup_programs(self) -> list:
        """Query startup programs by prefix"""
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        result = []

        for project_name, config in MANAGED_PROJECTS.items():
            prefix = config.get("startup_prefix")
            if not prefix:
                continue

            if not startup_dir.exists():
                continue

            for lnk_file in startup_dir.glob(f"{prefix}*.lnk"):
                result.append({
                    "name": lnk_file.stem,
                    "project": project_name,
                    "registered": True,
                    "path": str(lnk_file)
                })

        return result

    async def get_scheduled_tasks(self) -> list:
        """Query scheduled tasks by folder"""
        result = []

        for project_name, config in MANAGED_PROJECTS.items():
            folder = config.get("task_folder")
            if not folder:
                continue

            tasks = await self._query_tasks_in_folder(folder, project_name)
            result.extend(tasks)

        return result

    async def _query_tasks_in_folder(self, folder: str, project_name: str) -> list:
        """Query all scheduled tasks in a folder"""
        ps_script = f'''
$tasks = Get-ScheduledTask -TaskPath '\\{folder}\\' -ErrorAction SilentlyContinue
if ($tasks) {{
    $tasks | ForEach-Object {{
        $info = Get-ScheduledTaskInfo -TaskName $_.TaskName -TaskPath $_.TaskPath -ErrorAction SilentlyContinue
        [PSCustomObject]@{{
            Name = $_.TaskName
            Folder = '{folder}'
            State = $_.State.ToString()
            Description = $_.Description
            LastRun = if ($info -and $info.LastRunTime) {{ $info.LastRunTime.ToString('o') }} else {{ $null }}
            NextRun = if ($info -and $info.NextRunTime) {{ $info.NextRunTime.ToString('o') }} else {{ $null }}
            LastResult = if ($info) {{ $info.LastTaskResult }} else {{ $null }}
        }}
    }} | ConvertTo-Json -Compress
}}
'''
        proc = await asyncio.create_subprocess_exec(
            'powershell', '-NoProfile', '-Command', ps_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)

        if not stdout:
            return []

        try:
            # Windows PowerShell may output in cp949 or utf-8
            try:
                output = stdout.decode('utf-8')
            except UnicodeDecodeError:
                output = stdout.decode('cp949', errors='replace')

            data = json.loads(output)
            if isinstance(data, dict):
                data = [data]

            for task in data:
                task["project"] = project_name

            return data
        except json.JSONDecodeError:
            return []

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

    # ===== Management Operations =====

    async def restart_nssm_service(self, name: str) -> dict:
        """Restart an NSSM service"""
        ps_cmd = f"Restart-Service -Name '{name}' -Force -ErrorAction Stop"
        return await self._run_admin_command(ps_cmd, f"Restarted service: {name}")

    async def stop_nssm_service(self, name: str) -> dict:
        """Stop an NSSM service"""
        ps_cmd = f"Stop-Service -Name '{name}' -Force -ErrorAction Stop"
        return await self._run_admin_command(ps_cmd, f"Stopped service: {name}")

    async def start_nssm_service(self, name: str) -> dict:
        """Start an NSSM service"""
        ps_cmd = f"Start-Service -Name '{name}' -ErrorAction Stop"
        return await self._run_admin_command(ps_cmd, f"Started service: {name}")

    async def remove_startup_program(self, name: str) -> dict:
        """Remove a startup program"""
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        lnk_path = startup_dir / f"{name}.lnk"

        if lnk_path.exists():
            try:
                lnk_path.unlink()
                return {"success": True, "message": f"Removed startup program: {name}"}
            except Exception as e:
                return {"success": False, "message": f"Failed to remove: {str(e)}"}
        return {"success": False, "message": f"Startup program not found: {name}"}

    async def run_scheduled_task(self, folder: str, name: str) -> dict:
        """Run a scheduled task manually"""
        ps_cmd = f"Start-ScheduledTask -TaskName '{name}' -TaskPath '\\{folder}\\' -ErrorAction Stop"
        return await self._run_admin_command(ps_cmd, f"Started task: {folder}/{name}")

    async def unregister_scheduled_task(self, folder: str, name: str) -> dict:
        """Unregister a scheduled task"""
        ps_cmd = f"Unregister-ScheduledTask -TaskName '{name}' -TaskPath '\\{folder}\\' -Confirm:$false -ErrorAction Stop"
        return await self._run_admin_command(ps_cmd, f"Unregistered task: {folder}/{name}")

    async def _kill_pid_file(self, pid_file: Path, label: str) -> tuple[bool, str]:
        """PID 파일을 읽어 프로세스를 kill. (성공여부, 메시지) 반환."""
        if not pid_file.exists():
            return False, f"{label}: PID 파일 없음"
        try:
            pid = int(pid_file.read_text().strip())
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
            # infra tier 제외 (command_listener, api_watchdog)
            if item.get("tier") == "infra":
                continue
            if name != "all" and item["name"] != name:
                continue

            # watchdog 없으면 재시작 불가 경고
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
            # 와치독 종료
            success, msg = await self._kill_pid_file(
                pid_dir / item["watchdog_pid_file"], f"{item['label']} watchdog"
            )
            (killed if success else failed).append(msg)
            # 워커도 함께 종료 (고아 방지)
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
        # 인프라 유지 안내
        infra_names = [item["label"] for item in items if item.get("tier") == "infra"]
        if infra_names:
            parts.append(f"인프라 유지: {', '.join(infra_names)}")
        return {"success": len(killed) > 0 or all("PID 파일 없음" in f for f in failed), "message": " | ".join(parts) if parts else "모든 watchdog가 이미 중지 상태입니다."}

    async def start_watchdogs(self) -> dict:
        """Redis Command Listener를 통해 watchdog 시작 요청.
        API는 Session 0(NSSM)이므로 직접 subprocess 불가 → Redis 경유.
        """
        from app.shared.redis.client import RedisClient

        redis_client = await RedisClient.get_client()
        if not redis_client:
            return {"success": False, "message": "Redis 연결 없음. CLI에서 실행: python scripts/browser_workers.py start"}

        try:
            command = json.dumps({
                "action": "start",
                "timestamp": __import__("datetime").datetime.now().isoformat(),
                "source": "system-api",
            })
            await redis_client.delete("worker:command_results")
            await redis_client.lpush("worker:commands", command)

            result = await redis_client.brpop("worker:command_results", timeout=30)
            if result:
                _, result_data = result
                result_json = json.loads(result_data) if isinstance(result_data, str) else json.loads(result_data.decode())
                return {"success": result_json.get("success", False), "message": result_json.get("message", "완료")}
            else:
                return {"success": False, "message": "Command Listener 응답 타임아웃 (30초). CLI에서 실행: python scripts/browser_workers.py start"}
        except Exception as e:
            return {"success": False, "message": f"Redis 명령 전송 실패: {str(e)}. CLI에서 실행: python scripts/browser_workers.py start"}

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

    async def get_nightly_cleanup_stats(self, days: int = 14) -> dict:
        """Nightly done-cleanup 로그 파일 파싱 — 프로젝트별 완료 항목 수 통계"""
        import re
        from datetime import date, timedelta

        log_dir = Path("D:/work/project/service/wtools/common/scripts/logs")
        today = date.today()
        runs = []

        for i in range(days):
            target_date = today - timedelta(days=i)
            log_file = log_dir / f"done-cleanup-{target_date.strftime('%Y-%m-%d')}.log"
            if not log_file.exists():
                continue

            try:
                content = log_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            run = {
                "date": target_date.isoformat(),
                "total_items": 0,
                "processed": 0,
                "failed": 0,
                "skipped": 0,
                "duration": None,
                "projects": {}
            }

            # 프로젝트별 item count 파싱
            # "    - activity-hub: 52 items"
            for m in re.finditer(r"- ([a-z0-9_\-]+): (\d+) items", content):
                project_name, count = m.group(1), int(m.group(2))
                run["projects"][project_name] = count

            # Summary 파싱
            m = re.search(r"Total Items Archived: (\d+)", content)
            if m:
                run["total_items"] = int(m.group(1))

            m = re.search(r"Processed: (\d+)", content)
            if m:
                run["processed"] = int(m.group(1))

            m = re.search(r"Failed: (\d+)", content)
            if m:
                run["failed"] = int(m.group(1))

            m = re.search(r"Skipped: (\d+)", content)
            if m:
                run["skipped"] = int(m.group(1))

            m = re.search(r"Duration: ([\d:]+)", content)
            if m:
                run["duration"] = m.group(1)

            runs.append(run)

        # 전체 요약
        total_runs = len(runs)
        total_items_all = sum(r["total_items"] for r in runs)
        all_projects: dict[str, int] = {}
        for r in runs:
            for proj, cnt in r["projects"].items():
                all_projects[proj] = all_projects.get(proj, 0) + cnt

        return {
            "runs": runs,
            "summary": {
                "total_runs": total_runs,
                "total_items_archived": total_items_all,
                "avg_items_per_run": round(total_items_all / total_runs, 1) if total_runs else 0,
                "by_project": all_projects,
            }
        }

    async def _run_admin_command(self, ps_cmd: str, success_msg: str) -> dict:
        """Execute a PowerShell command (may require admin privileges)"""
        try:
            proc = await asyncio.create_subprocess_shell(
                f'powershell -Command "{ps_cmd}"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

            if proc.returncode == 0:
                return {"success": True, "message": success_msg}
            else:
                error_msg = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
                return {"success": False, "message": error_msg}
        except Exception as e:
            return {"success": False, "message": str(e)}
