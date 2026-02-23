"""
ripgrep subprocess 연동 서비스

rg --json 출력을 파싱해 파일 내용 검색 결과를 반환합니다.
RIPGREP_TIMEOUT(기본 120초) 이후 자동 중단됩니다.

rg JSON 출력 타입:
  - type:"begin"  — 파일 시작
  - type:"match"  — 매칭 라인 (path, line_number, lines, submatches)
  - type:"context"— 컨텍스트 라인
  - type:"end"    — 파일 끝 (elapsed_total, stats)
  - type:"summary"— 전체 요약
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import shutil
from collections import defaultdict
from typing import List, Optional, Tuple

from app.modules.file_search.config import RIPGREP_TIMEOUT

logger = logging.getLogger("file_search.ripgrep")


class RipgrepService:
    """ripgrep CLI를 subprocess로 실행하는 파일 내용 검색 서비스."""

    def __init__(self) -> None:
        self._rg_path: Optional[str] = shutil.which("rg") or self._find_rg_fallback()

    @staticmethod
    def _find_rg_fallback() -> Optional[str]:
        """winget 설치 경로 등에서 rg.exe를 탐색."""
        patterns = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*ripgrep*\*\rg.exe"),
            r"C:\ProgramData\chocolatey\bin\rg.exe",
        ]
        for pat in patterns:
            found = glob.glob(pat)
            if found:
                return found[0]
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        paths: List[str] = None,
        extensions: List[str] = None,
        excludes: List[str] = None,
        regex: bool = True,
        case_sensitive: bool = False,
        context_lines: int = 2,
        max_results: int = 100,
    ) -> List[dict]:
        """파일 내용 검색.

        Args:
            query: 검색 키워드 또는 정규식
            paths: 검색 경로 목록 (빈 리스트면 현재 디렉토리)
            extensions: 확장자 필터
            excludes: 제외 경로/패턴
            regex: True면 정규식, False면 리터럴 문자열
            case_sensitive: True면 대소문자 구분
            context_lines: 매칭 라인 전후 컨텍스트 라인 수
            max_results: 최대 결과 파일 수

        Returns:
            list[dict]: 파일별 매칭 정보
        """
        if not query:
            return []

        rg = self._rg_path
        if not rg:
            logger.error("ripgrep(rg)이 설치되어 있지 않습니다. 'winget install BurntSushi.ripgrep.MSVC'로 설치하세요.")
            raise FileNotFoundError("ripgrep(rg)을 찾을 수 없습니다.")

        args = self._build_args(
            query=query,
            paths=paths or [],
            extensions=extensions or [],
            excludes=excludes or [],
            regex=regex,
            case_sensitive=case_sensitive,
            context_lines=context_lines,
        )

        stdout, stderr = await self._run(rg, args)

        if stderr and not stdout:
            # 잘못된 정규식 등 rg 오류
            err_msg = stderr.strip()[:200]
            logger.warning(f"ripgrep 오류: {err_msg}")
            if "regex parse error" in err_msg.lower() or "error parsing" in err_msg.lower():
                raise ValueError(f"잘못된 정규식: {err_msg}")

        return self._parse_json_output(stdout, max_results=max_results)

    def is_available(self) -> Tuple[bool, Optional[str]]:
        """ripgrep 설치 여부 및 경로 반환."""
        if self._rg_path:
            return True, self._rg_path
        return False, None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_args(
        self,
        query: str,
        paths: List[str],
        extensions: List[str],
        excludes: List[str],
        regex: bool,
        case_sensitive: bool,
        context_lines: int,
    ) -> List[str]:
        """rg CLI 인수 목록 생성."""
        args: List[str] = [
            "--json",               # 구조화된 JSON 출력
            "--no-heading",
            "--with-filename",
        ]

        # 리터럴 문자열 모드 (regex=False)
        if not regex:
            args.append("--fixed-strings")

        # 대소문자 구분 (기본: 무시)
        if not case_sensitive:
            args.append("--ignore-case")

        # 컨텍스트 라인 (0이면 생략)
        if context_lines > 0:
            args += ["-C", str(context_lines)]

        # 확장자 필터: 점 포함/미포함 모두 수용
        if extensions:
            cleaned = [ext.lstrip(".") for ext in extensions]
            for ext in cleaned:
                args += ["-g", f"*.{ext}"]

        # 제외 패턴
        for excl in excludes:
            args += ["--glob", f"!{excl}"]

        # 검색 키워드
        args.append(query)

        # 검색 경로 (없으면 rg가 현재 디렉토리 사용)
        args.extend(paths)

        return args

    async def _run(self, rg: str, args: List[str]) -> Tuple[str, str]:
        """subprocess 실행 (RIPGREP_TIMEOUT 적용)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                rg,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=RIPGREP_TIMEOUT,
            )
            return stdout_bytes.decode("utf-8", errors="replace"), stderr_bytes.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            logger.warning(f"ripgrep 타임아웃 ({RIPGREP_TIMEOUT}초). RIPGREP_TIMEOUT 환경변수로 상향 가능.")
            raise TimeoutError(f"ripgrep이 {RIPGREP_TIMEOUT}초 내에 완료되지 않았습니다.")
        except FileNotFoundError:
            raise FileNotFoundError("ripgrep(rg)을 찾을 수 없습니다.")

    def _parse_json_output(self, stdout: str, max_results: int) -> List[dict]:
        """rg --json 출력 파싱 → 파일별 매칭 그룹핑.

        rg는 match 전에 context 라인을 emit하므로 context_before 버퍼링이 필요.
        흐름: context(before) → match → context(after) → context(before next match) ...
        """
        # 파일 경로 → 매칭 목록
        file_matches: dict[str, list] = defaultdict(list)
        file_order: list[str] = []  # 순서 보존
        # 파일 경로 → 아직 match를 만나지 못한 context 라인 버퍼 (context_before 후보)
        pending_context: dict[str, list] = defaultdict(list)

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")
            data = obj.get("data", {})

            if msg_type == "match":
                file_path = data.get("path", {}).get("text", "")
                if not file_path:
                    continue

                if file_path not in file_matches:
                    file_order.append(file_path)
                    # max_results 초과 시 조기 종료
                    if len(file_order) > max_results:
                        break

                line_number = data.get("line_number", 0)
                lines_data = data.get("lines", {})
                line_text = lines_data.get("text", "").rstrip("\n")
                submatches = [
                    {
                        "start": sm.get("start", 0),
                        "end": sm.get("end", 0),
                        "match": sm.get("match", {}).get("text", ""),
                    }
                    for sm in data.get("submatches", [])
                ]

                # 이전에 버퍼에 쌓인 context 라인 → context_before
                context_before = pending_context.pop(file_path, [])

                file_matches[file_path].append({
                    "line_number": line_number,
                    "line_text": line_text,
                    "context_before": context_before,
                    "context_after": [],
                    "submatches": submatches,
                })

            elif msg_type == "context":
                file_path = data.get("path", {}).get("text", "")
                if not file_path:
                    continue
                ctx_line = data.get("lines", {}).get("text", "").rstrip("\n")
                ctx_line_num = data.get("line_number", 0)
                # .get() 사용 — defaultdict key 자동 생성 방지
                matches = file_matches.get(file_path)

                if matches is None:
                    # 아직 match가 없음 → context_before 버퍼에 쌓기
                    pending_context[file_path].append(ctx_line)
                else:
                    last_match = matches[-1]
                    if ctx_line_num < last_match["line_number"]:
                        # 이전 match의 context_before (안전망)
                        last_match["context_before"].append(ctx_line)
                    else:
                        # context_after
                        last_match["context_after"].append(ctx_line)

        # max_results 제한 적용
        results = []
        for fp in file_order[:max_results]:
            import os
            results.append({
                "file_path": fp,
                "file_name": os.path.basename(fp),
                "file_size": None,
                "modified": None,
                "matches": file_matches[fp],
            })

        return results
