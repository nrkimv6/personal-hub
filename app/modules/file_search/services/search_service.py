"""
통합 검색 서비스

mode에 따라 Everything(filename) / ripgrep(content) / 둘 다(both) 실행.
both 모드: file_path 기준 중복 제거 — content 매칭 파일은 matches 포함,
           filename-only 결과는 matches 빈 배열.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.models.file_search_request import FileSearchRequest
from app.modules.file_search.schemas import (
    BrowseResponse,
    ContentMatch,
    DirectoryItem,
    FileMatch,
    FilePreviewResponse,
    FrequentSearchComboItem,
    SearchHistoryItem,
    SearchRequest,
    SearchResponse,
    SearchSuggestionItem,
    StatusResponse,
)
from app.modules.file_search.services.everything import EverythingService
from app.modules.file_search.services.presets import PRESETS
from app.modules.file_search.services.ripgrep import RipgrepService
from app.shared.process.session import is_session_0

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
KNOWN_SEARCH_ORIGINS = {"file-search", "plan-quick"}


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

    @staticmethod
    def _safe_json_loads(raw: Optional[str]) -> Optional[dict]:
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _normalize_query(query: str) -> str:
        # Normalize for suggestions: ignore case and collapse whitespace.
        return " ".join(query.lower().split())

    @staticmethod
    def _normalize_combo_values(values: Any, *, casefold: bool = False) -> tuple[str, ...]:
        if not isinstance(values, list):
            return ()
        normalized: list[str] = []
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            normalized.append(text.lower() if casefold else text)
        return tuple(sorted(set(normalized)))

    def _normalize_combo_key(self, request: SearchRequest) -> tuple:
        return (
            self._normalize_query(request.query),
            request.mode,
            bool(request.regex),
            bool(request.case_sensitive),
            (request.preset or "").strip().lower(),
            self._normalize_combo_values(request.paths, casefold=True),
            self._normalize_combo_values(request.extensions, casefold=True),
            self._normalize_combo_values(request.excludes, casefold=True),
        )

    @staticmethod
    def _summarize_paths(paths: list[str]) -> list[str]:
        tokens: list[str] = []
        for path in paths[:2]:
            raw = str(path).strip()
            if not raw:
                continue
            label = os.path.basename(raw.rstrip("\\/")) or raw
            tokens.append(label)
        extra = len(paths) - len(tokens)
        if extra > 0:
            tokens.append(f"+경로 {extra}")
        return tokens

    @staticmethod
    def _build_summary_tokens(request: SearchRequest) -> list[str]:
        mode_labels = {
            "filename": "파일명",
            "content": "내용",
            "both": "둘다",
        }
        tokens: list[str] = [mode_labels.get(request.mode, request.mode)]

        if request.preset:
            tokens.append(f"프리셋:{request.preset}")

        if request.regex:
            tokens.append("정규식")
        if request.case_sensitive:
            tokens.append("대소문자")

        tokens.extend(SearchService._summarize_paths(list(request.paths)))

        if request.extensions:
            tokens.extend([f".{ext.lstrip('.')}" for ext in list(request.extensions)[:2]])
            if len(request.extensions) > 2:
                tokens.append(f"+확장자 {len(request.extensions) - 2}")

        if request.excludes:
            first_exclude = str(request.excludes[0]).strip()
            if first_exclude:
                tokens.append(f"제외:{first_exclude}")
            if len(request.excludes) > 1:
                tokens.append(f"+제외 {len(request.excludes) - 1}")

        deduped: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if not token or token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        return deduped

    @staticmethod
    def _normalize_history_origin(req_data: dict[str, Any]) -> str:
        origin = str(req_data.get("origin") or "file-search").strip()
        if origin not in KNOWN_SEARCH_ORIGINS:
            return "file-search"
        return origin

    def _parse_history_request(self, req_data: Optional[dict[str, Any]]) -> Optional[SearchRequest]:
        if not req_data:
            return None

        normalized = dict(req_data)
        normalized["origin"] = self._normalize_history_origin(normalized)
        try:
            return SearchRequest(**normalized)
        except Exception:
            return None

    def _iter_completed_origin_rows(
        self,
        db: Session,
        *,
        origin: str,
        target_matches: int,
        chunk_size: int = 250,
        max_scanned_rows: Optional[int] = None,
    ) -> List[tuple[FileSearchRequest, SearchRequest]]:
        if target_matches <= 0:
            return []

        if max_scanned_rows is None:
            max_scanned_rows = max(chunk_size, target_matches * 5)
        max_scanned_rows = max(chunk_size, max_scanned_rows)

        matched_rows: List[tuple[FileSearchRequest, SearchRequest]] = []
        offset = 0
        scanned_rows = 0

        while scanned_rows < max_scanned_rows and len(matched_rows) < target_matches:
            rows_to_fetch = min(chunk_size, max_scanned_rows - scanned_rows)
            rows = (
                db.query(FileSearchRequest)
                .filter(FileSearchRequest.status == FileSearchRequest.STATUS_COMPLETED)
                .order_by(FileSearchRequest.created_at.desc(), FileSearchRequest.id.desc())
                .offset(offset)
                .limit(rows_to_fetch)
                .all()
            )
            if not rows:
                break

            offset += len(rows)
            scanned_rows += len(rows)

            for row in rows:
                request = self._parse_history_request(self._safe_json_loads(row.request_json))
                if not request:
                    continue
                if origin and request.origin != origin:
                    continue

                matched_rows.append((row, request))
                if len(matched_rows) >= target_matches:
                    break

        return matched_rows

    def get_history(self, db: Session, limit: int = 20, origin: str = "file-search") -> List[SearchHistoryItem]:
        """최근 검색 이력 (저장된 스냅샷 기반).

        - v1: request_json/result_json 파싱 기반, 별도 마이그레이션 없음
        - completed만 반환 (UI에서 스냅샷 복원용)
        """
        rows = self._iter_completed_origin_rows(
            db,
            origin=origin,
            target_matches=limit,
            chunk_size=100,
            max_scanned_rows=max(5000, limit * 50),
        )

        items: List[SearchHistoryItem] = []
        for row, request in rows:
            query = request.query.strip()
            if not query:
                continue

            result_data = self._safe_json_loads(row.result_json) if row.result_json else None
            total_count = 0
            sample_files: List[str] = []
            if result_data:
                try:
                    total_count = int(result_data.get("total_count") or 0)
                except (TypeError, ValueError):
                    total_count = 0

                raw_results = result_data.get("results") or []
                if isinstance(raw_results, list):
                    for r in raw_results[:10]:
                        if not isinstance(r, dict):
                            continue
                        name = r.get("file_name")
                        if not name:
                            fp = r.get("file_path") or ""
                            name = os.path.basename(fp) if fp else ""
                        if name:
                            sample_files.append(str(name))

            # Deduplicate while preserving order.
            dedup: List[str] = []
            seen = set()
            for name in sample_files:
                if name in seen:
                    continue
                seen.add(name)
                dedup.append(name)
            sample_files = dedup[:5]

            search_time_ms = 0
            try:
                search_time_ms = int(row.search_time_ms or 0)
            except (TypeError, ValueError):
                search_time_ms = 0
            if search_time_ms == 0 and result_data:
                try:
                    search_time_ms = int(result_data.get("search_time_ms") or 0)
                except (TypeError, ValueError):
                    search_time_ms = 0

            items.append(
                SearchHistoryItem(
                    search_id=row.search_id,
                    request=request,
                    query=query,
                    mode=request.mode,
                    created_at=row.created_at,
                    total_count=total_count,
                    search_time_ms=search_time_ms,
                    sample_files=sample_files,
                    origin=request.origin,
                )
            )

        return items

    def get_suggestions(self, db: Session, limit: int = 10, origin: str = "file-search") -> List[SearchSuggestionItem]:
        """검색어 추천 (최근 completed 이력 기반)."""
        rows = self._iter_completed_origin_rows(
            db,
            origin=origin,
            target_matches=2000,
            chunk_size=250,
            max_scanned_rows=10000,
        )

        buckets: dict[str, dict] = {}
        for row, request in rows:
            query_raw = request.query.strip()
            if not query_raw:
                continue

            norm = self._normalize_query(query_raw)
            if not norm:
                continue

            bucket = buckets.get(norm)
            if not bucket:
                buckets[norm] = {
                    "query": query_raw,
                    "count": 1,
                    "last_used_at": row.created_at or "",
                }
                continue

            bucket["count"] += 1
            created_at = row.created_at or ""
            if created_at and created_at >= bucket["last_used_at"]:
                bucket["last_used_at"] = created_at
                bucket["query"] = query_raw

        suggestions = [
            SearchSuggestionItem(
                query=v["query"],
                count=int(v["count"]),
                last_used_at=v["last_used_at"],
            )
            for v in buckets.values()
        ]
        suggestions.sort(key=lambda s: (s.count, s.last_used_at), reverse=True)
        return suggestions[:limit]

    def get_frequent_combos(
        self, db: Session, limit: int = 10, origin: str = "file-search"
    ) -> List[FrequentSearchComboItem]:
        """검색 폼 조합 추천 (최근 completed 이력 기반)."""
        rows = self._iter_completed_origin_rows(
            db,
            origin=origin,
            target_matches=2000,
            chunk_size=250,
            max_scanned_rows=10000,
        )

        buckets: dict[tuple, dict[str, Any]] = {}
        for row, request in rows:
            if not request.query.strip():
                continue

            key = self._normalize_combo_key(request)
            if not key[0]:
                continue

            bucket = buckets.get(key)
            if not bucket:
                buckets[key] = {
                    "request": request,
                    "label": request.query.strip(),
                    "count": 1,
                    "last_used_at": row.created_at or "",
                    "summary_tokens": self._build_summary_tokens(request),
                }
                continue

            bucket["count"] += 1
            created_at = row.created_at or ""
            if created_at and created_at >= bucket["last_used_at"]:
                bucket["request"] = request
                bucket["label"] = request.query.strip()
                bucket["last_used_at"] = created_at
                bucket["summary_tokens"] = self._build_summary_tokens(request)

        items = [
            FrequentSearchComboItem(
                request=value["request"],
                label=value["label"],
                count=int(value["count"]),
                last_used_at=value["last_used_at"],
                summary_tokens=value["summary_tokens"],
            )
            for value in buckets.values()
        ]
        items.sort(key=lambda item: (item.count, item.last_used_at), reverse=True)
        return items[:limit]

    # ------------------------------------------------------------------
    # 파일 열기
    # ------------------------------------------------------------------

    def open_file(self, file_path: str, line_number: Optional[int] = None) -> None:
        """파일을 VSCode 또는 기본 프로그램으로 열기."""
        if is_session_0():
            raise RuntimeError("Session 0에서는 파일 열기를 직접 실행할 수 없습니다. Redis file_search:open 큐를 사용하세요.")

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
