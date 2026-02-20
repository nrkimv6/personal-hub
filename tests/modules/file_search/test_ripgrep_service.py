"""
ripgrep subprocess 서비스 단위 테스트

Right-BICEP / CORRECT 패턴:
- Right:        텍스트 검색, JSON 파싱 정확성, 대소문자 구분
- Boundary:     max_results=1, context_lines=0, 빈 extensions
- Cross-check:  regex ON/OFF 결과 차이 (args 포함 여부)
- Error:        rg 미설치, 잘못된 정규식, 빈 경로, 타임아웃
- CORRECT-Cardinality: max_results=1 정확히 1건
- CORRECT-Range:       context_lines=0 컨텍스트 없음
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.file_search.services.ripgrep import RipgrepService


# ── helpers ───────────────────────────────────────────────────────────────

def _rg_match(file_path: str, line_number: int, text: str) -> str:
    return json.dumps({
        "type": "match",
        "data": {
            "path": {"text": file_path},
            "line_number": line_number,
            "lines": {"text": text + "\n"},
            "submatches": [{"start": 0, "end": 4, "match": {"text": text[:4]}}],
        },
    })


def _rg_context(file_path: str, line_number: int, text: str) -> str:
    return json.dumps({
        "type": "context",
        "data": {
            "path": {"text": file_path},
            "line_number": line_number,
            "lines": {"text": text + "\n"},
            "submatches": [],
        },
    })


def _make_proc_mock(stdout: str, stderr: str = "", returncode: int = 0):
    """asyncio.create_subprocess_exec mock."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(
        return_value=(stdout.encode(), stderr.encode())
    )
    proc.kill = MagicMock()
    return proc


# ── Right: 정상 동작 ─────────────────────────────────────────────────────

