"""dev-runner plan path/stage 공통 규칙.

목표:
- docs/plan → docs/archive 규칙 단일화
- common/docs/plan → common/docs/archive 규칙 단일화
- _auto* 계열 plan은 docs/history로 이동
- 검토완료 이전(pre_review) / 이후(post_review) 단계 분류 공통화
"""

from __future__ import annotations

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

TargetKind = Literal["plan", "archive", "history", "unknown"]
PlanStage = Literal["pre_review", "post_review", "unknown"]


class PathRuleError(ValueError):
    """plan 경로 규칙 해석 실패."""


@dataclass(frozen=True)
class PathResolution:
    source: Path
    target: Path
    target_kind: TargetKind
    rule_id: str


_PRE_REVIEW_STATUSES = {
    "초안",
    "검토대기",
    "검증중",
}

_POST_REVIEW_STATUSES = {
    "검토완료",
    "구현중",
    "테스트중",
    "머지대기",
    "통합테스트중",
    "구현완료",
    "완료",
    "수정필요",
    "보류",
    "배포완료",
    "수정완료",
    "수정 완료",
}


def _is_auto_plan_name(filename: str) -> bool:
    stem = Path(filename).stem.lower()
    return stem.startswith("_auto") or "_auto" in stem


def _normalize(path_str: str | Path) -> Path:
    return Path(path_str).resolve()


def _parts_lower(path: Path) -> tuple[str, ...]:
    return tuple(part.lower() for part in path.parts)


def _find_docs_segment(path: Path) -> int:
    parts = _parts_lower(path)
    for idx, part in enumerate(parts):
        if part == "docs":
            return idx
    return -1


def _status_from_head(content: str) -> str:
    for line in content.splitlines()[:40]:
        m = re.match(r">\s*상태:\s*(.+)", line.strip())
        if m:
            return _strip_md_inline(m.group(1))
        m2 = re.match(r"-\s*\*{0,2}상태\*{0,2}:\s*(.+)", line.strip())
        if m2:
            return _strip_md_inline(m2.group(1))
    return ""


def _strip_md_inline(text: str) -> str:
    return re.sub(r"[*_~`]+", "", text).strip()


def resolve_plan_target(plan_file: str | Path, purpose: str = "archive") -> PathResolution:
    """plan 파일의 규칙 기반 target 경로를 계산한다.

    규칙:
    - common/docs/plan/*.md -> common/docs/archive/*.md
    - */docs/plan/*.md -> */docs/archive/*.md
    - *_auto*.md -> */docs/history/*.md
    - 이미 docs/archive 또는 docs/history 경로면 그대로 반환
    """
    source = _normalize(plan_file)
    parts = _parts_lower(source)

    if "docs" not in parts:
        raise PathRuleError(f"docs 경로가 아닌 파일입니다: {source}")

    # 이미 archive/history 경로면 그대로 반환
    if "archive" in parts:
        return PathResolution(source=source, target=source, target_kind="archive", rule_id="already_archive")
    if "history" in parts:
        return PathResolution(source=source, target=source, target_kind="history", rule_id="already_history")

    docs_idx = _find_docs_segment(source)
    if docs_idx < 0 or docs_idx + 1 >= len(parts) or parts[docs_idx + 1] != "plan":
        raise PathRuleError(f"docs/plan 경로가 아닌 파일입니다: {source}")

    docs_dir = Path(*source.parts[: docs_idx + 1])  # .../docs
    parent_before_docs = source.parts[docs_idx - 1] if docs_idx > 0 else ""
    is_common = parent_before_docs.lower() == "common"
    is_auto = _is_auto_plan_name(source.name)

    if is_auto:
        target_dir = docs_dir / "history"
        rule_id = "auto_history"
        target_kind: TargetKind = "history"
    else:
        target_dir = docs_dir / "archive"
        rule_id = "common_plan_archive" if is_common else "project_plan_archive"
        target_kind = "archive"

    target = target_dir / source.name
    try:
        # docs/ 하위 이탈 방지
        target.relative_to(docs_dir)
    except Exception as exc:
        raise PathRuleError(f"docs 루트 이탈 경로가 계산되었습니다: source={source}, target={target}") from exc

    return PathResolution(source=source, target=target, target_kind=target_kind, rule_id=rule_id)


def is_archive_or_history_path(plan_file: str | Path) -> bool:
    try:
        resolution = resolve_plan_target(plan_file, purpose="check")
        return resolution.source == resolution.target and resolution.target_kind in {"archive", "history"}
    except PathRuleError:
        normalized = str(plan_file).replace("\\", "/")
        return "/docs/archive/" in normalized or "/docs/history/" in normalized


def read_plan_status(plan_file: str | Path) -> str:
    path = _normalize(plan_file)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = "".join([f.readline() for _ in range(40)])
        return _status_from_head(head)
    except Exception:
        return ""


def classify_plan_stage(status: str) -> PlanStage:
    normalized = (status or "").strip()
    if not normalized:
        return "unknown"
    if normalized in _PRE_REVIEW_STATUSES:
        return "pre_review"
    if normalized in _POST_REVIEW_STATUSES:
        return "post_review"
    return "unknown"

