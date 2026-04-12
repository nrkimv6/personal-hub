"""
단위 TC: scripts/ci/check_frontend_provider_hardcoding.py

RIGHT-BICEP:
- R: provider 하드코딩 옵션 포함 svelte 파일 → 감지 (True)
- R: 동적 렌더링 svelte 파일 → 통과 (False)
- B: 빈 svelte 파일 → 통과
- B: 화이트리스트에 있는 파일 → 통과
- E: frontend-dir 없음 → exit 1
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_CI = Path(__file__).parent.parent / "scripts" / "ci"
sys.path.insert(0, str(_SCRIPTS_CI))

from check_frontend_provider_hardcoding import check_file, main


class TestCheckFile:
    def test_R_detects_hardcoded_claude_option(self, tmp_path):
        """R: <option value="claude"> → 감지."""
        f = tmp_path / "LlmTab.svelte"
        f.write_text('<option value="claude">Claude</option>\n')
        hits = check_file(f)
        assert len(hits) == 1
        assert "claude" in hits[0][1]

    def test_R_detects_hardcoded_gemini_option(self, tmp_path):
        """R: <option value='gemini'> → 감지."""
        f = tmp_path / "Tab.svelte"
        f.write_text("<option value='gemini'>Gemini</option>\n")
        hits = check_file(f)
        assert len(hits) == 1

    def test_R_detects_hardcoded_codex_option(self, tmp_path):
        """R: <option value="codex"> → 감지."""
        f = tmp_path / "Tab.svelte"
        f.write_text('<option value="codex">Codex</option>\n')
        hits = check_file(f)
        assert len(hits) == 1

    def test_R_dynamic_render_not_detected(self, tmp_path):
        """R: 동적 렌더링 패턴 → 감지 안 함."""
        f = tmp_path / "LlmTab.svelte"
        content = """\
{#each providers as p}
  <option value={p.key}>{p.display_name}</option>
{/each}
"""
        f.write_text(content)
        hits = check_file(f)
        assert hits == []

    def test_B_empty_file_returns_empty(self, tmp_path):
        """B: 빈 파일 → 빈 결과."""
        f = tmp_path / "Empty.svelte"
        f.write_text("")
        hits = check_file(f)
        assert hits == []


class TestMain:
    def test_R_detects_hardcoded_exits_1(self, tmp_path):
        """R: 하드코딩 포함 파일 → exit 1."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "Tab.svelte").write_text('<option value="claude">Claude</option>\n')
        result = main(["--frontend-dir", str(src)])
        assert result == 1

    def test_R_clean_directory_exits_0(self, tmp_path):
        """R: 동적 렌더링만 있는 디렉토리 → exit 0."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "Tab.svelte").write_text("{#each providers as p}<option value={p.key}>{p.display_name}</option>{/each}\n")
        result = main(["--frontend-dir", str(src)])
        assert result == 0

    def test_B_whitelisted_file_skipped(self, tmp_path):
        """B: 화이트리스트에 있는 파일 → 건너뜀, exit 0."""
        src = tmp_path / "src"
        src.mkdir()
        bad_file = src / "Legacy.svelte"
        bad_file.write_text('<option value="claude">Claude</option>\n')

        whitelist_file = tmp_path / ".whitelist"
        whitelist_file.write_text("Legacy.svelte\n")

        result = main(["--frontend-dir", str(src), "--whitelist-file", str(whitelist_file)])
        assert result == 0

    def test_E_missing_frontend_dir_exits_1(self, tmp_path):
        """E: frontend-dir 없음 → exit 1."""
        result = main(["--frontend-dir", str(tmp_path / "nonexistent")])
        assert result == 1
