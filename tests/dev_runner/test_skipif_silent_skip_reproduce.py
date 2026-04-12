"""skipif 묵인 시나리오 재현 TC — Phase T3.

수정 전 동작이 위험했음을 증명하고, 수정 후 테스트가 실제로 실행되는지 확인한다.
"""
import subprocess
import sys
from pathlib import Path

import pytest


TESTS_ROOT = Path(__file__).resolve().parent.parent  # tests/ 디렉토리


def test_skipif_false_condition_causes_skip_not_fail():
    """skipif가 False 조건을 반환할 때 테스트가 skip되는 동작을 재현 (수정 전 위험 증명).

    pytest.mark.skipif(True, ...) 데코레이터가 붙은 임시 테스트를 subprocess로 실행해
    exit_code 0 + "skipped"가 나타나는 것을 확인한다.
    이는 서버 미가용 시 skipif가 조용히 통과시키던 위험한 동작을 재현한다.
    """
    # 임시 테스트 파일 내용 — skipif(True) 가 테스트를 skip시키는 시나리오
    test_code = """\
import pytest

@pytest.mark.skipif(True, reason="서버 미가용 시뮬레이션")
def test_should_be_skipped():
    assert False, "이 어서션은 절대 실행되지 않음 — skip 처리됨"
"""
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix="_skipif_demo.py", dir=str(TESTS_ROOT),
        delete=False, encoding="utf-8"
    ) as tf:
        tf.write(test_code)
        tmp_path = tf.name

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", tmp_path, "-v", "--tb=short", "-q"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            cwd=str(TESTS_ROOT),
        )
        output = result.stdout + result.stderr
        # exit code 0: skip은 실패가 아님 — 이게 바로 문제
        assert result.returncode == 0, (
            f"예상: returncode=0 (skip은 실패 아님), 실제: {result.returncode}\n{output}"
        )
        # "skipped" 포함 확인
        assert "skipped" in output.lower(), (
            f"'skipped' 키워드가 출력에 없음:\n{output}"
        )
        # "FAILED" 미포함 확인 — skip은 실패가 아님을 증명
        assert "FAILED" not in output, (
            f"skip이 FAILED로 처리됨 (예상과 다름):\n{output}"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def test_removed_skipif_test_runs_without_skip():
    """skipif 제거 후 테스트 함수가 실제로 실행되는지 확인 (skip 0건).

    수정된 test_connection_leak_e2e.py를 --collect-only로 수집 시
    skipif 마커가 없어 "no tests were selected"나 "skipped" 없이 정상 수집됨을 확인.
    """
    target = TESTS_ROOT / "dev_runner" / "test_connection_leak_e2e.py"
    assert target.exists(), f"파일 없음: {target}"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "--collect-only", "-q",
         "--ignore-glob=*__pycache__*"],
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
        cwd=str(TESTS_ROOT),
    )
    output = result.stdout + result.stderr

    # skipif 마커가 없으면 수집 결과에 "skipped" 또는 "no tests were selected" 없어야 함
    assert "no tests were selected" not in output, (
        f"테스트가 선택되지 않음 (skipif 제거 후에도 수집 실패):\n{output}"
    )

    # 2개 테스트 함수가 수집되어야 함
    assert "test_sse_events_disconnect_cleanup_e2e" in output, (
        f"테스트 함수가 수집되지 않음:\n{output}"
    )
    assert "test_sse_log_stream_disconnect_cleanup_e2e" in output, (
        f"테스트 함수가 수집되지 않음:\n{output}"
    )
