"""Source contracts for E2E readiness helpers."""

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SMOKE = PROJECT_ROOT / "tests" / "e2e" / "frontend" / "test_llm_scheduler_runtime.py"
E2E_CONFTEST = PROJECT_ROOT / "tests" / "e2e" / "conftest.py"


def _function_node(source: str, name: str) -> ast.FunctionDef:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} function not found")


def _string_constants(node: ast.AST) -> set[str]:
    return {child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)}


def test_runtime_smoke_does_not_wait_for_networkidle():
    source = RUNTIME_SMOKE.read_text(encoding="utf-8")

    assert '"networkidle"' not in source
    assert "wait_for_load_state(\"networkidle\")" not in source


def test_runtime_smoke_uses_route_level_readiness_contracts():
    source = RUNTIME_SMOKE.read_text(encoding="utf-8")

    assert "_wait_for_llm_runtime_ready" in source
    assert "_wait_for_scheduler_runtime_ready" in source
    assert "_wait_for_system_settings_ready" in source
    assert "_wait_for_any_visible" in source


def test_wait_for_app_ready_uses_dom_and_locator_contract():
    source = E2E_CONFTEST.read_text(encoding="utf-8")
    wait_for_app_ready = _function_node(source, "wait_for_app_ready")
    constants = _string_constants(wait_for_app_ready)

    assert "networkidle" not in constants
    assert "domcontentloaded" in constants
    assert "main" in constants
    assert "[data-sveltekit-hydrated]" in constants
