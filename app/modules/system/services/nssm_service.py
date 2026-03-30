"""
NSSM 서비스 조회/관리 + Startup programs + Scheduled tasks
"""
import asyncio
import json
from pathlib import Path

from ..config import MANAGED_PROJECTS
from .system_utils import run_admin_command


class NssmService:
    """NSSM 서비스, startup program, scheduled task 조회 및 관리"""

    async def get_nssm_services(self) -> list:
        """Query NSSM services by prefix"""
        result = []

        for project_name, config in MANAGED_PROJECTS.items():
            prefix = config.get("nssm_prefix")
            if prefix:
                services = await self._query_services_by_prefix(prefix, project_name)
                result.extend(services)

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

    async def restart_nssm_service(self, name: str) -> dict:
        """Restart an NSSM service"""
        ps_cmd = f"Restart-Service -Name '{name}' -Force -ErrorAction Stop"
        return await run_admin_command(ps_cmd, f"Restarted service: {name}")

    async def stop_nssm_service(self, name: str) -> dict:
        """Stop an NSSM service"""
        ps_cmd = f"Stop-Service -Name '{name}' -Force -ErrorAction Stop"
        return await run_admin_command(ps_cmd, f"Stopped service: {name}")

    async def start_nssm_service(self, name: str) -> dict:
        """Start an NSSM service"""
        ps_cmd = f"Start-Service -Name '{name}' -ErrorAction Stop"
        return await run_admin_command(ps_cmd, f"Started service: {name}")

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
        return await run_admin_command(ps_cmd, f"Started task: {folder}/{name}")

    async def unregister_scheduled_task(self, folder: str, name: str) -> dict:
        """Unregister a scheduled task"""
        ps_cmd = f"Unregister-ScheduledTask -TaskName '{name}' -TaskPath '\\{folder}\\' -Confirm:$false -ErrorAction Stop"
        return await run_admin_command(ps_cmd, f"Unregistered task: {folder}/{name}")
