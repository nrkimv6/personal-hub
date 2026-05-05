from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_E2E_DIR = PROJECT_ROOT / "tests" / "e2e" / "frontend"
E2E_DIR = PROJECT_ROOT / "tests" / "e2e"
ARCHIVE_RETRIEVAL_E2E = FRONTEND_E2E_DIR / "test_plan_archive_retrieval_surface_e2e.py"


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _is_playwright_locator_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "locator" or node.func.attr.startswith("get_by_"):
            return True
        return _is_playwright_locator_expression(node.func.value)
    if isinstance(node, ast.Attribute):
        return _is_playwright_locator_expression(node.value)
    return False


def _first_call_misuses(path: Path) -> list[tuple[int, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    misuses: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "first"
            and _is_playwright_locator_expression(node.func.value)
        ):
            misuses.append((node.lineno, node.col_offset))
    return misuses


def _source_contract_failures(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        for line, col in _first_call_misuses(path):
            rel = path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path
            failures.append(f"{rel}:{line}:{col}: Playwright Locator.first is a property; use `.first`")
    return failures


def _has_exact_text_assertion(path: Path, text: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "get_by_text":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != text:
            continue
        for keyword in node.keywords:
            if keyword.arg == "exact" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return True
    return False


def test_playwright_frontend_e2e_does_not_call_locator_first():
    failures = _source_contract_failures(_iter_python_files(E2E_DIR))
    assert not failures, "\n".join(failures)


def test_locator_first_contract_allows_property_usage(tmp_path: Path):
    fixture = tmp_path / "test_locator_first_property.py"
    fixture.write_text(
        """
from playwright.sync_api import expect


def test_example(page):
    expect(page.get_by_text("ready").first).to_be_visible()
""",
        encoding="utf-8",
    )

    assert _source_contract_failures([fixture]) == []


def test_locator_first_contract_rejects_callable_usage(tmp_path: Path):
    fixture = tmp_path / "test_locator_first_call.py"
    fixture.write_text(
        """
from playwright.sync_api import expect


def test_example(page):
    expect(page.get_by_text("ready").first()).to_be_visible()
""",
        encoding="utf-8",
    )

    failures = _source_contract_failures([fixture])
    assert len(failures) == 1
    assert "Locator.first is a property" in failures[0]


def test_archive_retrieval_status_badge_uses_exact_text_assertion():
    assert _has_exact_text_assertion(ARCHIVE_RETRIEVAL_E2E, "indexed 9")
