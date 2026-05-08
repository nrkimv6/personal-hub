"""Dev-runner cleanup regression for Plan Archive mapper initialization."""

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cleanup_subprocess(tmp_path: Path, *, repeat: int = 1) -> subprocess.CompletedProcess[str]:
    db_path = tmp_path / "cleanup_mapper.sqlite"
    plan_path = tmp_path / "plan.md"
    code = f"""
import logging
import sys
from pathlib import Path

import fakeredis

scripts_dir = Path({str(REPO_ROOT / "scripts")!r})
plan_runner_dir = scripts_dir / "plan_runner"
sys.path.insert(0, str(scripts_dir))
sys.path.insert(0, str(plan_runner_dir))

import app.models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.models.plan_execution_claim import PlanExecutionClaim
from app.modules.dev_runner.services.executor_service import ACTIVE_RUNNERS_KEY, RUNNER_KEY_PREFIX, RUNNER_KEY_SUFFIXES
from tests.dev_runner._path_helpers import bootstrap_plan_runner_modules

Base.metadata.create_all(bind=engine)
plan_path = Path({str(plan_path)!r})
plan_path.write_text("> 실행점유: claim-reconnect-mapper\\n", encoding="utf-8")
runner_id = "t-reconnect-mapper"
claim_id = "claim-reconnect-mapper"

db = SessionLocal()
db.add(PlanExecutionClaim(claim_id=claim_id, plan_path=str(plan_path), state="active", runner_id=runner_id))
db.commit()
db.close()

_, process_utils_mod = bootstrap_plan_runner_modules()
r = fakeredis.FakeRedis(decode_responses=True)
for suffix in RUNNER_KEY_SUFFIXES:
    r.set(f"{{RUNNER_KEY_PREFIX}}:{{runner_id}}:{{suffix}}", f"val_{{suffix}}")
r.set(f"{{RUNNER_KEY_PREFIX}}:{{runner_id}}:plan_file", str(plan_path))
r.set(f"{{RUNNER_KEY_PREFIX}}:{{runner_id}}:trigger", "user")
r.set(f"{{RUNNER_KEY_PREFIX}}:{{runner_id}}:merge_requested", "1")
r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

records = []

class Capture(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())

logger = logging.getLogger("_dr_process_utils")
logger.addHandler(Capture())
logger.setLevel(logging.INFO)

for _ in range({repeat}):
    process_utils_mod._cleanup_process_state(runner_id, r, reason="reconnect_orphan_scan")

db = SessionLocal()
state = db.query(PlanExecutionClaim.state).filter(PlanExecutionClaim.claim_id == claim_id).scalar()
db.close()

messages = "\\n".join(records)
assert "failed to locate a name ('LLMRequest')" not in messages
assert "LLMRequest" not in messages
assert state == "released", state
print(state)
"""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def test_reconnect_orphan_cleanup_release_no_mapper_warning_E(tmp_path: Path) -> None:
    result = _run_cleanup_subprocess(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "released" in result.stdout


def test_reconnect_orphan_cleanup_idempotent_Re(tmp_path: Path) -> None:
    result = _run_cleanup_subprocess(tmp_path, repeat=2)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "released" in result.stdout
