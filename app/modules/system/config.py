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
                {"name": "monitor_watchdog", "pid_file": "watchdog_dev.pid"},
                {"name": "instagram_watchdog", "pid_file": "instagram_watchdog_dev.pid"},
                {"name": "api_watchdog", "pid_file": "api_watchdog_dev.pid"},
                {"name": "claude_watchdog", "pid_file": "claude_watchdog_dev.pid"},
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
