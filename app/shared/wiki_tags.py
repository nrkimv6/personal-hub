"""
wiki_tags.py — archive 파일명 기반 wiki 태그 추출 공용 함수

archive_index_backfill.py에서 분리. guide-status 매칭, PlanRecord 교차 등에 재사용.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Union

import yaml

# 기본 경로 (importable 위치 기준 — ROOT/docs/... 로 resolve)
_HERE = Path(__file__).resolve().parent.parent.parent  # repo root
_DEFAULT_SCHEMA_PATH = _HERE / "docs" / "wiki-schema.md"
_DEFAULT_META_PATH = _HERE / "docs" / "dev-guide" / "_meta.yaml"


def extract_wiki_tags(filename: str, whitelist: "set[str]") -> "list[str]":
    """파일명에서 화이트리스트 단어 소문자 단어경계 매칭.

    Args:
        filename: archive 파일명 (예: "2026-04-10_fix-watchdog-heartbeat.md")
        whitelist: 태그 화이트리스트 set (소문자). "untagged" 자동 처리.

    Returns:
        매칭된 태그 sorted list. 매칭 0건이면 ["untagged"].
    """
    haystack = filename.lower()
    matched: list[str] = []
    for tag in whitelist:
        if tag == "untagged":
            continue
        if re.search(rf"\b{re.escape(tag)}\b", haystack):
            matched.append(tag)
    if not matched:
        return ["untagged"]
    return sorted(set(matched))


def load_whitelist(schema_path: "Union[str, Path, None]" = None) -> "set[str]":
    """`docs/wiki-schema.md`의 `## 3. 태그 Vocabulary` 섹션 코드블럭에서 단어 추출.

    Args:
        schema_path: wiki-schema.md 경로. None이면 repo root 기준 기본값 사용.

    Returns:
        태그 단어 소문자 set.

    Raises:
        FileNotFoundError: 파일이 없을 때.
        ValueError: vocabulary 섹션이 없거나 비어있을 때.
    """
    p = Path(schema_path) if schema_path is not None else _DEFAULT_SCHEMA_PATH
    if not p.exists():
        raise FileNotFoundError(f"wiki-schema.md not found: {p}")
    text = p.read_text(encoding="utf-8")
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


def load_meta_yaml(path: "Union[str, Path, None]" = None) -> dict:
    """docs/dev-guide/_meta.yaml 로드.

    Args:
        path: _meta.yaml 경로. None이면 repo root 기준 기본값 사용.

    Returns:
        {guide_filename: {tags, owns_archive_tags, last_archive_scan, ...}} dict.
    """
    p = Path(path) if path is not None else _DEFAULT_META_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
