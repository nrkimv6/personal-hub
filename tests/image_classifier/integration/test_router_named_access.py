from datetime import datetime

import pytest
from sqlalchemy import text

from app.modules.image_classifier.routers.clusters import (
    get_cluster_detail,
    get_clusters,
)
from app.modules.image_classifier.routers.rules import get_rules


@pytest.fixture
def seeded_named_access_data(test_db):
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, 'Travel', 'photos/travel'),
        (2, 'Family', 'photos/family')
    """))
    test_db.execute(text("""
        INSERT INTO time_clusters (id, date, start_time, end_time, file_count, category_id, reviewed) VALUES
        (1, '2023-04-15', '2023-04-15 10:00:00', '2023-04-15 10:45:00', 2, 1, 1)
    """))
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, cluster_id, extracted_date, status) VALUES
        (1, 'D:/Photos/travel/a.jpg', 'hash-a', 1, '2023-04-15 10:05:00', 'pending'),
        (2, 'D:/Photos/travel/b.jpg', 'hash-b', 1, '2023-04-15 10:15:00', 'pending')
    """))
    test_db.execute(text("""
        INSERT INTO classification_rules (id, rule_type, category_id, rule_content, priority, is_active, source, hit_count) VALUES
        (1, 'keyword', 1, 'beach', 100, 1, 'user', 7),
        (2, 'folder_path', 2, 'family', 90, 0, 'learned', 3)
    """))
    test_db.commit()
    return test_db


@pytest.mark.asyncio
async def test_get_clusters_reads_named_mapping_fields(seeded_named_access_data):
    result = await get_clusters(db=seeded_named_access_data)

    assert len(result) == 1
    cluster = result[0]
    assert cluster["cluster_id"] == 1
    assert cluster["category_path"] == "photos/travel"
    assert cluster["reviewed"] is True
    assert cluster["preview_file_ids"] == [1, 2]


@pytest.mark.asyncio
async def test_get_cluster_detail_reads_named_mapping_fields(seeded_named_access_data):
    result = await get_cluster_detail(cluster_id=1, db=seeded_named_access_data)

    assert result.cluster_id == 1
    assert result.category_path == "photos/travel"
    assert result.duration_minutes in (44, 45)
    assert [item.file_id for item in result.files] == [1, 2]
    assert result.files[0].thumbnail_url == "/api/ic/files/1/thumbnail"
    assert result.files[0].capture_time == datetime(2023, 4, 15, 10, 5, 0)


@pytest.mark.asyncio
async def test_get_rules_reads_named_mapping_fields(seeded_named_access_data):
    result = await get_rules(db=seeded_named_access_data)

    assert [rule.id for rule in result] == [1, 2]
    assert result[0].source == "user"
    assert result[0].hit_count == 7
    assert result[0].category_name == "photos/travel"
    assert result[1].source == "learned"
    assert result[1].hit_count == 3
    assert result[1].category_name == "photos/family"