class TestRipgrepRight:
    """Right — 올바른 결과를 반환하는지 검증."""

    @pytest.mark.asyncio
    async def test_search_single_file_match(self, rg_stdout_single):
        """Right: 파일 1개, 매칭 1건 — line_number, line_text, submatches 반환."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        proc = _make_proc_mock(rg_stdout_single)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            results = await svc.search("search", paths=["/home/user/project"])

        assert len(results) == 1
        file_result = results[0]
        assert file_result["file_name"] == "search.py"
        assert len(file_result["matches"]) == 1
        match = file_result["matches"][0]
        assert match["line_number"] == 11
        assert "search_files" in match["line_text"]

    @pytest.mark.asyncio
    async def test_search_returns_context_lines(self, rg_stdout_single):
        """Right: context_before / context_after 포함."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        proc = _make_proc_mock(rg_stdout_single)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            results = await svc.search("search", context_lines=2)

        match = results[0]["matches"][0]
        # context_before: line 9, 10 (line_number < 11)
        assert len(match["context_before"]) >= 1
        # context_after: line 12, 13
        assert len(match["context_after"]) >= 1

    @pytest.mark.asyncio
    async def test_search_case_insensitive_adds_flag(self):
        """Right: case_sensitive=False → --ignore-case 포함."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        captured_args = []

        async def fake_exec(*args, **kwargs):
            captured_args.extend(args)
            return _make_proc_mock("")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await svc.search("test", case_sensitive=False)

        assert "--ignore-case" in captured_args

    @pytest.mark.asyncio
    async def test_search_multi_file(self, rg_stdout_multi_file):
        """Right: 파일 2개 결과 → 2건 반환."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        proc = _make_proc_mock(rg_stdout_multi_file)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            results = await svc.search("def")

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_submatches_returned(self, rg_stdout_single):
        """Right: submatches 하이라이트 정보 포함."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        proc = _make_proc_mock(rg_stdout_single)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            results = await svc.search("search")

        match = results[0]["matches"][0]
        assert "submatches" in match
        assert len(match["submatches"]) >= 1
        sm = match["submatches"][0]
        assert "start" in sm and "end" in sm and "match" in sm


# ── Boundary / CORRECT ───────────────────────────────────────────────────

class TestRipgrepBoundary:
    """Boundary + CORRECT — 경계값 테스트."""

    @pytest.mark.asyncio
    async def test_max_results_one(self, rg_stdout_multi_file):
        """CORRECT-Cardinality: max_results=1 → 정확히 1건."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        proc = _make_proc_mock(rg_stdout_multi_file)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            results = await svc.search("def", max_results=1)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_context_lines_zero_no_context(self):
        """CORRECT-Range: context_lines=0 → -C 인수 없음."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        captured_args = []

        async def fake_exec(*args, **kwargs):
            captured_args.extend(args)
            return _make_proc_mock("")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await svc.search("test", context_lines=0)

        assert "-C" not in captured_args

    @pytest.mark.asyncio
    async def test_empty_extensions_no_glob_filter(self):
        """CORRECT-Existence: 확장자 미지정 → -g *.ext 인수 없음."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        captured_args = []

        async def fake_exec(*args, **kwargs):
            captured_args.extend(args)
            return _make_proc_mock("")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await svc.search("test", extensions=[])

        # -g 인수 없어야 함
        assert "-g" not in captured_args

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        """Boundary: 빈 쿼리 → subprocess 호출 없이 빈 결과."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        results = await svc.search("")
        assert results == []


# ── Cross-check: regex ON/OFF ────────────────────────────────────────────

class TestRipgrepCrossCheck:
    """Cross-check — regex ON/OFF 차이 검증."""

    @pytest.mark.asyncio
    async def test_regex_off_adds_fixed_strings(self):
        """Cross-check: regex=False → --fixed-strings 포함."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        captured_args = []

        async def fake_exec(*args, **kwargs):
            captured_args.extend(args)
            return _make_proc_mock("")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await svc.search("test.*py", regex=False)

        assert "--fixed-strings" in captured_args

    @pytest.mark.asyncio
    async def test_regex_on_no_fixed_strings(self):
        """Cross-check: regex=True → --fixed-strings 없음."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        captured_args = []

        async def fake_exec(*args, **kwargs):
            captured_args.extend(args)
            return _make_proc_mock("")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await svc.search("test.*py", regex=True)

        assert "--fixed-strings" not in captured_args


# ── Error: 에러 처리 ─────────────────────────────────────────────────────

class TestRipgrepError:
    """Error — 에러 조건 처리 검증."""

    @pytest.mark.asyncio
    async def test_rg_not_installed_raises(self):
        """Error: rg 미설치(rg_path=None) → FileNotFoundError."""
        svc = RipgrepService()
        svc._rg_path = None

        with pytest.raises(FileNotFoundError):
            await svc.search("test")

    @pytest.mark.asyncio
    async def test_invalid_regex_raises_value_error(self):
        """Error: 잘못된 정규식 → ValueError (rg stderr에 regex parse error)."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        stderr = "error parsing regex near '[unclosed'"
        proc = _make_proc_mock("", stderr=stderr)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(ValueError, match="잘못된 정규식"):
                await svc.search("[unclosed", regex=True)

    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_empty(self):
        """Error: 존재하지 않는 경로 → 결과 없음 (빈 리스트)."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        # rg는 존재하지 않는 경로에서 결과 없이 종료
        proc = _make_proc_mock("", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            results = await svc.search("test", paths=["/nonexistent/path"])

        assert results == []

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self):
        """Error: subprocess 타임아웃 → TimeoutError."""
        svc = RipgrepService()
        svc._rg_path = "/usr/bin/rg"

        proc = AsyncMock()
        proc.kill = MagicMock()

        async def slow_communicate():
            await asyncio.sleep(9999)
            return b"", b""

        proc.communicate = slow_communicate

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch("app.modules.file_search.services.ripgrep.RIPGREP_TIMEOUT", 0.01):
            with pytest.raises(TimeoutError):
                await svc.search("test", paths=["/some/path"])


# ── _build_args 단위 테스트 ─────────────────────────────────────────────

class TestBuildArgs:
    """_build_args 메서드 단위 검증."""

    def test_json_always_included(self):
        svc = RipgrepService()
        args = svc._build_args("test", [], [], [], True, False, 2)
        assert "--json" in args

    def test_extension_glob_pattern(self):
        svc = RipgrepService()
        args = svc._build_args("test", [], ["py", "ts"], [], True, False, 0)
        assert "-g" in args
        assert "*.py" in args
        assert "*.ts" in args

    def test_exclude_glob_pattern(self):
        svc = RipgrepService()
        args = svc._build_args("test", [], [], ["node_modules"], True, False, 0)
        assert "--glob" in args
        assert "!node_modules" in args

    def test_paths_appended_last(self):
        svc = RipgrepService()
        args = svc._build_args("test", ["/home/user"], [], [], True, False, 0)
        assert args[-1] == "/home/user"

    def test_case_sensitive_no_ignore_case(self):
        svc = RipgrepService()
        args = svc._build_args("test", [], [], [], True, True, 0)
        assert "--ignore-case" not in args
