"""
통합 검색 서비스

mode에 따라 Everything(filename) / ripgrep(content) / 둘 다(both) 실행.
both 모드: file_path 기준 중복 제거 — content 매칭 파일은 matches 포함,
           filename-only 결과는 matches 빈 배열.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import List, Optional

from app.modules.file_search.schemas import (
    BrowseResponse,
    ContentMatch,
    DirectoryItem,
    FileMatch,
    SearchRequest,
    SearchResponse,
    StatusResponse,
)
from app.modules.file_search.services.everything import EverythingService
from app.modules.file_search.services.presets import PRESETS
from app.modules.file_search.services.ripgrep import RipgrepService

logger = logging.getLogger("file_search.search_service")

_everything = EverythingService()
_ripgrep = RipgrepService()


class SearchService:
    """파일 검색 통합 서비스."""

    # ------------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------------

    async def search(self, request: SearchRequest) -> SearchResponse:
        """통합 검색 실행."""
        start_ms = int(time.time() * 1000)

        # 프리셋 적용 (preset 있으면 paths/extensions/excludes 오버라이드)
        paths, extensions, excludes = self._resolve_filters(request)

        # mode별 실행
        if request.mode == "filename":
            results, truncated = await self._search_filename(request, paths, extensions, excludes)
        elif request.mode == "content":
            results, truncated = await self._search_content(request, paths, extensions, excludes)
        else:  # both
            results, truncated = await self._search_both(request, paths, extensions, excludes)

        elapsed = int(time.time() * 1000) - start_ms

        return SearchResponse(
            results=results,
            total_count=len(results),
            search_time_ms=elapsed,
            mode=request.mode,
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # 파일 열기
    # ------------------------------------------------------------------

    def open_file(self, file_path: str, line_number: Optional[int] = None) -> None:
        """파일을 VSCode 또는 기본 프로그램으로 열기."""
        try:
            if line_number:
                subprocess.Popen(["code", "--goto", f"{file_path}:{line_number}"])
            else:
                subprocess.Popen(["code", file_path])
            logger.info(f"VSCode로 파일 열기: {file_path}:{line_number}")
        except FileNotFoundError:
            # VSCode 없으면 기본 프로그램으로 열기
            try:
                os.startfile(file_path)
            except Exception as exc:
                logger.warning(f"파일 열기 실패: {file_path} — {exc}")
                raise

    # ------------------------------------------------------------------
    # 상태 확인
    # ------------------------------------------------------------------

    async def check_status(self) -> StatusResponse:
        """Everything + ripgrep 상태 확인."""
        ev_ok, ev_msg = await _everything.is_available()
        rg_ok, rg_path = _ripgrep.is_available()

        return StatusResponse(
            everything_ok=ev_ok,
            everything_message=ev_msg,
            ripgrep_ok=rg_ok,
            ripgrep_path=rg_path,
        )

    # ------------------------------------------------------------------
    # 디렉토리 탐색
    # ------------------------------------------------------------------

    def browse_directory(self, path: str) -> BrowseResponse:
        """서버 측 디렉토리 목록 반환."""
        path = path.rstrip("\\/")
        if not path:
            # 드라이브 목록 반환 (Windows)
            import string
            drives = [
                DirectoryItem(name=f"{d}:\\", path=f"{d}:\\")
                for d in string.ascii_uppercase
                if os.path.exists(f"{d}:\\")
            ]
            return BrowseResponse(current="", parent=None, directories=drives)

        # 부모 경로
        parent = str(os.path.dirname(path)) if os.path.dirname(path) != path else None

        directories: List[DirectoryItem] = []
        try:
            with os.scandir(path) as entries:
                for entry in sorted(entries, key=lambda e: e.name.lower()):
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(DirectoryItem(name=entry.name, path=entry.path))
        except (PermissionError, FileNotFoundError, OSError) as exc:
            logger.debug(f"디렉토리 탐색 실패: {path} — {exc}")

        return BrowseResponse(current=path, parent=parent, directories=directories)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_filters(self, request: SearchRequest):
        """프리셋이 있으면 프리셋 값으로 오버라이드."""
        paths = list(request.paths)
        extensions = list(request.extensions)
        excludes = list(request.excludes)

        if request.preset and request.preset in PRESETS:
            preset = PRESETS[request.preset]
            paths = preset.paths
            extensions = preset.extensions
            excludes = preset.excludes

        return paths, extensions, excludes

    async def _search_filename(
        self, request: SearchRequest, paths, extensions, excludes
    ):
        raw = await _everything.search(
            query=request.query,
            regex=request.regex,
            extensions=extensions,
            paths=paths,
            excludes=excludes,
            max_results=request.max_results,
        )
        truncated = len(raw) >= request.max_results

        results = [
            FileMatch(
                file_path=r["file_path"],
                file_name=r["file_name"],
                file_size=r.get("file_size"),
                modified=r.get("modified"),
                matches=[],
                match_source="filename",
            )
            for r in raw
        ]
        return results, truncated

    async def _search_content(
        self, request: SearchRequest, paths, extensions, excludes
    ):
        raw = await _ripgrep.search(
            query=request.query,
            paths=paths,
            extensions=extensions,
            excludes=excludes,
            regex=request.regex,
            case_sensitive=request.case_sensitive,
            context_lines=request.context_lines,
            max_results=request.max_results,
        )
        truncated = len(raw) >= request.max_results

        results = [
            FileMatch(
                file_path=r["file_path"],
                file_name=r["file_name"],
                file_size=r.get("file_size"),
                modified=r.get("modified"),
                matches=[
                    ContentMatch(
                        line_number=m["line_number"],
                        line_text=m["line_text"],
                        context_before=m.get("context_before", []),
                        context_after=m.get("context_after", []),
                        submatches=m.get("submatches", []),
                    )
                    for m in r.get("matches", [])
                ],
                match_source="content",
            )
            for r in raw
        ]
        return results, truncated

    async def _search_both(
        self, request: SearchRequest, paths, extensions, excludes
    ):
        """filename + content 병합: file_path 기준 중복 제거."""
        fn_raw, rg_raw = [], []

        # 두 검색 병렬 실행
        import asyncio
        fn_task = asyncio.create_task(
            _everything.search(
                query=request.query,
                regex=request.regex,
                extensions=extensions,
                paths=paths,
                excludes=excludes,
                max_results=request.max_results,
            )
        )
        rg_task = asyncio.create_task(
            _ripgrep.search(
                query=request.query,
                paths=paths,
                extensions=extensions,
                excludes=excludes,
                regex=request.regex,
                case_sensitive=request.case_sensitive,
                context_lines=request.context_lines,
                max_results=request.max_results,
            )
        )

        results_gathered = await asyncio.gather(fn_task, rg_task, return_exceptions=True)
        if not isinstance(results_gathered[0], Exception):
            fn_raw = results_gathered[0]
        else:
            logger.warning(f"Everything 검색 오류 (both 모드): {results_gathered[0]}")
        if not isinstance(results_gathered[1], Exception):
            rg_raw = results_gathered[1]
        else:
            logger.warning(f"ripgrep 검색 오류 (both 모드): {results_gathered[1]}")

        # content 결과를 file_path → FileMatch 딕셔너리로
        merged: dict[str, FileMatch] = {}
        for r in rg_raw:
            fp = r["file_path"]
            merged[fp] = FileMatch(
                file_path=fp,
                file_name=r["file_name"],
                file_size=r.get("file_size"),
                modified=r.get("modified"),
                matches=[
                    ContentMatch(
                        line_number=m["line_number"],
                        line_text=m["line_text"],
                        context_before=m.get("context_before", []),
                        context_after=m.get("context_after", []),
                        submatches=m.get("submatches", []),
                    )
                    for m in r.get("matches", [])
                ],
                match_source="content",
            )

        # filename 결과 병합 (content에 없는 파일만 추가)
        for r in fn_raw:
            fp = r["file_path"]
            if fp not in merged:
                merged[fp] = FileMatch(
                    file_path=fp,
                    file_name=r["file_name"],
                    file_size=r.get("file_size"),
                    modified=r.get("modified"),
                    matches=[],
                    match_source="filename",
                )
            else:
                # 이미 content 결과 있음 → match_source=both 표시
                merged[fp].match_source = "both"

        results = list(merged.values())[:request.max_results]
        truncated = (len(fn_raw) >= request.max_results) or (len(rg_raw) >= request.max_results)
        return results, truncated
