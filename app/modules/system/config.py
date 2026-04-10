"""
System module configuration
Defines managed projects and their service identifiers
"""

MANAGED_PROJECTS = {
    "monitor-page": {
        "path": "D:\\work\\project\\tools\\monitor-page",
        "nssm_prefix": "MonitorPage",
        "startup_prefix": "MonitorPage-",
        "task_folder": "MonitorPage",
        "workers": {
            "pid_dir": ".pids",
            "items": [
                {
                    "name": "unified_worker",
                    "label": "통합 워커",
                    "tier": "worker",
                    "watchdog_pid_file": "worker_watchdog_admin.pid",
                    "worker_pid_file": "unified_worker_admin.pid",
                },
                {
                    "name": "claude_worker",
                    "label": "Claude 워커",
                    "tier": "worker",
                    "watchdog_pid_file": "claude_watchdog_admin.pid",
                    "worker_pid_file": "claude_worker_admin.pid",
                },
                {
                    "name": "command_listener",
                    "label": "명령 리스너",
                    "tier": "infra",
                    "watchdog_pid_file": "command_listener_watchdog_admin.pid",
                    "worker_pid_file": "command_listener_admin.pid",
                },
                {
                    "name": "dev_runner_listener",
                    "label": "Dev Runner 리스너",
                    "tier": "infra",
                    "watchdog_pid_file": "dev_runner_watchdog_admin.pid",
                    "worker_pid_file": "dev_runner_command_listener_admin.pid",
                },
                {
                    "name": "api_watchdog",
                    "label": "API 왓치독",
                    "tier": "infra",
                    "watchdog_pid_file": "api_watchdog_admin.pid",
                    "worker_pid_file": None,
                },
            ]
        }
    },
    "proxy-manager": {
        "path": "D:\\work\\project\\tools\\proxy-manager",
        "nssm_prefix": None,
        "startup_prefix": None,
        "task_folder": "ProxyManager",
        "workers": None
    },
    "wtools": {
        "path": "D:\\work\\project\\service\\wtools",
        "nssm_prefix": None,
        "startup_prefix": None,
        "task_folder": "WTools",
        "workers": None
    },
    "sleep-now": {
        "path": "D:\\work\\project\\tools\\sleep-now",
        "nssm_prefix": "SleepNow",
        "startup_prefix": "SleepNow-",
        "task_folder": "SleepNow",
        "workers": {
            "pid_dir": ".pids",
            "items": [
                {
                    "name": "session_worker",
                    "label": "세션 워커",
                    "tier": "worker",
                    "watchdog_pid_file": None,
                    "worker_pid_file": "session_worker.pid",
                },
            ]
        }
    },
    "ollama": {
        "path": None,
        "nssm_prefix": None,
        "startup_prefix": "Ollama",
        "task_folder": None,
        "workers": None
    },
    "system": {
        "path": None,
        "nssm_prefix": None,
        "startup_prefix": None,
        "task_folder": None,
        "workers": None,
        "nssm_services": ["cloudflared"]
    }
}
