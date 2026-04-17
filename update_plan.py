
import sys
from pathlib import Path

plan_path = Path(r".worktrees\plans\docs\plan\2026-04-16_fix-process-watch-worker-periodic-pg-coverage-gap.md")
content = plan_path.read_text(encoding="utf-8")

# 1. Add Orchestrator supervision task to Phase 1
old_orch = '`app/worker/orchestrator.py`: `OrphanDetector.run_periodic()`媛'
new_orch = '`app/worker/orchestrator.py`: `OrphanDetector.run_periodic()` task가 예외로 중단될 경우 감시/재시작하는 로직 추가 및'

if old_orch in content:
    content = content.replace(old_orch, new_orch)

# 2. Update fingerprints in Phase 1
old_fp = '`DatatypeMismatch`, `:window::interval` syntax error, `idx_pws_captured_at` deadlock fingerprint'
new_fp = '`DatatypeMismatch` (fingerprints: `26644c17...`, `bdc03bc2...`), `:window::interval` syntax error, `idx_pws_captured_at` deadlock fingerprints를 최신 로그 기준으로 보완.'

if old_fp in content:
    content = content.replace(old_fp, new_fp)

# 3. Add CAST/bindparam task to Phase 2
old_bp = 'helper/cache瑜 由ы.'
new_bp = 'helper/cache를 보완하고, Boolean 필드 insert 시 `CAST(:is_orphan AS BOOLEAN)`를 명시하여 PG DatatypeMismatch를 원천 차단.'

if old_bp in content:
    content = content.replace(old_bp, new_bp)

plan_path.write_text(content, encoding="utf-8")
print("Plan updated successfully.")
