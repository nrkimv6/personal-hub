"""
Everything HTTP API 연동 서비스

Everything (voidtools) HTTP 서버에 쿼리를 전송하고 결과를 파싱합니다.
Everything이 실행 중이지 않거나 HTTP 서버가 비활성화된 경우 빈 리스트를 반환합니다.

Everything HTTP API 쿼리 문법:
  - 정규식:     regex:패턴
  - 확장자:     ext:py;ts;js
  - 경로:       path:D:\work\project
  - 제외:       !node_modules
  - 조합:       ext:py path:D:\work !__pycache__
"""
from __future__ import annotations

import logging
from typing import List
from urllib.parse import quote

import httpx

from app.modules.file_search.config import EVERYTHING_HOST, EVERYTHING_PORT

logger = logging.getLogger("file_search.everything")


class EverythingService:
    """Everything HTTP API 를 통한 파일명 검색 서비스."""

    def __init__(self) -> None:
        self._base_url = f"http://{EVERYTHING_HOST}:{EVERYTHING_PORT}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        regex: bool = False,
        extensions: List[str] = None,
        paths: List[str] = None,
        excludes: List[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """파일명 검색.

        Args:
            query: 검색 키워드 (빈 문자열이면 빈 결과)
            regex: True면 정규식 모드
            extensions: 확장자 필터 (점 없이 전달, 예: ["py", "ts"])
            paths: 검색 경로 목록 (빈 리스트면 전체)
            excludes: 제외 패턴 목록
            max_results: 최대 결과 수

        Returns:
            list[dict]: 파일 정보 딕셔너리 목록
        """
        if not query:
            return []

        built_query = self._build_query(
            query=query,
            regex=regex,
            extensions=extensions or [],
            paths=paths or [],
            excludes=excludes or [],
        )

        params = {
            "s": built_query,
            "j": "1",           # JSON 출력
            "c": str(max_results),
            "path_column": "1",
            "size_column": "1",
            "date_modified_column": "1",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._base_url, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError:
            logger.warning("Everything HTTP 서버 연결 실패 (서버가 실행 중인지 확인)")
            return []
        except httpx.ReadTimeout:
            logger.warning("Everything HTTP 서버 응답 타임아웃")
            return []
        except Exception as exc:
            logger.warning(f"Everything 검색 오류: {exc}")
            return []

        return self._parse_results(data)

    async def is_available(self) -> tuple[bool, str]:
        """Everything HTTP 서버 연결 상태 확인.

        Returns:
            (ok, message) 튜플
        """
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(self._base_url, params={"j": "1", "c": "0", "s": "test"})
                resp.raise_for_status()
            return True, "연결됨"
        except httpx.ConnectError:
            return False, f"연결 실패 (포트: {EVERYTHING_PORT})"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_query(
        self,
        query: str,
        regex: bool,
        extensions: List[str],
        paths: List[str],
        excludes: List[str],
    ) -> str:
        """Everything 쿼리 문자열 조합.

        우선순위: regex > 확장자 > 경로 > 제외 > 키워드
        """
        parts: List[str] = []

        # 정규식 모드
        if regex:
            parts.append(f"regex:{query}")
        else:
            parts.append(query)

        # 확장자 필터 — 점 포함/미포함 모두 수용
        if extensions:
            cleaned = [ext.lstrip(".") for ext in extensions]
            parts.append(f"ext:{';'.join(cleaned)}")

        # 경로 필터
        for path in paths:
            parts.append(f"path:{path}")

        # 제외 패턴
        for exc in excludes:
            parts.append(f"!{exc}")

        return " ".join(parts)

    def _parse_results(self, data: dict) -> List[dict]:
        """Everything JSON 응답 파싱."""
        results = []
        try:
            items = data.get("results", [])
            for item in items:
                path = item.get("path", "")
                name = item.get("name", "")
                full_path = f"{path}\\{name}" if path and name else name or path

                results.append({
                    "file_path": full_path,
                    "file_name": name,
                    "file_size": item.get("size"),
                    "modified": item.get("date_modified"),
                })
        except Exception as exc:
            logger.warning(f"Everything 응답 파싱 오류: {exc}")

        return results
