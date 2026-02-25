import json
import pytest
from pathlib import Path

# Paths
WTOOLS_BASE_DIR = Path(r"D:\work\project\service\wtools")
GEMINI_SETTINGS_PATH = WTOOLS_BASE_DIR / ".gemini" / "settings.json"
PLAN_RUNNER_CONFIGS = WTOOLS_BASE_DIR / "common" / "tools" / "plan-runner" / "engines.json"

class TestConfigEncoding:
    """JSON 설정 파일이 UTF-8 BOM 없는 순수 UTF-8이며 유효한 JSON인지 검증"""

    def test_gemini_settings_no_bom_and_valid_json(self):
        """Right - .gemini/settings.json 파일에 BOM이 없고 JSON 파싱이 성공하는가?"""
        if not GEMINI_SETTINGS_PATH.exists():
            pytest.skip(f"{GEMINI_SETTINGS_PATH} does not exist.")
            
        with open(GEMINI_SETTINGS_PATH, "rb") as f:
            raw_content = f.read()
            
        # 1. Check for BOM (\xef\xbb\xbf)
        assert not raw_content.startswith(b'\xef\xbb\xbf'), "settings.json starts with UTF-8 BOM. Please save as UTF-8 without BOM."
        
        # 2. Check JSON Parse (Standard parser will fail if BOM was loaded as string without robust handling)
        content_str = raw_content.decode('utf-8')
        try:
            json.loads(content_str)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON in settings.json: {e}")

    def test_plan_runner_engines_no_bom_and_valid_json(self):
        """Right - engines.json 파일에 BOM이 없고 JSON 파싱이 성공하는가?"""
        if not PLAN_RUNNER_CONFIGS.exists():
            pytest.skip(f"{PLAN_RUNNER_CONFIGS} does not exist.")
            
        with open(PLAN_RUNNER_CONFIGS, "rb") as f:
            raw_content = f.read()
            
        assert not raw_content.startswith(b'\xef\xbb\xbf'), "engines.json starts with UTF-8 BOM."
        
        content_str = raw_content.decode('utf-8')
        try:
            json.loads(content_str)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON in engines.json: {e}")
