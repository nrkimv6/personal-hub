"""
archive_search.py — LLM/사람용 archive 검색 단일 진입점.

내부 구현(DB API 또는 파일 grep)을 숨기고 단일 인터페이스를 제공.

사용법:
  python scripts/archive_search.py --q watchdog
  python scripts/archive_search.py --q watchdog --tags worker,api --limit 5
  python scripts/archive_search.py --q watchdog --offline
  python scripts/archive_search.py --q watchdog --content --format json

EXIT CODES:
  0 = 결과 있음
  1 = 결과 없음
  2 = 에러 (API 응답 없음, 연결 실패 등)

실패 모드:
  API 실패 시 silent fallback 금지. stderr에 복구 힌트 출력 + sys.exit(2).
  --offline 플래그를 명시해야만 디스크 grep 경로로 진입.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (app.shared import 가능하도록)
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

# wiki_tags 공용 함수 (선택적)
try:
    from app.shared.wiki_tags import extract_wiki_tags as _extract_wiki_tags, load_whitelist as _load_whitelist
    _WIKI_TAGS_AVAILABLE = True
except ImportError:
    _WIKI_TAGS_AVAILABLE = False

# archive 기본 경로: .worktrees/plans/docs/archive/
ARCHIVE_DIR = _REPO_ROOT / ".worktrees" / "plans" / "docs" / "archive"
SCHEMA_PATH = _REPO_ROOT / "docs" / "wiki-schema.md"
API_BASE_URL = "http://localhost:8001"

DATE_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[-_]")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _load_whitelist_local(schema_path: Path = SCHEMA_PATH) -> set[str]:
    """wiki-schema.md §3 태그 Vocabulary에서 태그 목록 로드."""
    if _WIKI_TAGS_AVAILABLE:
        try:
            return _load_whitelist(schema_path)
        except Exception:
            pass
    # fallback: 직접 파싱
    if not schema_path.exists():
        return set()
    text = schema_path.read_text(encoding="utf-8")
    m = re.search(
        r"##\s*3\.\s*태그\s*Vocabulary.*?```\s*\n(.*?)\n```",
        text,
        re.DOTALL,
    )
    if not m:
        return set()
    words: set[str] = set()
    for tok in m.group(1).split():
        tok = tok.strip().lower()
        if tok:
            words.add(tok)
    return words


def search_via_api(
    q: str,
    tags: list[str] | None,
    date_from: str | None,
    date_to: str | None,
    deep: bool,
    limit: int,
) -> list[dict]:
    """GET /api/v1/plans/records 호출하여 결과 반환.

    실패 시 예외 전파 (ConnectionError, HTTPError, Timeout).
    silent fallback 없음.
    """
    if not _REQUESTS_AVAILABLE:
        raise RuntimeError("requests 라이브러리가 설치되지 않았습니다. pip install requests")

    url = f"{API_BASE_URL}/api/v1/plans/records"
    params: dict = {"limit": limit}
    if q:
        params["q"] = q
    if tags:
        params["tags"] = ",".join(tags)
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    if deep:
        params["deep"] = "true"

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    # 페이지네이션 래퍼: {"items": [...], "total": N} 형태도 지원
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return []


def _extract_date_from_filename(filename: str) -> str | None:
    """파일명에서 YYYY-MM-DD 날짜 추출."""
    m = DATE_FILENAME_RE.match(filename)
    return m.group(1) if m else None


def _extract_title(text: str, fallback: str) -> str:
    """본문에서 H1 제목 추출."""
    h1 = H1_RE.search(text)
    return h1.group(1).strip() if h1 else fallback


def _extract_one_liner(text: str) -> str:
    """본문에서 첫 비공백·비블록쿼트·비H1 단락의 첫 줄, 80자 절단."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(">") or s.startswith("---"):
            continue
        return s[:80].rstrip() + ("…" if len(s) > 80 else "")
    return ""


