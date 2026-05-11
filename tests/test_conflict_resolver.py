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


def test_verify_resolution_none_stdout_E(tmp_path, monkeypatch):
    """_verify_resolution에서 subprocess stdout이 None이면 AttributeError 없이 정상 반환"""
    from conflict_resolver import ConflictResolver
    make_git_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    resolver = ConflictResolver(tmp_path)

    original_run = subprocess.run

    def mock_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        result = original_run(*args, **kwargs)
        # git grep 호출에서 stdout=None 시뮬레이션
        if isinstance(cmd, list) and "grep" in cmd:
            result.stdout = None
            result.returncode = 0
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)
    # AttributeError 없이 정상 반환해야 함 (stdout=None → 마커 없음 → True)
    assert resolver._verify_resolution() is True


def test_try_resolve_no_result_block_returns_failure_B(tmp_path, monkeypatch):
    """Claude 에이전트가 결과 블록 없이 빈 stdout 반환 시 success=False + reason 포함"""
    from conflict_resolver import ConflictResolver, ConflictAnalyzer
    repo = make_conflict_repo(tmp_path)
    resolver = ConflictResolver(repo)

    # Claude subprocess를 빈 stdout으로 mock
    original_run = subprocess.run

    def mock_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "claude":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="no result block here", stderr="")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    # DB 기록을 mock (테이블 없을 수 있으므로)
    monkeypatch.setattr(resolver, "_record_resolution", lambda *a, **kw: None)

    result = resolver.try_resolve("test-runner", "feat")
    assert result.success is False
    assert "결과 블록 없음" in result.reason


def test_try_resolve_traceback_in_error_log_R(tmp_path, monkeypatch, caplog):
    """예외 발생 시 로그에 traceback이 포함되는지 확인"""
    import logging
    from conflict_resolver import ConflictResolver

    resolver = ConflictResolver(tmp_path)

    # _build_prompt에서 예외 발생시키기 위해 get_conflict_files를 mock
    def mock_get_files(project_root):
        return ["a.py"]

    def mock_is_resolvable(files):
        return True, ""

    def mock_parse(file_path):
        raise ValueError("test traceback error")

    from conflict_resolver import ConflictAnalyzer
    monkeypatch.setattr(ConflictAnalyzer, "get_conflict_files", staticmethod(mock_get_files))
    monkeypatch.setattr(ConflictAnalyzer, "is_resolvable", staticmethod(mock_is_resolvable))
    monkeypatch.setattr(ConflictAnalyzer, "parse_conflict_markers", staticmethod(mock_parse))

    with caplog.at_level(logging.ERROR):
        result = resolver.try_resolve("test-runner", "feat")

    assert result.success is False
    assert any("Traceback" in r.message for r in caplog.records)


def test_record_resolution_writes_pg_not_sqlite_R(tmp_path, monkeypatch):
    """R: conflict resolution history uses SQLAlchemy session, not data/monitor.db sqlite."""
    from conflict_resolver import ConflictResolver, ResolveResult

    class FakeSession:
        def __init__(self):
            self.executed = []
            self.committed = False
            self.closed = False
            self.rolled_back = False

        def execute(self, stmt, params):
            self.executed.append((str(stmt), params))

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    fake_session = FakeSession()

    import conflict_resolver

    monkeypatch.setattr(conflict_resolver, "_session_local", lambda: fake_session)

    resolver = ConflictResolver(tmp_path)
    resolver._record_resolution(
        "runner-1",
        "impl/test",
        ["a.py"],
        ResolveResult(success=True, resolved_files=["a.py"]),
        42,
    )

    assert fake_session.committed is True
    assert fake_session.closed is True
    assert fake_session.rolled_back is False
    sql, params = fake_session.executed[0]
    assert "INSERT INTO conflict_resolutions" in sql
    assert params["runner_id"] == "runner-1"
    assert params["success"] is True


# ---- T1-2: agent 프롬프트 내용 검증 TC ----

def _agent_md_path() -> Path:
    """auto-conflict-resolver.md 경로 (프로젝트 루트 기준)"""
    return Path(__file__).parent.parent / ".claude" / "agents" / "auto-conflict-resolver.md"


def test_conflict_resolver_agent_has_dedup_rule_R():
    """R(Right): agent md에 dedup/하나만 유지 문구 포함 확인"""
    content = _agent_md_path().read_text(encoding="utf-8")
    assert "하나만 유지" in content


def test_conflict_resolver_agent_has_verification_step_R():
    """R(Right): agent md에 '해결 후 검증' 문구 포함 확인"""
    content = _agent_md_path().read_text(encoding="utf-8")
    assert "해결 후 검증" in content


def test_conflict_resolver_agent_model_is_opus_R():
    """R(Right): frontmatter에 model: opus 존재 확인"""
    import re
    content = _agent_md_path().read_text(encoding="utf-8")
    assert re.search(r"^model:\s*opus", content, re.MULTILINE), \
        "frontmatter에 'model: opus'가 없습니다"


def test_conflict_resolver_agent_has_5_strategies_R():
    """R(Right): 전략 (a)~(e) 5개 모두 존재 확인"""
    content = _agent_md_path().read_text(encoding="utf-8")
    for label in ["(a)", "(b)", "(c)", "(d)", "(e)"]:
        assert label in content, f"전략 {label}이 agent md에 없습니다"


# ---- T1-3: 3-way diff TC ----

def test_get_base_content_returns_merge_base_R(tmp_path):
    """R(Right): merge 충돌 상태에서 base 버전 내용 반환"""
    from conflict_resolver import ConflictAnalyzer
    repo = make_conflict_repo(tmp_path)
    base = ConflictAnalyzer.get_base_content(repo, "a.py")
    assert base == "line = 1\n"


def test_get_base_content_new_file_returns_empty_B(tmp_path):
    """B(Boundary): merge base에 없는 신규 파일 → 빈 문자열 반환"""
    from conflict_resolver import ConflictAnalyzer
    repo = make_conflict_repo(tmp_path)
    base = ConflictAnalyzer.get_base_content(repo, "nonexistent_new_file.py")
    assert base == ""


def test_get_base_content_no_merge_returns_empty_E(tmp_path):
    """E(Error): merge 중이 아닌 일반 repo → 빈 문자열 반환, 예외 없음"""
    from conflict_resolver import ConflictAnalyzer
    make_git_repo(tmp_path)
    (tmp_path / "x.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "x.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    base = ConflictAnalyzer.get_base_content(tmp_path, "x.py")
    assert base == ""


def test_get_base_content_nonexistent_file_returns_empty_E(tmp_path):
    """E(Error): 존재하지 않는 파일 경로 → 빈 문자열 반환, 예외 없음"""
    from conflict_resolver import ConflictAnalyzer
    repo = make_conflict_repo(tmp_path)
    base = ConflictAnalyzer.get_base_content(repo, "totally_wrong_path/nothing.py")
    assert base == ""
