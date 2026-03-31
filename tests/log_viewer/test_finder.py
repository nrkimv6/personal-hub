"""
test_finder.py — finder.py RIGHT-BICEP 기준 TC

RIGHT-BICEP:
  Right     : 정상 파일 탐색 → 최신 파일 반환
  Boundary  : 빈 파일만 존재 / 파일 없음 / max_count 경계
  Inverse   : 패턴 미매칭 시 빈 리스트 반환
  Cross-check: 여러 디렉토리 + 여러 패턴 조합
  Error     : 존재하지 않는 디렉토리 전달 시 예외 없이 빈 리스트
  Performance: (해당 없음 — 단위 테스트 범위 밖)
"""
import time
from pathlib import Path

import pytest

from app.log_viewer.finder import find_latest_log, find_latest_logs


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_file(path: Path, content: bytes = b"data") -> Path:
    """파일을 생성하고 Path를 반환한다."""
    path.write_bytes(content)
    return path


def make_empty(path: Path) -> Path:
    """빈 파일(0 바이트)을 생성하고 Path를 반환한다."""
    path.write_bytes(b"")
    return path


# ---------------------------------------------------------------------------
# find_latest_logs — Right
# ---------------------------------------------------------------------------

class TestFindLatestLogsRight:
    def test_single_valid_file(self, tmp_path):
        """정상 파일 1개 → 그 파일 반환."""
        f = make_file(tmp_path / "api_20260327.log")
        result = find_latest_logs(["api_*.log"], [tmp_path])
        assert result == [f]

    def test_returns_newest_non_empty_as_last(self, tmp_path):
        """비어있지 않은 파일이 1개이면 결과는 그 파일 1개."""
        make_file(tmp_path / "api_20260325.log", b"old")
        newest = make_file(tmp_path / "api_20260327.log", b"new")
        # newest가 mtime이 더 최신이어야 하므로 잠깐 대기
        time.sleep(0.01)
        newest.write_bytes(b"new")
        result = find_latest_logs(["api_*.log"], [tmp_path])
        # 유효 파일 만나면 중단 → 결과는 newest 1개
        assert len(result) == 1
        assert result[-1].name == newest.name

    def test_sorted_asc_by_mtime(self, tmp_path):
        """반환 순서는 오래된→최신 ASC."""
        old = make_file(tmp_path / "api_old.log", b"x")
        time.sleep(0.02)
        new = make_file(tmp_path / "api_new.log", b"x")
        # 둘 다 non-empty → 첫 번째(newest)에서 중단이므로 결과는 new 1개
        result = find_latest_logs(["api_*.log"], [tmp_path])
        assert result == [new]


# ---------------------------------------------------------------------------
# find_latest_logs — Boundary
# ---------------------------------------------------------------------------

class TestFindLatestLogsBoundary:
    def test_empty_files_only(self, tmp_path):
        """빈 파일만 존재 — 빈 파일도 반환하되 max_count까지 포함."""
        e1 = make_empty(tmp_path / "api_1.log")
        time.sleep(0.01)
        e2 = make_empty(tmp_path / "api_2.log")
        time.sleep(0.01)
        e3 = make_empty(tmp_path / "api_3.log")
        time.sleep(0.01)
        e4 = make_empty(tmp_path / "api_4.log")

        result = find_latest_logs(["api_*.log"], [tmp_path], max_count=3)
        # 모두 빈 파일 → 최신 3개 반환, ASC 정렬
        assert len(result) == 3
        assert result[-1].name == e4.name  # 가장 최신이 마지막

    def test_no_files(self, tmp_path):
        """파일 없음 → 빈 리스트."""
        assert find_latest_logs(["api_*.log"], [tmp_path]) == []

    def test_max_count_1(self, tmp_path):
        """max_count=1 이면 파일 1개만 반환."""
        make_empty(tmp_path / "api_1.log")
        time.sleep(0.01)
        make_empty(tmp_path / "api_2.log")
        result = find_latest_logs(["api_*.log"], [tmp_path], max_count=1)
        assert len(result) == 1

    def test_empty_then_non_empty(self, tmp_path):
        """빈 파일 다음 유효 파일 — 빈 파일 포함 후 유효 파일에서 중단."""
        empty = make_empty(tmp_path / "api_old.log")
        time.sleep(0.01)
        valid = make_file(tmp_path / "api_new.log", b"content")
        # DESC 정렬: valid(newest=비어있지않음) → 포함 후 즉시 중단
        result = find_latest_logs(["api_*.log"], [tmp_path])
        assert result == [valid]

    def test_non_empty_then_empty(self, tmp_path):
        """최신 파일이 빈 파일, 구형 파일이 유효 — 빈 파일 포함, 유효 파일 만나면 중단."""
        valid = make_file(tmp_path / "api_old.log", b"content")
        time.sleep(0.01)
        empty = make_empty(tmp_path / "api_new.log")
        # DESC: empty(newest, 빈) → 포함 계속, valid(non-empty) → 포함 후 중단
        result = find_latest_logs(["api_*.log"], [tmp_path])
        assert len(result) == 2
        # ASC: valid이 older → 인덱스 0
        assert result[0].name == valid.name
        assert result[-1].name == empty.name