def search_offline(
    q: str,
    tags: list[str] | None,
    date_from: str | None,
    date_to: str | None,
    deep: bool,
    archive_dir: Path | None = None,
    limit: int = 20,
) -> list[dict]:
    """archive/*.md 파일을 로컬 grep으로 검색.

    파일명·H1·본문 앞 100자(deep=False) 또는 전체 본문(deep=True)에서 q 매칭.
    date_from/date_to: 파일명 앞 날짜로 필터.
    tags: extract_wiki_tags로 추출한 태그와 교집합 필터.
    """
    search_dir = archive_dir or ARCHIVE_DIR
    if not search_dir.exists():
        return []

    whitelist = _load_whitelist_local() if tags else set()
    date_from_d = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    date_to_d = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None

    q_lower = q.lower() if q else ""
    tags_lower = [t.lower() for t in tags] if tags else []

    results: list[dict] = []
    for p in sorted(search_dir.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        file_date_str = _extract_date_from_filename(p.name)
        if not file_date_str:
            continue

        # 날짜 범위 필터
        file_date = datetime.strptime(file_date_str, "%Y-%m-%d").date()
        if date_from_d and file_date < date_from_d:
            continue
        if date_to_d and file_date > date_to_d:
            continue

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        title = _extract_title(text, p.stem)
        one_liner = _extract_one_liner(text)

        # 태그 필터
        if tags_lower:
            if _WIKI_TAGS_AVAILABLE and whitelist:
                file_tags = set(_extract_wiki_tags(p.name, whitelist))
            else:
                file_tags = _extract_tags_local(p.name, title, text[:100], whitelist)
            if not file_tags.intersection(set(tags_lower)):
                continue

        # q 키워드 매칭
        if q_lower:
            if deep:
                haystack = f"{p.name} {title} {text}".lower()
            else:
                haystack = f"{p.name} {title} {text[:100]}".lower()
            if q_lower not in haystack:
                continue

        try:
            rel = p.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
        except ValueError:
            rel = p.as_posix()

        # 태그 정보 수집 (결과 출력용)
        if _WIKI_TAGS_AVAILABLE and whitelist:
            file_tags_list = sorted(_extract_wiki_tags(p.name, whitelist))
        else:
            file_tags_list = sorted(_extract_tags_local(p.name, title, text[:100], whitelist))

        results.append({
            "title": title,
            "summary": one_liner,
            "tags": file_tags_list,
            "file_path": rel,
            "archived_at": file_date_str,
        })

        if len(results) >= limit:
            break

    return results


def _extract_tags_local(filename: str, title: str, body_prefix: str, whitelist: set[str]) -> set[str]:
    """로컬 태그 추출 (wiki_tags 미사용 시 fallback)."""
    haystack = f"{filename} {title} {body_prefix}".lower()
    matched: set[str] = set()
    for tag in whitelist:
        if tag == "untagged":
            continue
        if re.search(rf"\b{re.escape(tag)}\b", haystack):
            matched.add(tag)
    return matched or {"untagged"}


def render_text(rows: list[dict]) -> str:
    """결과를 파이프 테이블 형식으로 렌더링."""
    if not rows:
        return "(검색 결과 없음)"

    lines = ["| date | tags | title | one-liner |", "|------|------|-------|-----------|"]
    for row in rows:
        d = row.get("archived_at", "")[:10]
        tags_raw = row.get("tags", [])
        if isinstance(tags_raw, list):
            tags_str = ",".join(tags_raw)
        else:
            tags_str = str(tags_raw)
        title = (row.get("title") or "").replace("|", "\\|")
        summary = (row.get("summary") or "").replace("|", "\\|")
        if len(summary) > 60:
            summary = summary[:60].rstrip() + "…"
        lines.append(f"| {d} | {tags_str} | {title} | {summary} |")
        # path는 별도 행으로 들여쓰기 (LLM grep 유도)
        file_path = row.get("file_path", "")
        if file_path:
            lines.append(f"    path: {file_path}")

    return "\n".join(lines)


def render_json(rows: list[dict]) -> str:
    """결과를 JSON 형식으로 렌더링."""
    return json.dumps(rows, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="archive 검색 — DB API 또는 파일 grep (단일 진입점)"
    )
    ap.add_argument("--q", default="", help="검색 키워드")
    ap.add_argument("--tags", default="", help="태그 필터 (comma-separated, 예: watchdog,worker)")
    ap.add_argument("--date-from", default="", help="시작일 (YYYY-MM-DD)")
    ap.add_argument("--date-to", default="", help="종료일 (YYYY-MM-DD)")
    ap.add_argument("--content", action="store_true", help="본문 전체 검색 (deep=true)")
    ap.add_argument("--offline", action="store_true", help="DB 미사용, 파일 grep 모드 (재해복구용)")
    ap.add_argument("--format", choices=["text", "json"], default="text", help="출력 형식")
    ap.add_argument("--limit", type=int, default=20, help="최대 결과 수 (기본 20)")
    args = ap.parse_args(argv)

    tags_list = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    date_from = args.date_from.strip() or None
    date_to = args.date_to.strip() or None

    if args.offline:
        # 명시적 오프라인 모드 — DB 안 씀
        rows = search_offline(
            q=args.q,
            tags=tags_list,
            date_from=date_from,
            date_to=date_to,
            deep=args.content,
            limit=args.limit,
        )
    else:
        # DB API 모드 — 실패 시 hard exit, silent fallback 없음
        url = f"{API_BASE_URL}/api/v1/plans/records"
        try:
            rows = search_via_api(
                q=args.q,
                tags=tags_list,
                date_from=date_from,
                date_to=date_to,
                deep=args.content,
                limit=args.limit,
            )
        except Exception as e:
            err_type = type(e).__name__
            print(
                f"ERROR: archive DB API 응답 없음 ({url})\n"
                f"원인: {err_type}: {e}\n"
                "복구 힌트:\n"
                f"  1. API 상태 확인: curl {API_BASE_URL}/api/v1/plans/records/guide-status\n"
                f"  2. 오프라인 모드로 파일 grep: archive-search --offline {' '.join(sys.argv[1:])}",
                file=sys.stderr,
            )
            sys.exit(2)

    if args.format == "json":
        print(render_json(rows))
    else:
        print(render_text(rows))

    if not rows:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
