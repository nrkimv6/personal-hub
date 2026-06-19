"""
BigQuery insert client.

Uses lazy import so that missing google-cloud-bigquery package does not
break app startup when ENABLE_BIGQUERY_EXPORT is false (default).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List

from app.modules.bigquery_export.validator import validate_export_row

logger = logging.getLogger(__name__)

# Maximum rows per single streaming-insert call (BigQuery limit)
MAX_ROWS_PER_INSERT = 1000


class CostGuardBlocked(Exception):
    """Raised when ENABLE_BIGQUERY_EXPORT is not 'true' and a live insert is attempted."""


@dataclass
class InsertResult:
    rows_attempted: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    errors: List[str] = field(default_factory=list)
    dry_run: bool = True


def _is_export_enabled() -> bool:
    return os.environ.get("ENABLE_BIGQUERY_EXPORT", "false").lower() == "true"


def insert_rows(
    rows: list[dict],
    table_id: str,
    dry_run: bool = True,
) -> InsertResult:
    """Insert rows into a BigQuery table.

    Args:
        rows:     List of dicts; each must pass validate_export_row().
        table_id: Fully-qualified BigQuery table ID
                  (e.g. "project.dataset.personal_hub_events").
        dry_run:  When True, validate rows but skip actual SDK call.

    Returns:
        InsertResult summarising what happened.

    Raises:
        CostGuardBlocked: When ENABLE_BIGQUERY_EXPORT != "true" and dry_run=False.
        ValueError:       When len(rows) > MAX_ROWS_PER_INSERT.
    """
    if len(rows) > MAX_ROWS_PER_INSERT:
        raise ValueError(
            f"BigQuery insert: 단일 호출 {MAX_ROWS_PER_INSERT}건 제한 초과 — {len(rows)}건"
        )

    if not dry_run and not _is_export_enabled():
        raise CostGuardBlocked(
            "ENABLE_BIGQUERY_EXPORT=false — live insert 차단. "
            "실제 적재를 원하면 환경변수를 'true'로 설정하세요."
        )

    result = InsertResult(rows_attempted=len(rows), dry_run=dry_run)

    # Validate each row; skip invalids
    valid_rows: list[dict] = []
    for i, row in enumerate(rows):
        try:
            valid_rows.append(validate_export_row(row))
        except ValueError as exc:
            msg = f"row[{i}] 검증 실패 — {exc}"
            logger.warning(msg)
            result.rows_skipped += 1
            result.errors.append(msg)

    if dry_run:
        logger.info(
            "BigQuery dry-run: %d/%d rows valid, table=%s",
            len(valid_rows),
            len(rows),
            table_id,
        )
        result.rows_inserted = len(valid_rows)
        return result

    # Live insert path — lazy import
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "google-cloud-bigquery가 설치되지 않았습니다. "
            "`pip install google-cloud-bigquery`를 실행하세요."
        ) from exc

    client = bigquery.Client()
    api_errors = client.insert_rows_json(table_id, valid_rows)
    if api_errors:
        for err in api_errors:
            msg = f"BigQuery API 오류: {err}"
            logger.error(msg)
            result.errors.append(msg)
            result.rows_skipped += 1
        result.rows_inserted = len(valid_rows) - len(api_errors)
    else:
        result.rows_inserted = len(valid_rows)

    return result
