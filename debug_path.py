from pathlib import Path
from app.modules.dev_runner.services.plan_path_resolver import resolve_plan_target

tmp_path = Path("C:/Temp/pytest-of-Narang/pytest-0/test_cleanup_stale_auto_history0") # Example path
plan_file = tmp_path / "docs" / "plan" / "2026-04-03_auto-next.md"
target = resolve_plan_target(plan_file, purpose="archive")
print(f"Source: {target.source}")
print(f"Target: {target.target}")
print(f"Rule: {target.rule_id}")
