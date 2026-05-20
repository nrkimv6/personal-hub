#!/usr/bin/env python3
"""Dry-run and repair legacy exact-window task schedules."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import TaskSchedule
from app.services.schedule_contracts import (
    build_time_window_candidate_summary,
    coerce_schedule_value,
    has_exact_time_window,
)


DEFAULT_WINDOW_MINUTES = 60


def _parse_hhmm(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _format_hhmm(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def exact_windows_to_ranges(
    windows: list[dict[str, Any]],
    *,
    default_window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> list[dict[str, str]]:
    """Convert exact HH:MM slots into explicit ranges."""
    normalized = [
        {"start": window["start"], "end": window["end"]}
        for window in windows
        if isinstance(window, dict)
        and isinstance(window.get("start"), str)
        and isinstance(window.get("end"), str)
    ]
    exact_minutes = sorted(
        _parse_hhmm(window["start"])
        for window in normalized
        if window["start"] == window["end"]
    )
    exact_ranges: dict[str, list[dict[str, str]]] = {}
    for index, start in enumerate(exact_minutes):
        next_start = exact_minutes[index + 1] if index + 1 < len(exact_minutes) else None
        if next_start is not None and 0 < next_start - start <= default_window_minutes:
            end = next_start
        else:
            end = start + default_window_minutes
        key = _format_hhmm(start)
        exact_ranges.setdefault(key, []).append({"start": key, "end": _format_hhmm(end)})

    result: list[dict[str, str]] = []
    for window in sorted(normalized, key=lambda item: _parse_hhmm(item["start"])):
        if window["start"] == window["end"]:
            result.append(exact_ranges[window["start"]].pop(0))
        else:
            result.append(window)
    return result


def build_repaired_schedule_value(schedule_value: Any) -> dict[str, Any]:
    """Return schedule_value with legacy exact windows replaced by ranges."""
    value = coerce_schedule_value(schedule_value)
    windows = value.get("time_windows")
    if not isinstance(windows, list):
        return value
    repaired = dict(value)
    repaired["time_windows"] = exact_windows_to_ranges(windows)
    return repaired


def _parse_ids(raw: str | None) -> set[int] | None:
    if not raw:
        return None
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            result.add(int(part))
    return result


def _write_backup(items: list[dict[str, Any]], backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"exact_window_schedule_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    backup_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_path


def repair_exact_window_schedules(
    *,
    apply: bool = False,
    ids: set[int] | None = None,
    backup_dir: Path | None = None,
    session=None,
) -> dict[str, Any]:
    """Preview or apply exact-window schedule repair."""
    if apply and not ids:
        raise ValueError("--apply requires explicit --ids")

    owns_session = session is None
    db = session or SessionLocal()
    try:
        query = db.query(TaskSchedule).filter(TaskSchedule.enabled == True)
        if ids:
            query = query.filter(TaskSchedule.id.in_(ids))
        schedules = query.order_by(TaskSchedule.id.asc()).all()

        items: list[dict[str, Any]] = []
        for schedule in schedules:
            if not has_exact_time_window(schedule.schedule_value):
                continue
            before = coerce_schedule_value(schedule.schedule_value)
            after = build_repaired_schedule_value(before)
            health_after = build_time_window_candidate_summary(after, days=1)
            items.append(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "display_name": schedule.display_name,
                    "target_type": schedule.target_type,
                    "before": before,
                    "after": after,
                    "health_after": health_after,
                }
            )
            if apply:
                schedule.schedule_value = json.dumps(after, ensure_ascii=False)
                schedule.updated_at = datetime.now()

        backup_path = None
        if apply and items:
            backup_path = _write_backup(items, backup_dir or (PROJECT_ROOT / "logs"))
            db.commit()
        elif apply:
            db.commit()

        return {
            "dry_run": not apply,
            "candidate_count": len(items),
            "repaired_count": len(items) if apply else 0,
            "backup_path": str(backup_path) if backup_path else None,
            "items": items,
        }
    finally:
        if owns_session:
            db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply repair. Requires --ids.")
    parser.add_argument("--ids", help="Comma-separated schedule ids to repair.")
    parser.add_argument("--backup-dir", type=Path, default=PROJECT_ROOT / "logs")
    args = parser.parse_args(argv)

    try:
        result = repair_exact_window_schedules(
            apply=args.apply,
            ids=_parse_ids(args.ids),
            backup_dir=args.backup_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
