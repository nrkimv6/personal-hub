"""
CI 감지: watchdog 스크립트 내 placeholder 패턴 검출

scripts/*watchdog*.ps1 파일에서 다음 패턴이 발견되면 exit 1:
- ^placeholder$  (한 줄 전체가 "placeholder")
- TODO:          (미완성 TODO 주석)
- # placeholder  (placeholder 주석)

사용법:
    python scripts/ci/check_watchdog_placeholders.py
    python scripts/ci/check_watchdog_placeholders.py --scripts-dir scripts/
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PLACEHOLDER_PATTERNS = [
    re.compile(r"^\s*placeholder\s*$", re.IGNORECASE),
    re.compile(r"TODO:", re.IGNORECASE),
    re.compile(r"#\s*placeholder", re.IGNORECASE),
]


def check_file(path: Path) -> list[tuple[int, str]]:
    """파일을 검사하여 (줄번호, 줄내용) 형태의 발견 목록 반환."""
    hits = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        print(f"[WARN] 파일 읽기 실패: {path} — {e}")
        return hits

    for lineno, line in enumerate(lines, start=1):
        for pattern in _PLACEHOLDER_PATTERNS:
            if pattern.search(line):
                hits.append((lineno, line.rstrip()))
                break
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="watchdog 스크립트 placeholder 감지")
    parser.add_argument(
        "--scripts-dir",
        default=str(Path(__file__).parent.parent),
        help="스크립트 루트 디렉토리 (기본: scripts/)",
    )
    args = parser.parse_args(argv)

    scripts_dir = Path(args.scripts_dir)
    watchdog_files = list(scripts_dir.glob("*watchdog*.ps1"))

    if not watchdog_files:
        print(f"[INFO] watchdog 스크립트 없음: {scripts_dir}")
        return 0

    found_any = False
    for path in sorted(watchdog_files):
        hits = check_file(path)
        if hits:
            found_any = True
            print(f"[FAIL] {path}")
            for lineno, line in hits:
                print(f"  L{lineno}: {line}")

    if found_any:
        print("\n❌ watchdog 스크립트에 placeholder 패턴이 남아있습니다. 구현을 완료하세요.")
        return 1

    print(f"✅ watchdog placeholder 검사 통과 ({len(watchdog_files)}개 파일)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
