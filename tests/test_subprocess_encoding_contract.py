"""
Windows subprocess text 인코딩 계약 회귀 TC

규칙: tests/ 내 subprocess.run(text=True) 호출은 Python/app 프로세스를 실행하는 경우
encoding="utf-8", errors="replace"를 명시해야 한다.

이 TC는 HIGH RISK 파일에서 encoding= 누락이 재발하지 않음을 정적으로 검증한다.
"""
import ast
import sys
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TESTS_ROOT.parent

# HIGH RISK: Python/app 프로세스를 직접 실행하는 파일
# encoding 누락 시 Windows cp949 → UTF-8 decode drift 발생
HIGH_RISK_FILES = [
    TESTS_ROOT / "scripts" / "test_worker_command_listener_imports.py",
    TESTS_ROOT / "dev_runner" / "test_skipif_removal_verify.py",
    TESTS_ROOT / "integration" / "test_marker_classification.py",
]


def _find_subprocess_run_calls(source: str) -> list[dict]:
    """AST로 subprocess.run 호출 위치와 키워드 인수를 추출한다."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_subprocess_run = (
            (isinstance(func, ast.Attribute) and func.attr == "run")
            or (isinstance(func, ast.Name) and func.id == "run")
        )
        if not is_subprocess_run:
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
        calls.append({"lineno": node.lineno, "kwargs": kwargs})
    return calls


@pytest.mark.parametrize("filepath", HIGH_RISK_FILES, ids=[p.name for p in HIGH_RISK_FILES])
def test_subprocess_run_has_encoding_when_text_mode(filepath: Path):
    """HIGH RISK 파일의 subprocess.run(text=True) 호출이 encoding= 를 명시한다."""
    assert filepath.exists(), f"파일이 없음: {filepath}"
    source = filepath.read_text(encoding="utf-8")
    calls = _find_subprocess_run_calls(source)

    violations = []
    for call in calls:
        if "text" in call["kwargs"] and "encoding" not in call["kwargs"]:
            violations.append(call["lineno"])

    assert not violations, (
        f"{filepath.name}: text=True이지만 encoding= 없는 subprocess.run 호출 "
        f"(line {violations}) — encoding='utf-8', errors='replace' 추가 필요"
    )


def test_subprocess_helper_has_encoding_defaults():
    """tests/helpers/subprocess_utils.py 의 run_proc 기본값에 encoding/errors 있음."""
    helper = TESTS_ROOT / "helpers" / "subprocess_utils.py"
    assert helper.exists(), "tests/helpers/subprocess_utils.py 없음"
    source = helper.read_text(encoding="utf-8")
    assert "encoding=" in source, "run_proc에 encoding= 인자 없음"
    assert "errors=" in source, "run_proc에 errors= 인자 없음"
    assert "utf-8" in source, "encoding 값이 utf-8이 아님"
    assert "replace" in source, "errors 값이 replace가 아님"
