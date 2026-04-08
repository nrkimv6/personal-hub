"""dumptruck_builder.py 단위 TC (RIGHT-BICEP)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ 디렉토리를 sys.path에 추가하여 dumptruck_builder 임포트
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import dumptruck_builder as db


# ──────────────────────────────────────────────────────────────────────────────
# collect_files TC
# ──────────────────────────────────────────────────────────────────────────────

class TestCollectFiles:
    def test_collect_files_R_basic(self, tmp_path, monkeypatch):
        """R: 임시 디렉토리에 .py/.md 생성 후 collect_files 결과에 .py 파일 포함."""
        # 프로젝트 루트를 tmp_path로 monkeypatch
        monkeypatch.setattr(db, "PROJECT_ROOT", tmp_path)

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
        (tmp_path / "README.md").write_text("# readme", encoding="utf-8")

        result = db.collect_files(["**/*.py"], [])
        names = [p.name for p in result]
        assert "main.py" in names
        assert all(p.suffix == ".py" for p in result)

    def test_collect_files_B_excludes_default_dirs(self, tmp_path, monkeypatch):
        """B: .git/, __pycache__/, node_modules/ 자동 제외 검증."""
        monkeypatch.setattr(db, "PROJECT_ROOT", tmp_path)

        for excluded_dir in [".git", "__pycache__", "node_modules", ".venv", "data"]:
            d = tmp_path / excluded_dir
            d.mkdir()
            (d / "file.py").write_text("x=1", encoding="utf-8")

        # 일반 파일도 추가
        (tmp_path / "app.py").write_text("app=True", encoding="utf-8")

        result = db.collect_files(["**/*.py"], [])
        names = [p.name for p in result]
        # 제외 디렉토리 내 파일은 없어야 함
        paths_str = [str(p) for p in result]
        for excluded in [".git", "__pycache__", "node_modules", ".venv", "data"]:
            assert not any(excluded in s for s in paths_str), f"{excluded} 파일이 수집됨"
        assert "app.py" in names


# ──────────────────────────────────────────────────────────────────────────────
# estimate_tokens TC
# ──────────────────────────────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_estimate_tokens_R_simple(self):
        """R: 알려진 길이 문자열의 토큰 추정값이 합리적 범위 (len//4)."""
        text = "A" * 400
        result = db.estimate_tokens(text)
        # 400 // 4 = 100
        assert result == 100

    def test_estimate_tokens_B_empty(self):
        """B: 빈 문자열 → 0."""
        assert db.estimate_tokens("") == 0

    def test_estimate_tokens_R_long_text(self):
        """R: 긴 텍스트에서 len//4 공식 확인."""
        text = "hello world " * 1000  # 12000자
        expected = len(text) // 4
        assert db.estimate_tokens(text) == expected


# ──────────────────────────────────────────────────────────────────────────────
# main() TC
# ──────────────────────────────────────────────────────────────────────────────

class TestMain:
    def _make_oversized_setup(self, tmp_path, monkeypatch):
        """임계 초과 텍스트를 생성하는 공통 헬퍼."""
        monkeypatch.setattr(db, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(db, "TEMPLATES_DIR", tmp_path / "templates")
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "architecture.md").write_text("# 아키텍처 분석\n", encoding="utf-8")

        # 임계(TOKEN_LIMIT = 1_500_000) 초과하는 파일 생성 (4 * 1_500_001 = 6_000_004자)
        big_file = tmp_path / "big.py"
        big_file.write_text("x" * (4 * db.TOKEN_LIMIT + 1), encoding="utf-8")
        return tmp_path

    def test_main_E_oversize_without_force(self, tmp_path, monkeypatch):
        """E: 임계 초과 입력 + --force 없음 → SystemExit(2)."""
        self._make_oversized_setup(tmp_path, monkeypatch)
        out_file = tmp_path / "out.txt"

        with pytest.raises(SystemExit) as exc_info:
            monkeypatch.setattr(
                sys, "argv",
                ["dumptruck_builder.py", "--template", "architecture",
                 "--include", "**/*.py", "--out", str(out_file)]
            )
            db.main()
        assert exc_info.value.code == 2

    def test_main_R_oversize_with_force(self, tmp_path, monkeypatch):
        """R: --force 시 임계 초과여도 정상 출력 파일 생성."""
        self._make_oversized_setup(tmp_path, monkeypatch)
        out_file = tmp_path / "out.txt"

        monkeypatch.setattr(
            sys, "argv",
            ["dumptruck_builder.py", "--template", "architecture",
             "--include", "**/*.py", "--out", str(out_file), "--force"]
        )
        db.main()
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert len(content) > 0


# ──────────────────────────────────────────────────────────────────────────────
# load_template TC
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadTemplate:
    def test_load_template_E_unknown_name(self, monkeypatch, tmp_path):
        """E: 존재하지 않는 템플릿 이름 → FileNotFoundError."""
        monkeypatch.setattr(db, "TEMPLATES_DIR", tmp_path / "no_templates")
        with pytest.raises(FileNotFoundError):
            db.load_template("nonexistent_template")

    def test_load_template_R_existing(self, monkeypatch, tmp_path):
        """R: 존재하는 템플릿 파일 → 내용 반환."""
        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "architecture.md").write_text("# 아키텍처\n질문 내용", encoding="utf-8")
        monkeypatch.setattr(db, "TEMPLATES_DIR", tmpl_dir)
        result = db.load_template("architecture")
        assert "아키텍처" in result


