"""dev_runner 테스트 공통 conftest - config 격리로 hang 방지"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """모든 dev_runner 테스트에서 config를 tmp 경로로 격리.

    모듈-레벨 싱글톤(plan_service, db_service 등)이 import 시
    실제 파일시스템에 접근하는 것을 방지합니다.
    """
    reg_file = tmp_path / "registered_paths.json"
    ign_file = tmp_path / "ignored_plans.json"
    reg_file.write_text("[]", encoding="utf-8")
    ign_file.write_text("[]", encoding="utf-8")

    mock_config = MagicMock()
    mock_config.REGISTERED_PATHS_FILE = reg_file
    mock_config.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
    mock_config.IGNORED_PLANS_FILE = ign_file
    mock_config.WTOOLS_BASE_DIR = tmp_path / "wtools"
    mock_config.PLAN_DIR = Path("common/docs/plan")
    mock_config.PROJECT_DIRS = []
    mock_config.ALLOWED_PATHS = [str(tmp_path)]
    mock_config.LOG_DIR = Path("common/logs")
    mock_config.LOG_FILE_PATTERN = "plan-runner-*.log"

    with patch("app.modules.dev_runner.services.plan_service.config", mock_config):
        yield mock_config


@pytest.fixture
def isolated_redis():
    """격리된 Redis 목업 클라이언트.

    plan-runner:* 패턴 키를 in-memory dict로 관리합니다.
    isolated_redis를 사용하는 테스트에 한해 runner cleanup이 자동 적용됩니다.
    """
    storage: dict = {}

    mock = MagicMock()

    def _set(key, value, *args, **kwargs):
        storage[key] = value

    def _get(key):
        return storage.get(key)

    def _delete(*keys):
        for key in keys:
            storage.pop(key, None)

    def _mget(keys):
        return [storage.get(k) for k in keys]

    def _smembers(key):
        val = storage.get(key, set())
        return val if isinstance(val, set) else set()

    def _sadd(key, *values):
        if key not in storage:
            storage[key] = set()
        if isinstance(storage[key], set):
            storage[key].update(values)

    def _srem(key, *values):
        if isinstance(storage.get(key), set):
            storage[key].discard(*values)

    def _keys(pattern):
        import fnmatch
        return [k for k in storage if fnmatch.fnmatch(k, pattern)]

    mock.set.side_effect = _set
    mock.get.side_effect = _get
    mock.delete.side_effect = _delete
    mock.mget.side_effect = _mget
    mock.smembers.side_effect = _smembers
    mock.sadd.side_effect = _sadd
    mock.srem.side_effect = _srem
    mock.keys.side_effect = _keys

    yield mock

    # teardown: plan-runner:* 패턴 키 자동 정리
    stale_keys = [k for k in list(storage.keys()) if k.startswith("plan-runner:")]
    for key in stale_keys:
        storage.pop(key, None)
