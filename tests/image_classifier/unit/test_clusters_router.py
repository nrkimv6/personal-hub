from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.image_classifier.routers.clusters import (
    get_cluster_detail,
    get_clusters,
)


pytestmark = pytest.mark.asyncio


def _mapping_all_result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _mapping_first_result(row):
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    return result


def _fetchall_result(rows):
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


async def test_get_clusters_right_named_fields():
    db = MagicMock()
    db.execute.side_effect = [
        _mapping_all_result([
            {
                "id": 3,
                "start_time": datetime(2026, 4, 24, 14, 0, 0),
                "end_time": datetime(2026, 4, 24, 14, 30, 0),
                "file_count": 2,
                "duration_minutes": 30,
                "full_path": "photos/travel",
                "reviewed": 1,
            },
            {
                "id": 1,
                "start_time": datetime(2026, 4, 24, 10, 0, 0),
                "end_time": datetime(2026, 4, 24, 10, 5, 0),
                "file_count": 1,
                "duration_minutes": 5,
                "full_path": None,
                "reviewed": 0,
            },
        ]),
        _fetchall_result([(101,), (102,)]),
        _fetchall_result([(201,)]),
    ]

    result = await get_clusters(limit=10, db=db)

    assert result[0]["cluster_id"] == 3
    assert result[0]["category_path"] == "photos/travel"
    assert result[0]["reviewed"] is True
    assert result[0]["preview_file_ids"] == [101, 102]
    assert result[1]["cluster_id"] == 1
    assert result[1]["reviewed"] is False
    assert result[1]["preview_file_ids"] == [201]


async def test_get_clusters_boundary_empty_rows():
    db = MagicMock()
    db.execute.return_value = _mapping_all_result([])

    result = await get_clusters(db=db)

    assert result == []


async def test_get_clusters_error_db_exception_propagates():
    db = MagicMock()
    db.execute.side_effect = RuntimeError("db boom")

    with pytest.raises(RuntimeError, match="db boom"):
        await get_clusters(db=db)


async def test_get_clusters_reference_shuffled_keys():
    db = MagicMock()
    db.execute.side_effect = [
        _mapping_all_result([
            {
                "reviewed": 0,
                "full_path": "photos/mixed",
                "duration_minutes": 12,
                "file_count": 4,
                "end_time": datetime(2026, 4, 24, 12, 12, 0),
                "start_time": datetime(2026, 4, 24, 12, 0, 0),
                "id": 9,
            }
        ]),
        _fetchall_result([(301,), (302,), (303,)]),
    ]

    result = await get_clusters(db=db)

    assert result[0]["cluster_id"] == 9
    assert result[0]["preview_file_ids"] == [301, 302, 303]
    assert result[0]["reviewed"] is False
    assert result[0]["category_path"] == "photos/mixed"


async def test_get_cluster_detail_right_named_fields():
    db = MagicMock()
    db.execute.side_effect = [
        _mapping_first_result({
            "id": 7,
            "start_time": datetime(2026, 4, 24, 8, 0, 0),
            "end_time": datetime(2026, 4, 24, 9, 0, 0),
            "file_count": 2,
            "duration_minutes": 60,
            "full_path": "photos/family",
        }),
        _mapping_all_result([
            {
                "id": 11,
                "file_path": "D:/Photos/family/a.jpg",
                "capture_time": datetime(2026, 4, 24, 8, 5, 0),
            },
            {
                "id": 12,
                "file_path": "D:/Photos/family/b.jpg",
                "capture_time": datetime(2026, 4, 24, 8, 30, 0),
            },
        ]),
    ]

    result = await get_cluster_detail(cluster_id=7, db=db)

    assert result.cluster_id == 7
    assert result.category_path == "photos/family"
    assert result.duration_minutes == 60
    assert len(result.files) == 2
    assert result.files[0].file_id == 11
    assert result.files[0].thumbnail_url == "/api/ic/files/11/thumbnail"
    assert result.files[1].capture_time == datetime(2026, 4, 24, 8, 30, 0)


async def test_get_cluster_detail_boundary_missing_cluster_404():
    db = MagicMock()
    db.execute.return_value = _mapping_first_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_cluster_detail(cluster_id=404, db=db)

    assert exc_info.value.status_code == 404


async def test_get_cluster_detail_error_db_exception_propagates():
    db = MagicMock()
    db.execute.side_effect = [
        _mapping_first_result({
            "id": 7,
            "start_time": datetime(2026, 4, 24, 8, 0, 0),
            "end_time": datetime(2026, 4, 24, 9, 0, 0),
            "file_count": 1,
            "duration_minutes": 60,
            "full_path": "photos/family",
        }),
        RuntimeError("db boom"),
    ]

    with pytest.raises(RuntimeError, match="db boom"):
        await get_cluster_detail(cluster_id=7, db=db)


async def test_get_cluster_detail_reference_shuffled_keys():
    db = MagicMock()
    db.execute.side_effect = [
        _mapping_first_result({
            "full_path": "photos/events",
            "duration_minutes": 45,
            "file_count": 1,
            "end_time": datetime(2026, 4, 24, 15, 45, 0),
            "start_time": datetime(2026, 4, 24, 15, 0, 0),
            "id": 20,
        }),
        _mapping_all_result([
            {
                "capture_time": datetime(2026, 4, 24, 15, 10, 0),
                "file_path": "D:/Photos/events/c.jpg",
                "id": 88,
            }
        ]),
    ]

    result = await get_cluster_detail(cluster_id=20, db=db)

    assert result.cluster_id == 20
    assert result.category_path == "photos/events"
    assert result.files[0].thumbnail_url == "/api/ic/files/88/thumbnail"
    assert result.files[0].capture_time == datetime(2026, 4, 24, 15, 10, 0)