# ──────────────────────────────────────────────────────────────────────────────
# Phase T3: 통합 TC (실제 파일시스템, mock 없음)
# ──────────────────────────────────────────────────────────────────────────────

class TestIntegration:
    """실제 프로젝트 파일과 템플릿을 사용하는 통합 TC."""

    REAL_REGISTRY = SCRIPTS_DIR.parent / "app" / "shared" / "llm_registry.py"

    def test_main_integration_real_repo_subset(self, tmp_path):
        """T3-R: 실제 llm_registry.py 1개 파일 include → 출력에 코드 블록 + 트리 포함."""
        # 실제 파일이 존재해야 의미 있는 TC
        assert self.REAL_REGISTRY.exists(), f"파일 없음: {self.REAL_REGISTRY}"

        out_file = tmp_path / "out.md"
        old_argv = sys.argv
        try:
            sys.argv = [
                "dumptruck_builder.py",
                "--template", "architecture",
                "--include", "app/shared/llm_registry.py",
                "--out", str(out_file),
            ]
            db.main()
        finally:
            sys.argv = old_argv

        assert out_file.exists(), "출력 파일이 생성되지 않음"
        content = out_file.read_text(encoding="utf-8")

        # 파일 내용 블록 포함 여부 (언어 블록 헤더 또는 경로)
        assert "llm_registry" in content, "llm_registry 경로/이름이 출력에 없음"
        # ASCII 트리 출력 포함 여부
        assert "llm_registry.py" in content

    def test_main_integration_template_header_present(self, tmp_path):
        """T3-R: --template architecture 출력에 실제 architecture.md 헤더 텍스트 포함."""
        # 실제 템플릿 파일 존재 확인
        tmpl_file = SCRIPTS_DIR / "dumptruck_templates" / "architecture.md"
        assert tmpl_file.exists(), f"템플릿 없음: {tmpl_file}"

        # 템플릿 첫 줄 추출
        first_line = tmpl_file.read_text(encoding="utf-8").splitlines()[0]

        out_file = tmp_path / "out_arch.md"
        old_argv = sys.argv
        try:
            sys.argv = [
                "dumptruck_builder.py",
                "--template", "architecture",
                "--include", "app/shared/llm_registry.py",
                "--out", str(out_file),
            ]
            db.main()
        finally:
            sys.argv = old_argv

        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        # 템플릿 첫 줄이 출력에 포함되어야 함
        assert first_line in content, f"템플릿 헤더 '{first_line}'가 출력에 없음"
