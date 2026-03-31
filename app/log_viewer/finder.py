"""
finder.py — 로그 파일 탐색/선택 로직

logs.ps1의 Get-LatestLogFileMultiPattern / Get-LatestLogFilesMultiPattern 로직을
Python으로 이식한다.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path


def _collect_candidates(patterns: list[str], dirs: list[Path]) -> list[Path]:
    """
    주어진 디렉토리 목록과 패턴(glob) 목록으로 후보 파일을 수집한다.

    - 존재하지 않는 디렉토리는 조용히 건너뛴다.
    - 중복 파일(절대경로 기준)은 제거한다.
    - 반환: 수집된 Path 리스트 (순서 미정렬)
    """
    seen: set[Path] = set()
    candidates: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for pattern in patterns:
            for f in d.iterdir():
                if not f.is_file():
                    continue
                if fnmatch.fnmatch(f.name, pattern):
                    resolved = f.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        candidates.append(f)
    return candidates


def find_latest_logs(
    patterns: list[str],
    dirs: list[Path],
    max_count: int = 3,
) -> list[Path]:
    """
    여러 디렉토리·패턴에서 최신 로그 파일 최대 max_count개를 반환한다.

    선택 로직 (logs.ps1의 Get-LatestLogFilesMultiPattern 동일):
      1. 모든 후보를 LastWriteTime DESC 정렬
      2. 순서대로 결과에 추가
         - max_count에 도달하면 중단
         - 비어있지 않은(size > 0) 파일을 만나면 추가 후 중단
         (빈 파일은 포함하면서 계속, 유효 파일 만나면 stop)
      3. 결과를 LastWriteTime ASC(오래된→최신) 재정렬 후 반환

    Parameters
    ----------
    patterns:  glob 패턴 리스트 (예: ["api_*.log", "stdout_api_*.log"])
    dirs:      탐색할 디렉토리 Path 리스트
    max_count: 반환할 최대 파일 수 (기본 3)

    Returns
    -------
    list[Path] — 오래된→최신 순, 비어있는 경우 빈 리스트
    """
    candidates = _collect_candidates(patterns, dirs)
    if not candidates:
        return []

    # LastWriteTime DESC
    sorted_desc = sorted(candidates, key=lambda f: f.stat().st_mtime, reverse=True)

    result: list[Path] = []
    for f in sorted_desc:
        result.append(f)
        if len(result) >= max_count:
            break
        if f.stat().st_size > 0:
            # 비어있지 않은 파일 만나면 추가 후 중단
            break

    # LastWriteTime ASC (오래된→최신) 재정렬
    result.sort(key=lambda f: f.stat().st_mtime)
    return result


def find_latest_log(
    patterns: list[str],
    dirs: list[Path],
) -> Path | None:
    """
    여러 디렉토리·패턴에서 최신 로그 파일 1개를 반환한다.

    선택 로직 (logs.ps1의 Get-LatestLogFileMultiPattern 동일):
      - 비어있지 않은 파일 중 LastWriteTime이 가장 최신인 파일 우선
      - 비어있지 않은 파일이 없으면 전체 후보 중 가장 최신 파일

    Parameters
    ----------
    patterns:  glob 패턴 리스트
    dirs:      탐색할 디렉토리 Path 리스트

    Returns
    -------
    Path | None — 파일이 없으면 None
    """
    candidates = _collect_candidates(patterns, dirs)
    if not candidates:
        return None

    non_empty = [f for f in candidates if f.stat().st_size > 0]
    pool = non_empty if non_empty else candidates
    return max(pool, key=lambda f: f.stat().st_mtime)
