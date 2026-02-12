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
                    "watchdog_pid_file": "worker_watchdog_dev.pid",
                    "worker_pid_file": "unified_worker_dev.pid",
                },
                {
                    "name": "claude_worker",
                    "label": "Claude 워커",
                    "watchdog_pid_file": "claude_watchdog_dev.pid",
                    "worker_pid_file": "claude_worker_dev.pid",
                },
                {
                    "name": "video_download",
                    "label": "동영상 다운로드",
                    "watchdog_pid_file": "video_download_watchdog_dev.pid",
                    "worker_pid_file": "video_download_worker_dev.pid",
                },
                {
                    "name": "command_listener",
                    "label": "명령 리스너",
                    "watchdog_pid_file": None,
                    "worker_pid_file": "command_listener_dev.pid",
                },
                {
                    "name": "api_watchdog",
                    "label": "API 왓치독",
                    "watchdog_pid_file": "api_watchdog_dev.pid",
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
        "startup_prefix": None,
        "task_folder": "SleepNow",
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
