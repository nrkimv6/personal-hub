"""NSSM 호환 리다이렉트 스텁.

scripts/ 재구성(2026-04-12) 이후 실제 파일은 scripts/services/service_run.py 에 위치.
NSSM AppParameters 업데이트 전까지 이 스텁을 통해 실제 스크립트를 실행한다.

업데이트 방법 (관리자 권한 PowerShell):
    nssm set MonitorPage-Admin AppParameters "D:\\work\\project\\tools\\monitor-page\\scripts\\services\\service_run.py --admin"
    nssm set MonitorPage-Public AppParameters "D:\\work\\project\\tools\\monitor-page\\scripts\\services\\service_run.py"
    nssm restart MonitorPage-Admin
    nssm restart MonitorPage-Public
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

_real = os.path.join(_root, "scripts", "services", "service_run.py")
with open(_real, encoding="utf-8") as _f:
    exec(compile(_f.read(), _real, "exec"))  # noqa: S102