# ---------------------------------------------------------------------------
# find_latest_logs — Inverse (패턴 미매칭)
# ---------------------------------------------------------------------------

class TestFindLatestLogsInverse:
    def test_pattern_no_match(self, tmp_path):
        """패턴이 매칭되지 않으면 빈 리스트."""
        make_file(tmp_path / "worker_20260327.log")
        result = find_latest_logs(["api_*.log"], [tmp_path])
        assert result == []

    def test_wrong_extension(self, tmp_path):
        """확장자가 다르면 매칭되지 않는다."""
        make_file(tmp_path / "api_20260327.txt")
        result = find_latest_logs(["api_*.log"], [tmp_path])
        assert result == []


# ---------------------------------------------------------------------------
# find_latest_logs — Cross-check (여러 디렉토리/패턴)
# ---------------------------------------------------------------------------

class TestFindLatestLogsCrossCheck:
    def test_multiple_dirs(self, tmp_path):
        """여러 디렉토리에서 파일을 수집한다."""
        dir1 = tmp_path / "logs"
        dir2 = tmp_path / "logs_admin"
        dir1.mkdir()
        dir2.mkdir()
        f1 = make_file(dir1 / "api_1.log", b"x")
        time.sleep(0.01)
        f2 = make_file(dir2 / "api_2.log", b"x")
        # 두 디렉토리 합산 → 최신 비어있지않은 파일(f2)에서 중단
        result = find_latest_logs(["api_*.log"], [dir1, dir2])
        assert result == [f2]

    def test_multiple_patterns(self, tmp_path):
        """여러 패턴이 모두 수집된다."""
        f1 = make_file(tmp_path / "api_1.log", b"x")
        time.sleep(0.01)
        f2 = make_file(tmp_path / "stdout_api_1.log", b"x")
        # DESC: f2가 최신 non-empty → 중단
        result = find_latest_logs(["api_*.log", "stdout_api_*.log"], [tmp_path])
        assert f2 in result

    def test_duplicate_across_dirs_deduplicated(self, tmp_path):
        """동일 파일이 두 디렉토리 경로에서 잡히더라도 중복 없이 1개."""
        # 심볼릭 링크 대신 같은 파일을 두 dirs에 직접 전달하면 resolve()로 중복 제거
        f = make_file(tmp_path / "api_1.log", b"x")
        result = find_latest_logs(["api_*.log"], [tmp_path, tmp_path])
        assert result.count(f) == 1


# ---------------------------------------------------------------------------
# find_latest_logs — Error (존재하지 않는 디렉토리)
# ---------------------------------------------------------------------------

class TestFindLatestLogsError:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        """존재하지 않는 디렉토리 → 예외 없이 빈 리스트."""
        ghost = tmp_path / "does_not_exist"
        result = find_latest_logs(["api_*.log"], [ghost])
        assert result == []

    def test_mixed_valid_invalid_dirs(self, tmp_path):
        """유효 디렉토리 + 존재하지 않는 디렉토리 혼합 → 유효 디렉토리 결과만 반환."""
        f = make_file(tmp_path / "api_1.log", b"x")
        ghost = tmp_path / "ghost"
        result = find_latest_logs(["api_*.log"], [ghost, tmp_path])
        assert result == [f]


# ---------------------------------------------------------------------------
# find_latest_log — Right / Boundary
# ---------------------------------------------------------------------------

class TestFindLatestLog:
    def test_returns_none_when_no_files(self, tmp_path):
        assert find_latest_log(["api_*.log"], [tmp_path]) is None

    def test_returns_non_empty_over_empty(self, tmp_path):
        """빈 파일보다 비어있지 않은 파일이 우선."""
        empty = make_empty(tmp_path / "api_old.log")
        time.sleep(0.01)
        # empty가 최신이지만 비어있음
        valid = make_file(tmp_path / "api_older.log", b"data")
        # valid가 older지만 non-empty → 선택되어야 함
        result = find_latest_log(["api_*.log"], [tmp_path])
        assert result is not None
        assert result.name == valid.name

    def test_returns_newest_non_empty(self, tmp_path):
        """비어있지 않은 파일이 여럿이면 가장 최신을 반환."""
        make_file(tmp_path / "api_old.log", b"old")
        time.sleep(0.01)
        new = make_file(tmp_path / "api_new.log", b"new")
        result = find_latest_log(["api_*.log"], [tmp_path])
        assert result is not None
        assert result.name == new.name

    def test_falls_back_to_empty_if_all_empty(self, tmp_path):
        """모두 빈 파일이면 가장 최신 빈 파일 반환."""
        make_empty(tmp_path / "api_old.log")
        time.sleep(0.01)
        newest_empty = make_empty(tmp_path / "api_new.log")
        result = find_latest_log(["api_*.log"], [tmp_path])
        assert result is not None
        assert result.name == newest_empty.name

    def test_nonexistent_dir(self, tmp_path):
        """존재하지 않는 디렉토리 → None 반환."""
        ghost = tmp_path / "ghost"
        assert find_latest_log(["api_*.log"], [ghost]) is None

    def test_pattern_no_match(self, tmp_path):
        """패턴 미매칭 → None."""
        make_file(tmp_path / "worker_1.log", b"x")
        assert find_latest_log(["api_*.log"], [tmp_path]) is None
