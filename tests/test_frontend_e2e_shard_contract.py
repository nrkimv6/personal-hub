"""Frontend E2E shard contract tests.

These tests are intentionally non-E2E: they validate selection metadata and
operational documentation without importing Playwright or touching live services.
"""

from __future__ import annotations

from pathlib import Path

from scripts.tests_scripts.frontend_e2e_shards import (
    FRONTEND_E2E_SHARDS,
    default_evidence_commands,
    is_broad_frontend_e2e_command,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DOC = PROJECT_ROOT / "docs" / "dev-guide" / "frontend-e2e-shard-contract.md"


def test_default_frontend_e2e_evidence_uses_explicit_files_only():
    commands = default_evidence_commands()

    assert commands
    assert any("test_dev_runner_live_log_fallback_e2e.py" in command for command in commands)
    for command in commands:
        assert not is_broad_frontend_e2e_command(command), command
        assert "tests\\e2e\\frontend\\" in command, command
        assert command.endswith(" -v"), command


def test_frontend_e2e_shard_files_exist_and_stay_in_frontend_directory():
    seen_ids: set[str] = set()

    for shard in FRONTEND_E2E_SHARDS:
        assert shard.shard_id not in seen_ids
        seen_ids.add(shard.shard_id)
        assert shard.expected_max_seconds > 0
        assert shard.files
        for file_name in shard.files:
            path = PROJECT_ROOT / file_name
            assert path.is_file(), file_name
            assert path.parent == PROJECT_ROOT / "tests" / "e2e" / "frontend"


def test_contract_doc_lists_manifest_shards_and_commands():
    text = CONTRACT_DOC.read_text(encoding="utf-8")

    assert "frontend E2E directory is a long-run diagnostic target" in text
    assert "scripts/tests_scripts/frontend_e2e_shards.py" in text
    for shard in FRONTEND_E2E_SHARDS:
        assert f"`{shard.shard_id}`" in text
        assert f"`{shard.command}`" in text


def test_operational_docs_and_helpers_do_not_offer_broad_frontend_e2e_default():
    scan_roots = (
        PROJECT_ROOT / "docs" / "dev-guide",
        PROJECT_ROOT / "scripts",
        PROJECT_ROOT / "tests",
    )
    suffixes = {".md", ".py", ".ps1", ".txt"}
    violations: list[str] = []

    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if path == Path(__file__).resolve():
                continue
            if path == PROJECT_ROOT / "scripts" / "tests_scripts" / "frontend_e2e_shards.py":
                continue
            if PROJECT_ROOT / "tests" / "e2e" / "frontend" in path.parents:
                continue

            text = path.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if "pytest" not in line:
                    continue
                if is_broad_frontend_e2e_command(line):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{line_no}: {line.strip()}")

    assert violations == []
