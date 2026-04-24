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

from sqlalchemy.orm import Session

from app.modules.file_search.schemas import (
    BrowseResponse,
    ContentMatch,
    DirectoryItem,
    FileMatch,
    FilePreviewResponse,
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

PREVIEW_TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".text",
    ".py",
    ".ps1",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".svelte",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".sql",
    ".css",
    ".html",
    ".xml",
    ".csv",
    ".log",
}

MAX_PREVIEW_BYTES = 256 * 1024


class FilePreviewError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class SearchService:
    """파일 검색 통합 서비스."""

    # ------------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------------

    async def search(self, request: SearchRequest, db: Optional[Session] = None) -> SearchResponse:
        """통합 검색 실행."""
        start_ms = int(time.time() * 1000)

        # 프리셋 적용 (preset 있으면 paths/extensions/excludes 오버라이드)
        paths, extensions, excludes = self._resolve_filters(request, db)

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
        # 드라이브 루트 보정: "D:" → "D:\" (Windows에서 "D:"는 상대경로)
        if len(path) == 2 and path[1] == ':' and path[0].isalpha():
            path = path + "\\"
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
    # Preview
    # ------------------------------------------------------------------

    def get_file_preview(self, file_path: str) -> FilePreviewResponse:
        """텍스트 파일 미리보기 내용을 반환한다.

        NOTE: Session 0에서도 파일 읽기는 가능하므로, preview는 Redis queue를 타지 않는 direct read로 유지한다.
        """
        if not os.path.exists(file_path):
            raise FilePreviewError(status_code=404, detail=f"파일을 찾을 수 없습니다: {file_path}")
        if not os.path.isfile(file_path):
            raise FilePreviewError(status_code=404, detail=f"디렉토리는 미리보기할 수 없습니다: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in PREVIEW_TEXT_EXTENSIONS:
            raise FilePreviewError(status_code=415, detail=f"지원하지 않는 확장자입니다: {ext or '(none)'}")

        try:
            size_bytes = int(os.path.getsize(file_path))
        except OSError:
            raise FilePreviewError(status_code=404, detail=f"파일 크기를 확인할 수 없습니다: {file_path}")

        if size_bytes > MAX_PREVIEW_BYTES:
            raise FilePreviewError(status_code=413, detail=f"미리보기 크기 제한(256KB)을 초과했습니다: {size_bytes} bytes")

        with open(file_path, "rb") as f:
            raw = f.read(MAX_PREVIEW_BYTES + 1)

        if len(raw) > MAX_PREVIEW_BYTES:
            raise FilePreviewError(status_code=413, detail=f"미리보기 크기 제한(256KB)을 초과했습니다: {len(raw)} bytes")
        if b"\x00" in raw:
            raise FilePreviewError(status_code=415, detail=f"미리보기 불가 (binary 파일): {file_path}")

        content, encoding = self._decode_preview_text(raw, file_path)

        return FilePreviewResponse(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            extension=ext.lstrip("."),
            size_bytes=size_bytes,
            encoding=encoding,
            content=content,
        )

    @staticmethod
    def _decode_preview_text(raw: bytes, file_path: str) -> tuple[str, str]:
        for encoding in ("utf-8-sig", "utf-8", "cp949"):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise FilePreviewError(status_code=415, detail=f"미리보기 불가 (지원하지 않는 인코딩): {file_path}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_filters(self, request: SearchRequest, db: Optional[Session] = None):
        """프리셋이 있으면 프리셋 값으로 오버라이드. DB의 활성 ignore 패턴도 병합."""
        paths = list(request.paths)
        extensions = list(request.extensions)
        excludes = list(request.excludes)

        if request.preset and request.preset in PRESETS:
            preset = PRESETS[request.preset]
            paths = preset.paths
            extensions = preset.extensions
            excludes = preset.excludes

        # DB의 활성 ignore 패턴 병합 (enabled=1)
        if db is not None:
            try:
                from app.models.file_search_ignore_pattern import FileSearchIgnorePattern
                db_patterns = (
                    db.query(FileSearchIgnorePattern.pattern)
                    .filter(FileSearchIgnorePattern.enabled == 1)
                    .all()
                )
                db_excludes = [row.pattern for row in db_patterns]
                # 중복 제거 후 병합
                existing = set(excludes)
                excludes = excludes + [p for p in db_excludes if p not in existing]
            except Exception as e:
                logger.warning(f"[search_service] ignore 패턴 조회 실패: {e}")

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

        def _safe_int(v):
            try:
                return int(v) if v not in (None, "") else None
            except (ValueError, TypeError):
                return None

        results = [
            FileMatch(
                file_path=r["file_path"],
                file_name=r["file_name"],
                file_size=_safe_int(r.get("file_size")),
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

        def _safe_int(v):
            try:
                return int(v) if v not in (None, "") else None
            except (ValueError, TypeError):
                return None

        # filename 결과 병합 (content에 없는 파일만 추가)
        for r in fn_raw:
            fp = r["file_path"]
            if fp not in merged:
                merged[fp] = FileMatch(
                    file_path=fp,
                    file_name=r["file_name"],
                    file_size=_safe_int(r.get("file_size")),
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
