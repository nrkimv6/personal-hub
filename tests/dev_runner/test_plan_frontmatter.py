"""plan_frontmatter 유틸 단위 테스트."""
import pytest
from pathlib import Path
from app.modules.dev_runner.services.plan_frontmatter import (
    read_frontmatter,
    write_frontmatter_field,
    read_auto_run_meta,
    AUTO_RUN_SCOPES,
)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test_plan.md"
    p.write_text(content, encoding="utf-8")
    return p


# ── read_frontmatter ──────────────────────────────────────────────────────────

def test_read_frontmatter_R_blockquote_format(tmp_path):
    """blockquote 형식 정상 파싱"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: tc\n\n# Title\n")
    result = read_frontmatter(p)
    assert result["auto_run"] == "true"
    assert result["auto_run_scope"] == "tc"


def test_read_frontmatter_R_yaml_block(tmp_path):
    """--- YAML 블록 형식 파싱 (yaml safe_load는 true→True, str()→'True')"""
    p = _write(tmp_path, "---\nauto_run: true\nauto_run_scope: docs\n---\n# Title\n")
    result = read_frontmatter(p)
    # yaml.safe_load converts `true` → Python bool True → str(True) = "True"
    assert result.get("auto_run") == "True"
    assert result.get("auto_run_scope") == "docs"


def test_read_frontmatter_B_missing_field(tmp_path):
    """존재하지 않는 필드는 None 반환"""
    p = _write(tmp_path, "> auto_run: true\n\n# Title\n")
    result = read_frontmatter(p)
    assert result.get("auto_run_scope") is None


def test_read_frontmatter_E_malformed(tmp_path):
    """잘못된 형식의 파일 — 빈 dict 반환, 예외 없음"""
    p = _write(tmp_path, "이건 blockquote도 yaml도 아님\n\n# Title\n")
    result = read_frontmatter(p)
    assert isinstance(result, dict)


def test_read_frontmatter_E_nonexistent_file(tmp_path):
    """존재하지 않는 파일 — 빈 dict 반환"""
    p = tmp_path / "missing.md"
    result = read_frontmatter(p)
    assert result == {}


# ── write_frontmatter_field ───────────────────────────────────────────────────

def test_write_frontmatter_field_R_add_new_key(tmp_path):
    """새 키 추가"""
    p = _write(tmp_path, "> auto_run: true\n\n# Title\n")
    write_frontmatter_field(p, "auto_run_status", "completed")
    content = p.read_text(encoding="utf-8")
    assert "auto_run_status: completed" in content


def test_write_frontmatter_field_R_update_existing(tmp_path):
    """기존 키 값 업데이트"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_status: running\n\n# Title\n")
    write_frontmatter_field(p, "auto_run_status", "completed")
    content = p.read_text(encoding="utf-8")
    assert "auto_run_status: completed" in content
    assert "auto_run_status: running" not in content


def test_write_frontmatter_field_Co_preserves_other_lines(tmp_path):
    """다른 frontmatter 줄 보존"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: tc\n\n# Title\n")
    write_frontmatter_field(p, "auto_run_status", "completed")
    content = p.read_text(encoding="utf-8")
    assert "> auto_run: true" in content
    assert "> auto_run_scope: tc" in content
    assert "# Title" in content


# ── read_auto_run_meta ────────────────────────────────────────────────────────

def test_read_auto_run_meta_R_returns_subset(tmp_path):
    """auto_run 관련 필드만 반환"""
    p = _write(tmp_path, "> auto_run: true\n> auto_run_scope: safe-fix\n> 상태: 초안\n\n# Title\n")
    meta = read_auto_run_meta(p)
    assert meta["auto_run"] == "true"
    assert meta["auto_run_scope"] == "safe-fix"


# ── AUTO_RUN_SCOPES ───────────────────────────────────────────────────────────

def test_auto_run_scopes_contains_required_values():
    """허용 scope 셋이 tc/docs/safe-fix를 포함"""
    assert "tc" in AUTO_RUN_SCOPES
    assert "docs" in AUTO_RUN_SCOPES
    assert "safe-fix" in AUTO_RUN_SCOPES
