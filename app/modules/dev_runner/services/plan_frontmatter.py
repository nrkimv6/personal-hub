"""plan 파일 frontmatter read/write 유틸

plan 파일 헤더는 blockquote 형식 (> key: value) 을 사용한다.
--- YAML block 형식도 파싱 fallback으로 지원.

기존 코드(_plan_header_utils.py, plan_service.py, plan_scanner.py)는 특정 필드 한정
regex를 사용하며 범용 read/write 기능이 없으므로 독립 모듈로 분리.
"""

import re
from pathlib import Path
from typing import Optional

AUTO_RUN_SCOPES: frozenset[str] = frozenset({"tc", "docs", "safe-fix"})

_BLOCKQUOTE_HEADER_RE = re.compile(
    r"^>\s*(\w[\w-]*):\s*(.*?)\s*$",
    re.MULTILINE,
)


def read_frontmatter(plan_path: Path) -> dict[str, Optional[str]]:
    """plan 파일의 frontmatter를 파싱해 {key: value} dict를 반환.

    지원 형식:
    1. blockquote: > key: value  (기본 — plan 파일 공식 형식)
    2. YAML block: --- ... --- (fallback)

    파싱 실패 시 빈 dict 반환 (원본 손상 없음).
    """
    try:
        content = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    result: dict[str, Optional[str]] = {}

    # 1. blockquote 형식 파싱 (헤더 영역 — 첫 --- 이전 또는 전체)
    header_section = content.split("\n---\n", 1)[0] if "\n---\n" in content else content[:2000]
    for m in _BLOCKQUOTE_HEADER_RE.finditer(header_section):
        key = m.group(1).strip()
        val = m.group(2).strip()
        result[key] = val if val else None

    # 2. YAML block fallback (---로 감싸인 경우)
    yaml_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if yaml_match:
        try:
            import yaml  # type: ignore[import]
            parsed = yaml.safe_load(yaml_match.group(1)) or {}
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if k not in result:
                        result[str(k)] = str(v) if v is not None else None
        except Exception:
            pass

    return result


def write_frontmatter_field(plan_path: Path, key: str, value: Optional[str]) -> None:
    """blockquote 헤더 형식을 유지하며 key를 추가/갱신한다.

    - key가 이미 존재하면 value로 갱신.
    - 없으면 헤더 blockquote 블록 끝(첫 --- 줄 직전 또는 빈 줄 직전)에 추가.
    - value가 None이면 빈 값으로 기록.
    """
    try:
        content = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    write_val = value if value is not None else ""
    new_line = f"> {key}: {write_val}"

    # 기존 key 갱신
    existing = re.compile(r"^(>\s*" + re.escape(key) + r":\s*).*$", re.MULTILINE)
    if existing.search(content):
        updated = existing.sub(new_line, content, count=1)
        plan_path.write_text(updated, encoding="utf-8")
        return

    # 신규 key — 헤더 블록 끝에 삽입
    # 헤더는 첫 "---" 줄 직전까지. 없으면 첫 빈 줄(연속 빈줄) 직전.
    sep_match = re.search(r"^---$", content, re.MULTILINE)
    if sep_match:
        insert_pos = sep_match.start()
        # 마지막 blockquote 라인 바로 뒤에 삽입
        header = content[:insert_pos]
        last_bq = re.search(r"^>.*$", header, re.MULTILINE | re.REVERSE if hasattr(re, "REVERSE") else 0)  # type: ignore[call-overload]
        if last_bq:
            # insert after last blockquote line
            after_bq = header.rfind("\n", 0, last_bq.end())
            if after_bq == -1:
                after_bq = last_bq.end()
            updated = content[:after_bq + 1] + new_line + "\n" + content[after_bq + 1:]
        else:
            updated = content[:insert_pos] + new_line + "\n" + content[insert_pos:]
    else:
        # --- 없으면 첫 비어있지 않은 blockquote 그룹 끝에 추가
        lines = content.split("\n")
        insert_idx = None
        for i, line in enumerate(lines):
            if line.startswith(">"):
                insert_idx = i
        if insert_idx is not None:
            lines.insert(insert_idx + 1, new_line)
        else:
            lines.insert(0, new_line)
        updated = "\n".join(lines)

    plan_path.write_text(updated, encoding="utf-8")


CLAIM_HEADER_KEY = "실행점유"


def read_claim_id(plan_path: Path) -> Optional[str]:
    """plan 헤더의 `> 실행점유: {claim_id}` 값을 반환. 없으면 None."""
    fm = read_frontmatter(plan_path)
    val = fm.get(CLAIM_HEADER_KEY)
    return val if val else None


def write_claim_id(plan_path: Path, claim_id: str) -> None:
    """`> 실행점유: {claim_id}`를 헤더에 기록/갱신한다."""
    write_frontmatter_field(plan_path, CLAIM_HEADER_KEY, claim_id)


def clear_claim_id(plan_path: Path) -> None:
    """`> 실행점유:`를 빈 값으로 초기화한다 (released/stale 이후)."""
    write_frontmatter_field(plan_path, CLAIM_HEADER_KEY, None)


def read_auto_run_meta(plan_path: Path) -> dict[str, Optional[str]]:
    """auto_run 관련 frontmatter 필드만 추출."""
    fm = read_frontmatter(plan_path)
    return {
        "auto_run": fm.get("auto_run"),
        "auto_run_scope": fm.get("auto_run_scope"),
        "auto_run_status": fm.get("auto_run_status"),
        "auto_run_at": fm.get("auto_run_at"),
        "auto_run_log_path": fm.get("auto_run_log_path"),
    }
