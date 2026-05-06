"""Static overwrite-block gate for merge lifecycle keys.

Axis map:
- overwrite-block: listener modules must not bypass MergePersistence for
  merge_status, merge_reason, merge_message, or merge_requested writes.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PLAN_RUNNER_DIR = ROOT / "scripts" / "plan_runner"
ALLOWLIST = {"_dr_merge_persistence.py"}


def _scan_direct_lifecycle_writes():
    patterns = (
        re.compile(r"\.set\([^\n]*:(merge_status|merge_reason|merge_message|merge_requested)"),
        re.compile(r"\.delete\([^\n]*:(merge_status|merge_reason|merge_message|merge_requested)"),
    )
    offenders = []
    for path in PLAN_RUNNER_DIR.glob("_dr_*.py"):
        if path.name in ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(source.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                offenders.append(f"{path.name}:{line_no}:{line.strip()}")
    listener = PLAN_RUNNER_DIR / "dev-runner-command-listener.py"
    source = listener.read_text(encoding="utf-8")
    for line_no, line in enumerate(source.splitlines(), start=1):
        if any(pattern.search(line) for pattern in patterns):
            offenders.append(f"{listener.name}:{line_no}:{line.strip()}")
    return offenders


def test_merge_lifecycle_writes_go_through_persistence_chokepoint():
    assert _scan_direct_lifecycle_writes() == []
