"""skipif 제거 검증 TC — Phase T1."""
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]


def _grep_in_tests(pattern: str) -> list[str]:
    """tests/ 디렉토리에서 패턴 검색 후 매칭 라인 목록 반환."""
    result = subprocess.run(
        [sys.executable, "-c",
         f"""
import re, sys
from pathlib import Path

pattern = re.compile({pattern!r})
matches = []
for f in Path({str(TESTS_ROOT)!r}).rglob("*.py"):
    try:
        content = f.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                matches.append(f"{{f.relative_to(Path({str(TESTS_ROOT)!r}))}}: {{lineno}}: {{line.strip()}}")
    except Exception:
        pass
print("\\n".join(matches))
"""],
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    return lines


def test_no_skipif_server_available_right():
    """skipif + _server_available 조합이 tests/ 전체에서 0건인지 확인 (R: 정상)."""
    import re

    # 이 TC 파일 자체는 제외
    this_file = Path(__file__)
    pattern = re.compile(r"skipif[^#\n]*_server_available")
    matches = []
    for f in TESTS_ROOT.rglob("*.py"):
        if f == this_file:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    matches.append(f"{f.relative_to(TESTS_ROOT)}: {lineno}: {line.strip()}")
        except Exception:
            pass

    assert matches == [], (
        f"skipif+_server_available 잔존 {len(matches)}건:\n" + "\n".join(matches)
    )


def test_no_skipif_redis_available_right():
    """skipif + _redis_available 조합이 tests/ 전체에서 0건인지 확인 (R: 정상)."""
    import re

    this_file = Path(__file__)
    pattern = re.compile(r"skipif[^#\n]*_redis_available")
    matches = []
    for f in TESTS_ROOT.rglob("*.py"):
        if f == this_file:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    matches.append(f"{f.relative_to(TESTS_ROOT)}: {lineno}: {line.strip()}")
        except Exception:
            pass

    assert matches == [], (
        f"skipif+_redis_available 잔존 {len(matches)}건:\n" + "\n".join(matches)
    )


def test_no_skipif_api_and_pg_available_right():
    """skipif + API/PG helper 조합이 tests/ 전체에서 0건인지 확인."""
    import re

    this_file = Path(__file__)
    pattern = re.compile(r"@pytest\.mark\.skipif\(not _(api_available|is_api_available|check_admin_api|pg_available)\(")
    matches = []
    for f in TESTS_ROOT.rglob("*.py"):
        if f == this_file:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    matches.append(f"{f.relative_to(TESTS_ROOT)}: {lineno}: {line.strip()}")
        except Exception:
            pass

    assert matches == [], (
        f"skipif+api/pg helper 잔존 {len(matches)}건:\n" + "\n".join(matches)
    )


def test_no_helper_function_defs_right():
    """Grep으로 제거 대상 helper 함수가 선택된 파일들에서 0건인지 확인."""
    import re

    target_files = [
        TESTS_ROOT / "dev_runner" / "test_post_merge_done_http.py",
        TESTS_ROOT / "dev_runner" / "test_v2_merge_fallback_http.py",
        TESTS_ROOT / "dev_runner" / "test_event_stream_log_http.py",
        TESTS_ROOT / "dev_runner" / "test_redis_reconnect_e2e.py",
        TESTS_ROOT / "dev_runner" / "test_sse_filter_e2e.py",
        TESTS_ROOT / "dev_runner" / "test_sse_filter_http.py",
        TESTS_ROOT / "dev_runner" / "test_tab_persistence_http.py",
        TESTS_ROOT / "dev_runner" / "test_merge_lock_per_repo_http.py",
        TESTS_ROOT / "test_database_pg_compat.py",
        TESTS_ROOT / "test_pg_sequence_sync.py",
    ]

    pattern = re.compile(r"def _api_available|def _is_api_available|def _check_admin_api|def _pg_available")
    matches = []
    for f in target_files:
        if not f.exists():
            continue
        content = f.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                matches.append(f"{f.name}: {lineno}: {line.strip()}")

    assert matches == [], (
        f"_api_available/_is_api_available/_check_admin_api/_pg_available 함수 정의 잔존 {len(matches)}건:\n"
        + "\n".join(matches)
    )


def test_runtime_skip_to_fail_converted_right():
    """Phase 2 대상 4개 파일에서 pytest.skip.*미기동|pytest.skip.*not available 패턴이 0건인지 확인."""
    import re

    target_files = [
        TESTS_ROOT / "dev_runner" / "test_early_exit_e2e_http.py",
        TESTS_ROOT / "dev_runner" / "test_devguide_staleness.py",
        TESTS_ROOT / "dev_runner" / "conftest_e2e.py",
        TESTS_ROOT / "dev_runner" / "test_e2e.py",
    ]

    # pytest.skip( 또는 _pytest.skip( 뒤에 미기동/not available/unavailable
    pattern = re.compile(r"_pytest\.skip\(.*미기동|pytest\.skip\(.*미기동|_pytest\.skip\(.*not available|pytest\.skip\(.*not available")
    matches = []
    for f in target_files:
        if not f.exists():
            continue
        content = f.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                matches.append(f"{f.name}: {lineno}: {line.strip()}")

    assert matches == [], (
        f"런타임 skip 잔존 {len(matches)}건:\n" + "\n".join(matches)
    )
