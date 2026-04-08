#!/usr/bin/env python3
"""Gemini oneshot 덤프트럭 컨텍스트 빌더.

대상 디렉토리의 파일 트리 + 파일 내용 전문을 하나의 거대 프롬프트 파일로 조립합니다.

사용 예:
    python scripts/dumptruck_builder.py \\
        --template architecture \\
        --include "app/shared/**" "app/modules/llm/**" \\
        --exclude "*.pyc" \\
        --out /tmp/dump_out.txt

    python scripts/dumptruck_builder.py \\
        --template logdump \\
        --include "logs/**" \\
        --out /tmp/logdump.txt --force
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트: 이 스크립트는 scripts/ 에 위치
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TEMPLATES_DIR = SCRIPT_DIR / "dumptruck_templates"

# 기본 제외 디렉토리 (최상위 컴포넌트 이름)
DEFAULT_EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "data"}

# 바이너리 파일 판정 시 읽는 바이트 수
BINARY_PROBE_BYTES = 8192

# 토큰 임계치 (Gemini 2M 컨텍스트의 75%)
TOKEN_LIMIT = 1_500_000

# 확장자 → 언어 매핑 (코드 블록 언어 표기용)
LANG_MAP = {
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

TEMPLATE_CHOICES = ["architecture", "refactor", "conflict", "logdump"]


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


def collect_files(includes: list[str], excludes: list[str]) -> list[Path]:
    """include glob 패턴에 매칭되는 파일 목록을 반환한다.

    - 기본 제외 디렉토리 (DEFAULT_EXCLUDE_DIRS)에 속하는 파일은 항상 제외
    - excludes 추가 패턴도 제외
    - 결과는 상대경로 기준으로 정렬됨
    """
    collected: set[Path] = set()

    for pattern in includes:
        for p in PROJECT_ROOT.rglob(pattern.lstrip("/")):
            if not p.is_file():
                continue
            # 기본 제외 디렉토리 체크
            if any(part in DEFAULT_EXCLUDE_DIRS for part in p.parts):
                continue
            collected.add(p.resolve())

    # exclude 패턴 제거
    excluded: set[Path] = set()
    for pattern in (excludes or []):
        for p in PROJECT_ROOT.rglob(pattern.lstrip("/")):
            excluded.add(p.resolve())

    result = sorted(collected - excluded)
    return result


def render_tree(paths: list[Path]) -> str:
    """파일 목록을 ASCII 디렉토리 트리 문자열로 반환한다."""
    if not paths:
        return "(파일 없음)"

    # PROJECT_ROOT 기준 상대 경로로 변환
    rel_paths = [p.relative_to(PROJECT_ROOT) for p in paths]

    # 트리 노드 구성: dict of dict
    tree: dict = {}
    for rp in rel_paths:
        node = tree
        for part in rp.parts[:-1]:
            node = node.setdefault(part, {})
        # 파일 노드는 None으로 표기
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


def concat_files(paths: list[Path]) -> str:
    """파일 목록을 코드 블록으로 직렬화한다.

    각 파일: ```{lang}\n# {상대경로}\n{내용}\n```
    바이너리 파일은 스킵한다.
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
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = p
        parts.append(f"```{lang}\n# {rel}\n{content}\n```")
    return "\n\n".join(parts)


def load_template(name: str) -> str:
    """템플릿 파일을 읽어 헤더 프롬프트 문자열을 반환한다.

    Raises:
        FileNotFoundError: 해당 템플릿 파일이 없는 경우
    """
    template_path = TEMPLATES_DIR / f"{name}.md"
    if not template_path.exists():
        raise FileNotFoundError(f"템플릿 파일을 찾을 수 없습니다: {template_path}")
    return template_path.read_text(encoding="utf-8")


def estimate_tokens(text: str) -> int:
    """텍스트의 토큰 수를 휴리스틱으로 추정한다 (len // 4)."""
    return len(text) // 4


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gemini oneshot 덤프트럭 컨텍스트 빌더",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--template",
        choices=TEMPLATE_CHOICES,
        required=True,
        help="사용할 프롬프트 템플릿",
    )
    parser.add_argument(
        "--include",
        nargs="+",
        metavar="GLOB",
        default=[],
        help="포함할 파일 glob 패턴 (여러 개 가능)",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        metavar="GLOB",
        default=[],
        help="제외할 파일 glob 패턴 (여러 개 가능)",
    )
    parser.add_argument(
        "--out",
        required=True,
        metavar="PATH",
        help="출력 파일 경로",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="토큰 임계치 초과 시에도 강제 출력",
    )

    args = parser.parse_args()

    # 1. 파일 수집
    paths = collect_files(args.include, args.exclude)

    # 2. 트리 렌더링
    tree_str = render_tree(paths)

    # 3. 파일 내용 연결
    files_str = concat_files(paths)

    # 4. 템플릿 로드
    template_str = load_template(args.template)

    # 5. 최종 프롬프트 조립
    output = "\n\n".join([
        template_str.strip(),
        "## 프로젝트 파일 트리\n\n" + tree_str,
        "## 파일 내용\n\n" + files_str,
    ])

    # 6. 토큰 예산 체크
    total_bytes = len(output.encode("utf-8"))
    est_tokens = estimate_tokens(output)

    if est_tokens > TOKEN_LIMIT:
        print(
            f"[WARN] 추정 토큰 {est_tokens:,} > 임계치 {TOKEN_LIMIT:,} (Gemini 2M 75%)",
            file=sys.stderr,
        )
        if not args.force:
            print(
                "[ERROR] --force 없이는 임계치 초과 시 출력을 중단합니다. "
                "--force 플래그를 추가하거나 include 범위를 줄이세요.",
                file=sys.stderr,
            )
            sys.exit(2)

    # 7. 출력 파일 기록
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")

    print(f"[INFO] total_bytes={total_bytes:,} est_tokens={est_tokens:,}", file=sys.stderr)
    print(str(out_path))


if __name__ == "__main__":
    main()
