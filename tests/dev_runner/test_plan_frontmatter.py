"""plan_frontmatter 유틸 단위 테스트."""
import pytest
from pathlib import Path
from app.modules.dev_runner.services.plan_frontmatter import (
    read_frontmatter,
    write_frontmatter_field,
    read_auto_run_meta,
    read_claim_id,
    write_claim_id,
    clear_claim_id,
    AUTO_RUN_SCOPES,
    CLAIM_HEADER_KEY,
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


# ── 실행점유 헤더 (write_claim_id / read_claim_id / clear_claim_id) ──────────

_SAMPLE_HEADER = """\
> 상태: 구현중
> branch: impl/test
> worktree: .worktrees/impl-test
> worktree-owner: .worktrees/impl-test

---

# feat: 테스트 계획서

## TODO

- [ ] 항목 1
"""


def test_write_claim_id_R_adds_new_field(tmp_path):
    """R: 기존 헤더에 실행점유 필드가 없으면 추가된다"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER, encoding="utf-8")
    write_claim_id(p, "aaaa-bbbb-cccc")
    content = p.read_text(encoding="utf-8")
    assert f"> {CLAIM_HEADER_KEY}: aaaa-bbbb-cccc" in content


def test_write_claim_id_R_updates_existing_field(tmp_path):
    """R: 이미 실행점유 필드가 있으면 값을 갱신한다"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER + f"\n> {CLAIM_HEADER_KEY}: old-id\n", encoding="utf-8")
    write_claim_id(p, "new-id-xyz")
    content = p.read_text(encoding="utf-8")
    assert f"> {CLAIM_HEADER_KEY}: new-id-xyz" in content
    assert "old-id" not in content


def test_write_claim_id_Co_preserves_other_header_fields(tmp_path):
    """Co: write_claim_id 후 기존 blockquote 필드가 그대로 남는다"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER, encoding="utf-8")
    write_claim_id(p, "claim-123")
    content = p.read_text(encoding="utf-8")
    assert "> 상태: 구현중" in content
    assert "> branch: impl/test" in content
    assert "> worktree-owner: .worktrees/impl-test" in content


def test_write_claim_id_Co_does_not_duplicate_field(tmp_path):
    """Co: 동일 필드를 두 번 써도 중복 줄이 생기지 않는다"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER, encoding="utf-8")
    write_claim_id(p, "id-first")
    write_claim_id(p, "id-second")
    content = p.read_text(encoding="utf-8")
    count = content.count(f"> {CLAIM_HEADER_KEY}:")
    assert count == 1, f"실행점유 필드 중복 기록: {count}개"
    assert "id-second" in content
    assert "id-first" not in content


def test_read_claim_id_R_reads_written_value(tmp_path):
    """R: write_claim_id → read_claim_id 왕복 검증"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER, encoding="utf-8")
    write_claim_id(p, "round-trip-id")
    result = read_claim_id(p)
    assert result == "round-trip-id"


def test_read_claim_id_B_returns_none_when_absent(tmp_path):
    """B: 실행점유 필드 없으면 None 반환"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER, encoding="utf-8")
    assert read_claim_id(p) is None


def test_read_claim_id_E_returns_none_on_missing_file(tmp_path):
    """E: 파일 없으면 None 반환 (예외 없음)"""
    p = tmp_path / "nonexistent.md"
    assert read_claim_id(p) is None


def test_clear_claim_id_R_sets_empty_value(tmp_path):
    """R: clear_claim_id → 빈 값으로 초기화 (필드 자체는 유지)"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER, encoding="utf-8")
    write_claim_id(p, "to-be-cleared")
    clear_claim_id(p)
    content = p.read_text(encoding="utf-8")
    assert f"> {CLAIM_HEADER_KEY}:" in content
    assert "to-be-cleared" not in content


def test_clear_claim_id_B_read_after_clear_returns_none(tmp_path):
    """B: clear 후 read_claim_id는 None을 반환한다"""
    p = tmp_path / "plan.md"
    p.write_text(_SAMPLE_HEADER, encoding="utf-8")
    write_claim_id(p, "some-id")
    clear_claim_id(p)
    assert read_claim_id(p) is None


def test_write_claim_id_B_header_only_no_separator(tmp_path):
    """B: --- 구분자 없는 plan 파일에도 정상 삽입된다"""
    content = "> 상태: 초안\n> branch: impl/test\n\n# Title\n"
    p = tmp_path / "plan.md"
    p.write_text(content, encoding="utf-8")
    write_claim_id(p, "no-sep-id")
    result = p.read_text(encoding="utf-8")
    assert f"> {CLAIM_HEADER_KEY}: no-sep-id" in result
    assert "> 상태: 초안" in result
