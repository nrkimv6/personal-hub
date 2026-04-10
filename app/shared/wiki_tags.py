"""
wiki_tags.py — archive 파일명 기반 wiki 태그 추출 공용 함수
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Union
import yaml

_HERE = Path(__file__).resolve().parent.parent.parent  # repo root
_DEFAULT_SCHEMA_PATH = _HERE / "docs" / "wiki-schema.md"
_DEFAULT_META_PATH = _HERE / "docs" / "dev-guide" / "_meta.yaml"


def extract_wiki_tags(filename: str, whitelist: "set[str]") -> "list[str]":
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
    p = Path(path) if path is not None else _DEFAULT_META_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
