"""
archive_index_backfill.py — 1회성 백필 유틸

`docs/archive/*.md` 전체를 스캔해:
  1) `docs/archive/INDEX.md`의 INDEX:BEGIN/END 블록을 재생성 (idempotent)
  2) `docs/dev-guide/*.md`의 AUTO:BEGIN/END 블록을 각 가이드의 owns_archive_tags와
     매칭되는 최근 cutoff_days 이내 archive로 재생성

LLM 호출 없음 — 파일명/첫 H1/본문 앞 100자에서 화이트리스트 규칙 매칭만 사용.
운영 코드 아님. 태그 vocabulary 확장 시 `--apply` 재실행.

사용법:
  python scripts/archive_index_backfill.py --dry-run       # 임의 20건 stdout
  python scripts/archive_index_backfill.py --apply         # INDEX + 가이드 전량 갱신
  python scripts/archive_index_backfill.py --apply --cutoff-days 90
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import yaml

# DB 세션 헬퍼 (선택적 — DB 미연결 시에도 기존 파일 기반 동작 유지)
try:
    from app.database import SessionLocal as _SessionLocal
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False

# wiki_tags 공용 함수 (선택적)
try:
    from app.shared.wiki_tags import (
        extract_wiki_tags as _extract_wiki_tags_shared,
        load_whitelist as _load_wl_shared,
    )
    _WIKI_TAGS_AVAILABLE = True
except ImportError:
    _WIKI_TAGS_AVAILABLE = False

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT / "docs" / "archive"
DEV_GUIDE_DIR = ROOT / "docs" / "dev-guide"
INDEX_PATH = ARCHIVE_DIR / "INDEX.md"
META_PATH = DEV_GUIDE_DIR / "_meta.yaml"
SCHEMA_PATH = ROOT / "docs" / "wiki-schema.md"

INDEX_BEGIN = "<!-- INDEX:BEGIN -->"
INDEX_END = "<!-- INDEX:END -->"
AUTO_BEGIN = "<!-- AUTO:BEGIN -->"
AUTO_END = "<!-- AUTO:END -->"

DATE_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[-_]")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

EXIT_OK = 0
EXIT_NO_WHITELIST = 1
EXIT_NO_ARCHIVE = 2


# ----- DB 세션 헬퍼 -----

def get_db_session():
    """SessionLocal 세션 반환. DB 미연결 시 RuntimeError."""
    if not _DB_AVAILABLE:
        raise RuntimeError("app.database not available — run from repo root or install app package")
    session = _SessionLocal()
    try:
        return session
    except Exception:
        session.close()
        raise


# ----- 데이터 -----

@dataclass(frozen=True)
class ArchiveRow:
    date: str  # YYYY-MM-DD
    tags: tuple[str, ...]
    title: str
    one_liner: str
    path: str  # relative to repo root, POSIX

    def render_row(self) -> str:
        tags_str = ",".join(self.tags)
        # pipe 이스케이프
        title = self.title.replace("|", "\\|")
        one = self.one_liner.replace("|", "\\|")
        return f"| {self.date} | {tags_str} | {title} | {one} | [{Path(self.path).name}](../../{self.path}) |"


# ----- 추출 -----

def extract_meta(path: Path) -> dict:
    """파일명/본문에서 (date, title, one_liner) 추출.

    - date: 파일명 `YYYY-MM-DD` prefix. 없으면 ValueError.
    - title: 첫 H1. 없으면 파일명(확장자 제거) 폴백.
    - one_liner: 첫 비공백·비블록쿼트·비H1 단락의 첫 줄, 80자 절단.
    """
    m = DATE_FILENAME_RE.match(path.name)
    if not m:
        raise ValueError(f"filename lacks YYYY-MM-DD prefix: {path.name}")
    d = m.group(1)

    text = path.read_text(encoding="utf-8", errors="replace")

    h1 = H1_RE.search(text)
    if h1:
        title = h1.group(1).strip()
    else:
        title = path.stem

    one_liner = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(">") or s.startswith("---"):
            continue
        one_liner = s
        break
    if len(one_liner) > 80:
        one_liner = one_liner[:80].rstrip() + "…"

    return {"date": d, "title": title, "one_liner": one_liner}


def extract_tags(filename: str, title: str, body: str, whitelist: set[str]) -> list[str]:
    """파일명/제목/본문 앞 100자에서 화이트리스트 단어 소문자 매칭 (하위 호환 래퍼).

    wiki_tags.extract_wiki_tags()로 위임. title/body는 파일명과 함께 haystack에 포함.
    매칭 0건이면 `["untagged"]` 단독 부여.
    """
    if _WIKI_TAGS_AVAILABLE:
        # 파일명 + title + body 앞 100자를 하나의 가상 파일명으로 합쳐 매칭
        # wiki_tags는 filename만 받으므로 haystack을 직접 구성
        haystack = f"{filename} {title} {body[:100]}".lower()
        matched: list[str] = []
        for tag in whitelist:
            if tag == "untagged":
                continue
            if re.search(rf"\b{re.escape(tag)}\b", haystack):
                matched.append(tag)
        if not matched:
            return ["untagged"]
        return sorted(set(matched))
    # fallback: 동일 로직 직접 실행
    haystack = f"{filename} {title} {body[:100]}".lower()
    matched = []
    for tag in whitelist:
        if tag == "untagged":
            continue
        if re.search(rf"\b{re.escape(tag)}\b", haystack):
            matched.append(tag)
    if not matched:
        return ["untagged"]
    return sorted(set(matched))


def load_whitelist(schema_path: Path = SCHEMA_PATH) -> set[str]:
    """`docs/wiki-schema.md`의 `## 3. 태그 Vocabulary` 섹션 코드블럭에서 단어 추출 (래퍼)."""
    if _WIKI_TAGS_AVAILABLE:
        return _load_wl_shared(schema_path)
    # fallback: 직접 파싱
    if not schema_path.exists():
        raise FileNotFoundError(f"wiki-schema.md not found: {schema_path}")
    text = schema_path.read_text(encoding="utf-8")
    m = re.search(
        r"##\s*3\.\s*태그\s*Vocabulary.*?```\s*\n(.*?)\n```",
        text,
        re.DOTALL,
    )
    if not m:
        raise ValueError("태그 vocabulary section not found in wiki-schema.md")
    words: set[str] = set()
    for tok in m.group(1).split():
        tok = tok.strip().lower()
        if tok:
            words.add(tok)
    if not words:
        raise ValueError("태그 vocabulary section is empty")
    return words


# ----- 스캔 -----

def scan_archive(archive_dir: Path, whitelist: set[str], root: Path = ROOT) -> list[ArchiveRow]:
    rows: list[ArchiveRow] = []
    for p in sorted(archive_dir.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        try:
            meta = extract_meta(p)
        except ValueError:
            # 날짜 prefix 없는 파일은 스킵
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        tags = extract_tags(p.name, meta["title"], body, whitelist)
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = p.as_posix()
        rows.append(
            ArchiveRow(
                date=meta["date"],
                tags=tuple(tags),
                title=meta["title"],
                one_liner=meta["one_liner"],
                path=rel,
            )
        )
    # date desc, 동일 날짜 파일명 asc
    rows.sort(key=lambda r: (r.date, Path(r.path).name), reverse=False)
    rows.sort(key=lambda r: r.date, reverse=True)
    return rows


# ----- 렌더 -----

def render_index(rows: Iterable[ArchiveRow]) -> str:
    header = "| date | tags | title | one-liner | path |\n|------|------|-------|-----------|------|"
    body = "\n".join(r.render_row() for r in rows)
    return f"{header}\n{body}\n" if body else f"{header}\n"


def replace_marker_block(text: str, begin: str, end: str, new_inner: str) -> str:
    pattern = re.compile(
        rf"({re.escape(begin)})(.*?)({re.escape(end)})",
        re.DOTALL,
    )
    if not pattern.search(text):
        raise ValueError(f"markers not found: {begin}..{end}")
    replacement = f"{begin}\n{new_inner.rstrip()}\n{end}"
    # callable form avoids backref interpretation of '\|' etc. in replacement
    return pattern.sub(lambda _m: replacement, text)


def write_index(rows: list[ArchiveRow], index_path: Path | None = None) -> None:
    path = index_path if index_path is not None else INDEX_PATH
    text = path.read_text(encoding="utf-8")
    inner = render_index(rows)
    new_text = replace_marker_block(text, INDEX_BEGIN, INDEX_END, inner)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")


def backfill_guide_blocks(
    rows: list[ArchiveRow],
    meta_yaml: dict,
    guide_dir: Path | None = None,
    cutoff_days: int = 90,
    today: date | None = None,
) -> dict[str, int]:
    guide_dir = guide_dir if guide_dir is not None else DEV_GUIDE_DIR
    """각 가이드의 AUTO 블록을 owns_archive_tags 매칭된 최근 archive로 치환.

    반환: {guide_filename: 매칭 행 수}
    """
    today = today or date.today()
    cutoff = today - timedelta(days=cutoff_days)
    result: dict[str, int] = {}
    for guide_name, meta in meta_yaml.items():
        owns = set(meta.get("owns_archive_tags") or [])
        if not owns:
            matched: list[ArchiveRow] = []
        else:
            matched = [
                r
                for r in rows
                if set(r.tags) & owns
                and datetime.strptime(r.date, "%Y-%m-%d").date() >= cutoff
            ]
        guide_path = guide_dir / guide_name
        if not guide_path.exists():
            continue
        text = guide_path.read_text(encoding="utf-8")
        if AUTO_BEGIN not in text:
            continue
        if matched:
            inner = (
                "| date | tags | title | one-liner | path |\n"
                "|------|------|-------|-----------|------|\n"
                + "\n".join(r.render_row() for r in matched)
            )
        else:
            inner = "_(매칭되는 최근 archive 없음)_"
        try:
            new_text = replace_marker_block(text, AUTO_BEGIN, AUTO_END, inner)
        except ValueError:
            continue
        if new_text != text:
            guide_path.write_text(new_text, encoding="utf-8")
        # last_archive_scan 갱신 (가이드 파일 수정 여부와 무관하게 스캔 사실 기록)
        meta["last_archive_scan"] = today.isoformat()
        result[guide_name] = len(matched)
    return result


def load_meta_yaml(path: Path | None = None) -> dict:
    p = path if path is not None else META_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save_meta_yaml(data: dict, path: Path | None = None) -> None:
    p = path if path is not None else META_PATH
    p.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# ----- CLI -----

def cmd_dry_run(rows: list[ArchiveRow], n: int = 20) -> None:
    sample = random.sample(rows, min(n, len(rows)))
    print(f"[dry-run] total archives: {len(rows)}, sample: {len(sample)}")
    for r in sample:
        print(f"  {r.date} | {','.join(r.tags):40} | {r.title[:60]}")


def cmd_apply(rows: list[ArchiveRow], cutoff_days: int) -> None:
    write_index(rows)
    meta = load_meta_yaml()
    guide_result = backfill_guide_blocks(rows, meta, cutoff_days=cutoff_days)
    save_meta_yaml(meta)
    print(f"[apply] INDEX.md: {len(rows)} rows")
    print(f"[apply] guide AUTO blocks updated: {len(guide_result)}")
    for name, count in sorted(guide_result.items()):
        print(f"  {name}: {count}")


def extract_guide_summary(guide_path: Path) -> str:
    """가이드 파일에서 H1 이후 첫 비공백·비블록쿼트 단락 80자 절단.

    extract_meta()의 one_liner 추출 로직과 동일.
    """
    try:
        text = guide_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    one_liner = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(">") or s.startswith("---"):
            continue
        one_liner = s
        break
    if len(one_liner) > 80:
        one_liner = one_liner[:80].rstrip() + "…"
    return one_liner


def render_guide_status_index(statuses: list[dict], guide_dir: Path | None = None) -> str:
    """guide-status 목록을 INDEX.md 테이블로 렌더링.

    Args:
        statuses: get_guide_status() 반환값 리스트
        guide_dir: dev-guide 디렉토리 (summary 추출용). None이면 DEV_GUIDE_DIR.

    Returns:
        마커 블록 내 삽입용 텍스트 (헤더 포함).
    """
    guide_dir = guide_dir or DEV_GUIDE_DIR
    header = "| guide | 현행 요약 | last_updated | pending |\n|-------|----------|--------------|---------|"
    rows_str: list[str] = []
    for item in statuses:
        guide = item.get("guide", "")
        last_updated = item.get("last_updated") or item.get("last_archive_scan", "")
        pending = item.get("pending_count", 0)
        # 현행 요약: 가이드 파일 첫 단락
        summary = extract_guide_summary(guide_dir / guide) if guide else ""
        guide_esc = guide.replace("|", "\\|")
        summary_esc = summary.replace("|", "\\|")
        rows_str.append(f"| {guide_esc} | {summary_esc} | {last_updated} | {pending} |")
    body = "\n".join(rows_str)
    return f"{header}\n{body}\n" if body else f"{header}\n"


def cmd_guide_status(cutoff_days: int = 90) -> None:
    """--mode guide-status: DB 기반 guide-status INDEX.md 재생성."""
    if not _DB_AVAILABLE:
        print("[guide-status] DB not available — DB 연결 필요", file=sys.stderr)
        sys.exit(1)
    try:
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
    except ImportError as e:
        print(f"[guide-status] PlanRecordService import 실패: {e}", file=sys.stderr)
        sys.exit(1)

    db = get_db_session()
    try:
        svc = PlanRecordService(db)
        statuses = svc.get_guide_status()
    finally:
        db.close()

    inner = render_guide_status_index(statuses)

    # INDEX.md에서 GUIDE_STATUS 마커 블록 치환 (없으면 생성 안 함)
    GUIDE_STATUS_BEGIN = "<!-- GUIDE_STATUS:BEGIN -->"
    GUIDE_STATUS_END = "<!-- GUIDE_STATUS:END -->"
    text = INDEX_PATH.read_text(encoding="utf-8")
    if GUIDE_STATUS_BEGIN not in text:
        print(f"[guide-status] INDEX.md에 {GUIDE_STATUS_BEGIN} 마커 없음 — 출력만 합니다:")
        print(inner)
        return

    new_text = replace_marker_block(text, GUIDE_STATUS_BEGIN, GUIDE_STATUS_END, inner)
    if new_text != text:
        INDEX_PATH.write_text(new_text, encoding="utf-8")
    print(f"[guide-status] INDEX.md guide-status 섹션 갱신 완료 ({len(statuses)} guides)")


def backfill_guide_blocks_db(
    db,
    meta_yaml: dict,
    guide_dir: Path | None = None,
    cutoff_days: int = 90,
    today: date | None = None,
) -> dict[str, int]:
    """AUTO 블록을 DB PlanRecord 기반 summary 포함으로 렌더링.

    기존 backfill_guide_blocks()와 병행. DB PlanRecord에서 extract_wiki_tags() 기반 매칭.
    summary=None 레코드는 extract_meta() one_liner fallback.

    Returns: {guide_filename: 매칭 행 수}
    """
    from app.models.plan_record import PlanRecord as PlanRecordModel
    # 모듈 레벨 shared 함수 사용 (mock 가능하도록 직접 참조)
    _ewt = _extract_wiki_tags_shared if _WIKI_TAGS_AVAILABLE else None
    _lwl = _load_wl_shared if _WIKI_TAGS_AVAILABLE else None

    guide_dir = guide_dir or DEV_GUIDE_DIR
    today = today or date.today()
    cutoff = today - timedelta(days=cutoff_days)

    # whitelist 로드
    try:
        wl = _lwl() if _lwl else load_whitelist()
    except Exception:
        wl = set()

    # PlanRecord 전체 조회 (archived_at IS NOT NULL)
    records = db.query(PlanRecordModel).filter(PlanRecordModel.archived_at.isnot(None)).all()

    # 레코드를 guide별로 분류
    guide_records: dict[str, list] = {g: [] for g in meta_yaml}
    for rec in records:
        # archived_at cutoff 필터
        rec_date = rec.archived_at.date() if rec.archived_at else None
        if rec_date is None or rec_date < cutoff:
            continue
        filename = Path(rec.file_path).name
        if _ewt:
            tags = set(_ewt(filename, wl))
        else:
            tags = set()

        for guide_name, meta in meta_yaml.items():
            owns = set(meta.get("owns_archive_tags") or [])
            if owns and tags & owns:
                guide_records[guide_name].append(rec)

    result: dict[str, int] = {}
    for guide_name, recs in guide_records.items():
        guide_path = guide_dir / guide_name
        if not guide_path.exists():
            continue
        text = guide_path.read_text(encoding="utf-8")
        if AUTO_BEGIN not in text:
            continue

        if recs:
            # | date | title | summary | path |
            header_line = "| date | title | summary | path |"
            sep_line = "|------|-------|---------|------|"
            body_lines: list[str] = []
            for rec in sorted(recs, key=lambda r: (r.archived_at or datetime.min), reverse=True):
                rec_date = rec.archived_at.strftime("%Y-%m-%d") if rec.archived_at else ""
                title = (rec.title or Path(rec.file_path).stem).replace("|", "\\|")
                # summary: PlanRecord.summary → one_liner fallback
                summary = ""
                if rec.summary:
                    summary = rec.summary[:80].replace("|", "\\|")
                else:
                    try:
                        meta_info = extract_meta(Path(rec.file_path))
                        summary = meta_info["one_liner"].replace("|", "\\|")
                    except Exception:
                        pass
                path_name = Path(rec.file_path).name
                rel_path = rec.file_path.replace("\\", "/")
                body_lines.append(f"| {rec_date} | {title} | {summary} | [{path_name}](../../{rel_path}) |")
            inner = f"{header_line}\n{sep_line}\n" + "\n".join(body_lines)
        else:
            inner = "_(매칭되는 최근 archive 없음)_"

        try:
            new_text = replace_marker_block(text, AUTO_BEGIN, AUTO_END, inner)
        except ValueError:
            continue
        if new_text != text:
            guide_path.write_text(new_text, encoding="utf-8")
        result[guide_name] = len(recs)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="임의 20건 추출 결과 stdout")
    mode.add_argument("--apply", action="store_true", help="INDEX.md + 가이드 AUTO 블록 일괄 갱신 (legacy)")
    ap.add_argument("--cutoff-days", type=int, default=90, help="가이드 AUTO 블록 최근 N일")
    ap.add_argument(
        "--mode",
        choices=["legacy", "guide-status"],
        default="legacy",
        help="legacy: 기존 파일 기반(기본), guide-status: DB 기반 INDEX.md 재생성",
    )
    args = ap.parse_args(argv)

    if not ARCHIVE_DIR.exists():
        print(f"archive dir not found: {ARCHIVE_DIR}", file=sys.stderr)
        return EXIT_NO_ARCHIVE

    # guide-status 모드는 DB 필요, whitelist/rows 스캔 불필요
    if args.mode == "guide-status":
        cmd_guide_status(args.cutoff_days)
        return EXIT_OK

    try:
        whitelist = load_whitelist()
    except (FileNotFoundError, ValueError) as e:
        print(f"whitelist load failed: {e}", file=sys.stderr)
        return EXIT_NO_WHITELIST

    rows = scan_archive(ARCHIVE_DIR, whitelist)

    if args.dry_run:
        cmd_dry_run(rows)
    else:
        cmd_apply(rows, args.cutoff_days)

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
