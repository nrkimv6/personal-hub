"""auto_run_validator 단위 테스트."""
import pytest
from pathlib import Path
from app.modules.dev_runner.services.auto_run_validator import validate_scope


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "2026-04-25_test-plan.md"
    p.write_text(content, encoding="utf-8")
    return p


# ── scope=tc ──────────────────────────────────────────────────────────────────

def test_validate_scope_R_tc_only_test_files(tmp_path):
    """tc scope + tests/ 경로만 → 의심 없음"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: tc\n\n"
               "- [ ] `tests/dev_runner/test_foo.py` 수정\n"
               "- [ ] `tests/utils/test_bar.py` 추가\n")
    result = validate_scope(p, "tc")
    assert result == []


def test_validate_scope_E_tc_with_app_change(tmp_path):
    """tc scope + app/ 경로 포함 → 의심 발생"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: tc\n\n"
               "- [ ] `app/modules/foo/service.py` 수정\n")
    result = validate_scope(p, "tc")
    assert len(result) >= 1
    assert "app/modules/foo/service.py" in result[0]


def test_validate_scope_R_tc_test_prefix_py(tmp_path):
    """tc scope + test_xxx.py 패턴 → 의심 없음"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: tc\n\n"
               "- [ ] `test_something.py` 추가\n")
    result = validate_scope(p, "tc")
    assert result == []


def test_validate_scope_B_tc_mixed_hints(tmp_path):
    """tc scope + test 파일과 app 파일 혼합 → app 파일만 의심"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: tc\n\n"
               "- [ ] `tests/test_ok.py` 수정\n"
               "- [ ] `app/routes/main.py` 수정\n")
    result = validate_scope(p, "tc")
    assert len(result) == 1
    assert "app/routes/main.py" in result[0]


# ── scope=docs ────────────────────────────────────────────────────────────────

def test_validate_scope_R_docs_md_only(tmp_path):
    """docs scope + .md 파일만 → 의심 없음"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: docs\n\n"
               "- [ ] `docs/guide/README.md` 수정\n"
               "- [ ] `CHANGELOG.md` 업데이트\n")
    result = validate_scope(p, "docs")
    assert result == []


def test_validate_scope_E_docs_with_py_change(tmp_path):
    """docs scope + .py 파일 포함 → 의심 발생"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: docs\n\n"
               "- [ ] `app/utils/helper.py` 수정\n")
    result = validate_scope(p, "docs")
    assert len(result) >= 1


# ── scope=safe-fix ─────────────────────────────────────────────────────────────

def test_validate_scope_R_safe_fix_skips(tmp_path):
    """safe-fix scope → 항상 빈 리스트"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: safe-fix\n\n"
               "- [ ] `app/modules/billing/service.py` 수정\n")
    result = validate_scope(p, "safe-fix")
    assert result == []


# ── 에러 경로 ──────────────────────────────────────────────────────────────────

def test_validate_scope_E_invalid_scope(tmp_path):
    """허용되지 않는 scope → 에러 메시지"""
    p = _write(tmp_path, "content")
    result = validate_scope(p, "unknown-scope")
    assert len(result) == 1
    assert "허용 값" in result[0]


def test_validate_scope_E_nonexistent_file(tmp_path):
    """존재하지 않는 파일 → 에러 메시지"""
    p = tmp_path / "missing.md"
    result = validate_scope(p, "tc")
    assert len(result) == 1
    assert "읽을 수 없습니다" in result[0]


def test_validate_scope_B_no_file_hints(tmp_path):
    """backtick 파일 힌트 없는 plan → 의심 없음"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: tc\n\n"
               "- [ ] 테스트 코드 작성\n- [ ] 검증\n")
    result = validate_scope(p, "tc")
    assert result == []
