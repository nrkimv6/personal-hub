"""
컨텍스트 번들 빌더 — 공통 파일 수집/직렬화 모듈.

dumptruck_builder.py 의 핵심 함수를 PROJECT_ROOT 하드코딩 없이 추출.
A(덤프트럭 스킬)와 B-2(aggregator) 양쪽에서 import 사용.

사용 예:
    from app.shared.context_bundle_builder import collect_files, concat_files, render_tree

    paths = collect_files(["app/shared/**"], excludes=[], root=Path("."))
    tree_str = render_tree(paths, root=Path("."))
    content = concat_files(paths, root=Path("."))
    tokens = estimate_tokens(content)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


# 기본 제외 디렉토리 (최상위 컴포넌트 이름)
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "data"}
)

# 확장자 → 언어 매핑
LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".svelte": "svelte",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".sql": "sql",
    ".sh": "bash",
    ".ps1": "powershell",
    ".html": "html",
    ".css": "css",
    ".txt": "text",
}

BINARY_PROBE_BYTES = 8192


def _is_binary(path: Path) -> bool:
    """파일이 바이너리인지 빠르게 판정한다."""
    try:
        with path.open("rb") as f:
            chunk = f.read(BINARY_PROBE_BYTES)
        return b"\x00" in chunk
    except OSError:
        return True


def _lang_of(path: Path) -> str:
    return LANG_MAP.get(path.suffix.lower(), "text")


def collect_files(
    includes: list[str],
    excludes: list[str],
    root: Path,
) -> list[Path]:
    """include glob 패턴에 매칭되는 파일 목록 반환 (절대경로, 정렬됨).

    Args:
        includes: 포함 glob 패턴 리스트 (예: ["app/shared/**"]).
        excludes: 제외 glob 패턴 리스트.
        root: 검색 기준 루트 디렉토리.

    Raises:
        FileNotFoundError: root 가 존재하지 않는 경우.
    """
    if not root.exists():
        raise FileNotFoundError(f"root 디렉토리가 존재하지 않습니다: {root}")

    collected: set[Path] = set()
    for pattern in includes:
        for p in root.rglob(pattern.lstrip("/")):
            if not p.is_file():
                continue
            if any(part in DEFAULT_EXCLUDE_DIRS for part in p.parts):
                continue
            collected.add(p.resolve())

    excluded: set[Path] = set()
    for pattern in (excludes or []):
        for p in root.rglob(pattern.lstrip("/")):
            excluded.add(p.resolve())

    return sorted(collected - excluded)


def render_tree(paths: list[Path], root: Path) -> str:
    """파일 목록을 ASCII 디렉토리 트리 문자열로 반환.

    Args:
        paths: 파일 절대경로 리스트.
        root: 상대경로 계산 기준.
    """
    if not paths:
        return "(파일 없음)"

    rel_paths = []
    for p in paths:
        try:
            rel_paths.append(p.relative_to(root))
        except ValueError:
            rel_paths.append(p)

    tree: dict = {}
    for rp in rel_paths:
        node = tree
        for part in rp.parts[:-1]:
            node = node.setdefault(part, {})
        node[rp.name] = None

    lines: list[str] = []

    def _walk(node: dict, prefix: str = "") -> None:
        items = list(node.items())
        for idx, (name, child) in enumerate(items):
            is_last = idx == len(items) - 1
            connector = "└──" if is_last else "├──"
            lines.append(f"{prefix}{connector} {name}")
            if child is not None:
                extension = "    " if is_last else "│   "
                _walk(child, prefix + extension)

    _walk(tree)
    return "\n".join(lines)


def concat_files(paths: list[Path], root: Path) -> str:
    """파일 목록을 코드 블록으로 직렬화.

    각 파일: ```{lang}\\n# {상대경로}\\n{내용}\\n```
    바이너리 파일은 스킵.

    Args:
        paths: 파일 절대경로 리스트.
        root: 상대경로 계산 기준.
    """
    parts: list[str] = []
    for p in paths:
        if _is_binary(p):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lang = _lang_of(p)
        try:
            rel = p.relative_to(root)
        except ValueError:
            rel = p
        parts.append(f"```{lang}\n# {rel}\n{content}\n```")
    return "\n\n".join(parts)


def estimate_tokens(text: str) -> int:
    """텍스트의 토큰 수를 휴리스틱으로 추정 (len // 4).

    session_switching.estimate_tokens(byte_count)과 동일 공식.
    바이트 수 기반 추정과 구별: 이 함수는 str 길이 기반.
    """
    return len(text) // 4
