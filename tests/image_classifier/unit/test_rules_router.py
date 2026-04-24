from unittest.mock import MagicMock

import pytest

from app.modules.image_classifier.routers.rules import get_rules


pytestmark = pytest.mark.asyncio


def _mapping_all_result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


async def test_get_rules_right_named_fields():
    db = MagicMock()
    db.execute.return_value = _mapping_all_result([
        {
            "id": 1,
            "rule_type": "keyword",
            "category_id": 3,
            "rule_content": "receipt",
            "priority": 100,
            "is_active": 1,
            "source": "user",
            "hit_count": 7,
            "category_name": "shopping/receipt",
        }
    ])

    result = await get_rules(db=db)

    assert len(result) == 1
    rule = result[0]
    assert rule.id == 1
    assert rule.rule_type == "keyword"
    assert rule.category_id == 3
    assert rule.rule_content == "receipt"
    assert rule.priority == 100
    assert rule.is_active is True
    assert rule.source == "user"
    assert rule.hit_count == 7
    assert rule.category_name == "shopping/receipt"


async def test_get_rules_boundary_empty_rows():
    db = MagicMock()
    db.execute.return_value = _mapping_all_result([])

    result = await get_rules(db=db)

    assert result == []


async def test_get_rules_error_db_exception_propagates():
    db = MagicMock()
    db.execute.side_effect = RuntimeError("db boom")

    with pytest.raises(RuntimeError, match="db boom"):
        await get_rules(db=db)


async def test_get_rules_reference_shuffled_keys():
    db = MagicMock()
    db.execute.return_value = _mapping_all_result([
        {
            "category_name": "travel",
            "hit_count": 3,
            "source": "learned",
            "is_active": 0,
            "priority": 90,
            "rule_content": "travel",
            "category_id": 2,
            "rule_type": "folder_path",
            "id": 8,
        }
    ])

    result = await get_rules(db=db)

    assert len(result) == 1
    rule = result[0]
    assert rule.id == 8
    assert rule.source == "learned"
    assert rule.hit_count == 3
    assert rule.category_name == "travel"
    assert rule.is_active is False

