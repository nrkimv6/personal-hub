#!/usr/bin/env python3
"""Gemini oneshot 덤프트럭 컨텍스트 빌더 — CLI wrapper.

핵심 함수는 app/shared/context_bundle_builder.py 로 이관됨.
이 파일은 argparse + main() 진입점만 유지하는 얇은 wrapper.

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

# app/ 패키지 접근을 위해 PROJECT_ROOT를 sys.path에 추가
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.shared.context_bundle_builder import (  # noqa: E402
    collect_files as _collect_files,
    render_tree as _render_tree,
    concat_files as _concat_files,
    estimate_tokens,
)

# 토큰 임계치 (Gemini 2M 컨텍스트의 75%)
TOKEN_LIMIT = 1_500_000

TEMPLATE_CHOICES = ["architecture", "refactor", "conflict", "logdump"]


def collect_files(includes: list[str], excludes: list[str]) -> list[Path]:
    """PROJECT_ROOT 기준 collect_files wrapper (하위 호환)."""
    return _collect_files(includes, excludes, root=PROJECT_ROOT)


def render_tree(paths: list[Path]) -> str:
    """PROJECT_ROOT 기준 render_tree wrapper (하위 호환)."""
    return _render_tree(paths, root=PROJECT_ROOT)


def concat_files(paths: list[Path]) -> str:
    """PROJECT_ROOT 기준 concat_files wrapper (하위 호환)."""
    return _concat_files(paths, root=PROJECT_ROOT)


def load_template(name: str) -> str:
    """템플릿 파일을 읽어 헤더 프롬프트 문자열을 반환한다.

    Raises:
        FileNotFoundError: 해당 템플릿 파일이 없는 경우
    """
    template_path = TEMPLATES_DIR / f"{name}.md"
    if not template_path.exists():
        raise FileNotFoundError(f"템플릿 파일을 찾을 수 없습니다: {template_path}")
    return template_path.read_text(encoding="utf-8")


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
