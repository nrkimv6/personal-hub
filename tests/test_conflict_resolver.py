"""tests/test_conflict_resolver.py — ConflictAnalyzer, ConflictResolver 단위 테스트"""
import subprocess
import sys
from pathlib import Path

import pytest

# scripts 경로를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ---- fixture: conflict repo ----

def make_git_repo(tmp_path: Path):
    """tmp_path에 git init + 초기 설정"""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    return tmp_path


def make_conflict_repo(tmp_path: Path):
    """충돌 상태 repo 생성"""
    make_git_repo(tmp_path)
    # main 브랜치로 초기화
    subprocess.run(["git", "checkout", "-b", "main"], cwd=tmp_path, capture_output=True)
    a_py = tmp_path / "a.py"
    a_py.write_text("line = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    # feat 브랜치
    subprocess.run(["git", "checkout", "-b", "feat"], cwd=tmp_path, capture_output=True)
    a_py.write_text("line = 2\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat change"], cwd=tmp_path, capture_output=True)
    # main으로 돌아가서 다른 수정
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True)
    a_py.write_text("line = 3\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=tmp_path, capture_output=True)
    # 충돌 머지 (returncode 1 이어야 충돌 발생)
    subprocess.run(["git", "merge", "feat", "--no-ff"], cwd=tmp_path, capture_output=True)
    return tmp_path


# ---- ConflictAnalyzer 테스트 ----

def test_get_conflict_files_R(tmp_path):
    from conflict_resolver import ConflictAnalyzer
    repo = make_conflict_repo(tmp_path)
    files = ConflictAnalyzer.get_conflict_files(repo)
    assert files == ["a.py"]


def test_get_conflict_files_no_conflict_B(tmp_path):
    from conflict_resolver import ConflictAnalyzer
    make_git_repo(tmp_path)
    (tmp_path / "b.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "b.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    files = ConflictAnalyzer.get_conflict_files(tmp_path)
    assert files == []


def test_parse_conflict_markers_R(tmp_path):
    from conflict_resolver import ConflictAnalyzer
    f = tmp_path / "test.py"
    f.write_text("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feat\n")
    blocks = ConflictAnalyzer.parse_conflict_markers(f)
    assert len(blocks) == 1
    assert blocks[0].ours == "ours\n"
    assert blocks[0].theirs == "theirs\n"


def test_parse_conflict_markers_multiple_blocks_R(tmp_path):
    from conflict_resolver import ConflictAnalyzer
    f = tmp_path / "test.py"
    f.write_text(
        "<<<<<<< HEAD\nours1\n=======\ntheirs1\n>>>>>>> feat\n"
        "middle\n"
        "<<<<<<< HEAD\nours2\n=======\ntheirs2\n>>>>>>> feat\n"
    )
    blocks = ConflictAnalyzer.parse_conflict_markers(f)
    assert len(blocks) == 2
    assert blocks[0].ours == "ours1\n"
    assert blocks[1].theirs == "theirs2\n"


def test_parse_conflict_markers_empty_file_B(tmp_path):
    from conflict_resolver import ConflictAnalyzer
    f = tmp_path / "empty.py"
    f.write_text("")
    blocks = ConflictAnalyzer.parse_conflict_markers(f)
    assert blocks == []


def test_is_resolvable_within_limit_R():
    from conflict_resolver import ConflictAnalyzer
    ok, reason = ConflictAnalyzer.is_resolvable(["a.py", "b.py"])
    assert ok is True
    assert reason == ""


def test_is_resolvable_over_limit_B():
    from conflict_resolver import ConflictAnalyzer
    files = [f"file{i}.py" for i in range(6)]
    ok, reason = ConflictAnalyzer.is_resolvable(files)
    assert ok is False
    assert "6" in reason


def test_is_resolvable_binary_excluded_B():
    from conflict_resolver import ConflictAnalyzer
    # .lock 확장자가 제외 목록에 포함됨
    ok, reason = ConflictAnalyzer.is_resolvable(["a.py", "package.lock"])
    assert ok is False
    assert "package.lock" in reason


def test_verify_resolution_clean_R(tmp_path):
    from conflict_resolver import ConflictResolver
    make_git_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    resolver = ConflictResolver(tmp_path)
    assert resolver._verify_resolution() is True


def test_verify_resolution_markers_remain_E(tmp_path):
    from conflict_resolver import ConflictResolver
    make_git_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    # conflict markers 포함 파일 추가
    (tmp_path / "a.py").write_text("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feat\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
    resolver = ConflictResolver(tmp_path)
    assert resolver._verify_resolution() is False
