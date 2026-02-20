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
    mock_config.DEV_RUNNER_DB_PATH = tmp_path / "tasks.db"
    mock_config.WTOOLS_BASE_DIR = tmp_path / "wtools"
    mock_config.PLAN_DIR = Path("common/docs/plan")
    mock_config.PROJECT_DIRS = []
    mock_config.ALLOWED_PATHS = [str(tmp_path)]
    mock_config.LOG_DIR = Path("common/logs")
    mock_config.LOG_FILE_PATTERN = "plan-runner-*.log"

    with patch("app.modules.dev_runner.services.plan_service.config", mock_config), \
         patch("app.modules.dev_runner.services.db_service.config", mock_config):
        yield mock_config
