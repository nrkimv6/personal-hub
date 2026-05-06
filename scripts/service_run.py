"""Stable NSSM bootstrap for the Monitor Page service runner.

NSSM should point at this low-churn file:
    nssm set MonitorPage-Admin AppParameters "D:\\work\\project\\tools\\monitor-page\\scripts\\service_run.py --admin"
    nssm set MonitorPage-Public AppParameters "D:\\work\\project\\tools\\monitor-page\\scripts\\service_run.py"
    nssm restart MonitorPage-Admin
    nssm restart MonitorPage-Public
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set the mode before importing the heavier runner module so import-time config
# readers see the same mode as direct scripts/services/service_run.py execution.
os.environ["APP_MODE"] = "admin" if "--admin" in sys.argv[1:] else "public"
os.environ["MONITOR_SERVICE_RUN_ENTRY_SCRIPT"] = str(Path(__file__).resolve())

from scripts.services.service_run import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
