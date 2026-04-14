"""
CI 감지: frontend Svelte 파일 내 provider 하드코딩 옵션 감지

frontend/src/**/*.svelte 에서 아래 패턴이 발견되면 exit 1:
    <option value="(claude|gemini|codex|cc-codex)"

이 패턴은 provider select 옵션이 하드코딩된 것을 의미한다.
모든 provider 옵션은 GET /api/v1/llm/providers 동적 렌더링으로 교체해야 한다.

사용법:
    python scripts/ci/check_frontend_provider_hardcoding.py
    python scripts/ci/check_frontend_provider_hardcoding.py --frontend-dir frontend/src
    python scripts/ci/check_frontend_provider_hardcoding.py --whitelist-file .provider-hardcode-whitelist
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HARDCODED_PROVIDER_PATTERN = re.compile(
    r'<option\s[^>]*value=["\'](?:claude|gemini|codex|cc-codex)["\']',
    re.IGNORECASE,
)

_DEFAULT_WHITELIST: list[str] = []


def load_whitelist(whitelist_file: str | None) -> set[str]:
    """화이트리스트 파일에서 허용 경로 목록 로드."""
    if not whitelist_file:
        return set()
    path = Path(whitelist_file)
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def check_file(path: Path) -> list[tuple[int, str]]:
    """파일을 검사하여 (줄번호, 줄내용) 형태의 발견 목록 반환."""
    hits = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        print(f"[WARN] 파일 읽기 실패: {path} — {e}")
        return hits

    for lineno, line in enumerate(lines, start=1):
        if _HARDCODED_PROVIDER_PATTERN.search(line):
            hits.append((lineno, line.rstrip()))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="frontend provider 하드코딩 감지")
    parser.add_argument(
        "--frontend-dir",
        default=str(Path(__file__).parent.parent.parent / "frontend" / "src"),
        help="Svelte 소스 루트 디렉토리",
    )
    parser.add_argument(
        "--whitelist-file",
        default=None,
        help="허용 예외 파일 경로 (줄당 한 경로)",
    )
    args = parser.parse_args(argv)

    frontend_dir = Path(args.frontend_dir)
    if not frontend_dir.exists():
        print(f"[ERROR] 디렉토리 없음: {frontend_dir}")
        return 1

    whitelist = load_whitelist(args.whitelist_file)
    svelte_files = list(frontend_dir.rglob("*.svelte"))

    if not svelte_files:
        print(f"[INFO] Svelte 파일 없음: {frontend_dir}")
        return 0

    found_any = False
    for path in sorted(svelte_files):
        # 화이트리스트에 있는 파일 건너뜀
        if str(path) in whitelist or path.name in whitelist:
            continue

        hits = check_file(path)
        if hits:
            found_any = True
            print(f"[FAIL] {path}")
            for lineno, line in hits:
                print(f"  L{lineno}: {line}")

    if found_any:
        print(
            "\n❌ Svelte 파일에 provider 하드코딩 옵션이 남아있습니다.\n"
            "   GET /api/v1/llm/providers 동적 렌더링으로 교체하세요."
        )
        return 1

    print(f"✅ frontend provider 하드코딩 검사 통과 ({len(svelte_files)}개 파일)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
