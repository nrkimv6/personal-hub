import sys
import importlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

def test_constants_importable_R():
    from _dr_constants import RUNNER_KEY_PREFIX, PLAN_RUNNER_PYTHON, MERGE_ACTIVE_STATUSES
    assert RUNNER_KEY_PREFIX
    assert PLAN_RUNNER_PYTHON
    assert MERGE_ACTIVE_STATUSES

def test_merge_active_statuses_contains_fixing_R():
    from _dr_constants import MERGE_ACTIVE_STATUSES
    assert "fixing" in MERGE_ACTIVE_STATUSES

def test_get_set_redis_db_R():
    import _dr_constants as m
    m.set_redis_db(15)
    assert m.get_redis_db() == 15
    m.set_redis_db(0)  # 원복

def test_redis_db_default_zero_R():
    import _dr_constants as m
    m.set_redis_db(0)
    assert m.get_redis_db() == 0
