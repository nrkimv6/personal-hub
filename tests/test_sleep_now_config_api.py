"""
sleep-now 설정 관리 API 테스트 (Phase 6)

GET /config, GET /config/{section},
PUT /config, POST /config/schedule/exceptions,
DELETE /config/schedule/exceptions/{date}

모든 헬퍼 함수(_load_config, _save_config, _verify_password,
_trigger_reload, _validate_config)를 mock하여 파일시스템 의존성 제거.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ===== 테스트용 기본 설정 =====

SAMPLE_CONFIG = {
    "schedule": {
        "warning_times": ["23:00", "23:30"],
        "block_start": "00:00",
        "block_end": "07:00",
        "exceptions": {},
    },
    "brightness": {
        "enabled": True,
        "dim_brightness": 30,
        "gradual_dim": True,
    },
    "emergency": {
        "password_hash": "abc123realhash",
        "grace_period_minutes": 60,
    },
    "browsers": {
        "chrome": "C:/Program Files/Google/Chrome/Application/chrome.exe",
    },
    "session_worker": {
        "command_file": "data/commands.json",
        "status_file": "data/status.json",
        "heartbeat": 30,
    },
    "exceptions": {
        "local_ports": [],
        "allowed_processes": [],
    },
    "input_blocker": {
        "enabled": True,
        "input_delay_seconds": 5,
    },
    "context_destroyer": {
        "enabled": False,
        "kill_targets": {"kill": []},
        "disable_git_push": False,
    },
    "window_minimizer": {
        "enabled": False,
        "exclude_processes": [],
    },
    "user_lock": {
        "enabled": False,
        "lock_after_block": False,
    },
}

BASE_URL = "/api/v1/sleep-now"


# ===== Phase 6-1: GET /config =====

class TestGetConfig:
    """GET /config — 전체 설정 반환 & password_hash 마스킹 테스트"""

    def test_get_config_returns_all_sections(self):
        """전체 설정 정상 반환 확인"""
        import copy
        with patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)):
            response = client.get(f"{BASE_URL}/config")
            assert response.status_code == 200
            data = response.json()
            assert "schedule" in data
            assert "brightness" in data
            assert "emergency" in data

    def test_get_config_masks_password_hash(self):
        """password_hash가 '***'으로 마스킹됨을 확인"""
        import copy
        with patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)):
            response = client.get(f"{BASE_URL}/config")
            assert response.status_code == 200
            data = response.json()
            assert data["emergency"]["password_hash"] == "***"

    def test_get_config_does_not_expose_real_hash(self):
        """실제 password_hash 값이 응답에 노출되지 않음"""
        config = {"emergency": {"password_hash": "real_secret_hash_abc123"}}
        with patch("app.routes.sleep_now._load_config", return_value=config):
            response = client.get(f"{BASE_URL}/config")
            assert response.status_code == 200
            data = response.json()
            assert "real_secret_hash_abc123" not in str(data)
            assert data["emergency"]["password_hash"] == "***"

    def test_get_config_empty_config(self):
        """설정 파일이 비어있을 때 빈 dict 반환"""
        with patch("app.routes.sleep_now._load_config", return_value={}):
            response = client.get(f"{BASE_URL}/config")
            assert response.status_code == 200
            assert response.json() == {}


# ===== Phase 6-2: GET /config/{section} =====

class TestGetConfigSection:
    """GET /config/{section} — 섹션별 조회 테스트"""

    def test_get_schedule_section(self):
        """schedule 섹션 정상 반환 확인"""
        import copy
        with patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)):
            response = client.get(f"{BASE_URL}/config/schedule")
            assert response.status_code == 200
            data = response.json()
            assert "warning_times" in data
            assert "block_start" in data
            assert "block_end" in data

    def test_get_brightness_section(self):
        """brightness 섹션 정상 반환 확인"""
        import copy
        with patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)):
            response = client.get(f"{BASE_URL}/config/brightness")
            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert data["dim_brightness"] == 30

    def test_get_section_not_found_returns_404(self):
        """존재하지 않는 섹션 요청 시 404 반환"""
        import copy
        with patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)):
            response = client.get(f"{BASE_URL}/config/nonexistent_section")
            assert response.status_code == 404

    def test_get_emergency_section_masks_password_hash(self):
        """emergency 섹션 조회 시 password_hash 마스킹 적용"""
        import copy
        with patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)):
            response = client.get(f"{BASE_URL}/config/emergency")
            assert response.status_code == 200
            data = response.json()
            assert data["password_hash"] == "***"
            assert "abc123realhash" not in str(data)

    def test_get_browsers_section(self):
        """browsers 섹션 정상 반환"""
        import copy
        with patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)):
            response = client.get(f"{BASE_URL}/config/browsers")
            assert response.status_code == 200
            data = response.json()
            assert "chrome" in data


# ===== Phase 6-3: PUT /config =====

class TestPutConfig:
    """PUT /config — 범용 설정 변경 테스트"""

    def test_put_config_single_section_update(self):
        """단일 섹션 부분 업데이트 (brightness.dim_brightness 변경)"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config") as mock_save, \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"brightness": {"dim_brightness": 20}},
            })

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "brightness" in data["sections_updated"]
            mock_save.assert_called_once()

    def test_put_config_multiple_sections_update(self):
        """다중 섹션 동시 변경"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {
                    "brightness": {"dim_brightness": 20},
                    "input_blocker": {"enabled": False},
                },
            })

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            updated = set(data["sections_updated"])
            assert "brightness" in updated
            assert "input_blocker" in updated

    def test_put_config_pydantic_validation_failure_returns_400(self):
        """Pydantic 유효성 검증 실패 시 400 에러"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value="validation error: invalid field"), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"brightness": {"dim_brightness": "not_a_number"}},
            })

            assert response.status_code == 400
            assert "유효성 검증 실패" in response.json()["detail"]

    def test_put_config_blocks_password_hash_change(self):
        """emergency.password_hash 직접 변경 시도 시 400 에러"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"emergency": {"password_hash": "new_hash_attempt"}},
            })

            assert response.status_code == 400
            detail = response.json()["detail"]
            # "PUT /password를 사용하세요" 또는 "password_hash" 포함 여부 확인
            assert "password_hash" in detail or "PUT /password" in detail

    def test_put_config_wrong_password_returns_401(self):
        """잘못된 비밀번호 시 401 에러"""
        with patch("app.routes.sleep_now._verify_password", return_value=False), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "wrong_password",
                "config": {"brightness": {"dim_brightness": 20}},
            })

            assert response.status_code == 401


# ===== Phase 6-4: PUT /config deep merge 검증 =====

class TestPutConfigDeepMerge:
    """PUT /config deep merge 동작 검증"""

    def test_deep_merge_preserves_existing_exceptions(self):
        """schedule.exceptions에 새 날짜 추가 시 기존 날짜가 유지됨"""
        import copy
        base = copy.deepcopy(SAMPLE_CONFIG)
        base["schedule"]["exceptions"] = {
            "2026-02-20": {"enabled": True, "reason": "기존 예외"},
        }

        saved_config = {}

        def capture_save(config):
            saved_config.clear()
            saved_config.update(config)

        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=base), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config", side_effect=capture_save), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {
                    "schedule": {
                        "exceptions": {
                            "2026-02-21": {"enabled": False, "reason": "새 예외"},
                        },
                    },
                },
            })

            assert response.status_code == 200
            # 기존 날짜가 유지됨
            assert "2026-02-20" in saved_config["schedule"]["exceptions"]
            # 새 날짜가 추가됨
            assert "2026-02-21" in saved_config["schedule"]["exceptions"]

    def test_deep_merge_list_full_replace(self):
        """list 필드는 merge가 아닌 전체 교체임을 확인"""
        import copy

        saved_config = {}

        def capture_save(config):
            saved_config.clear()
            saved_config.update(config)

        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config", side_effect=capture_save), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            new_warning_times = ["22:00", "22:30"]
            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"schedule": {"warning_times": new_warning_times}},
            })

            assert response.status_code == 200
            # 기존 ["23:00", "23:30"]이 새 목록으로 교체됨
            assert saved_config["schedule"]["warning_times"] == new_warning_times

    def test_restart_required_for_session_worker(self):
        """session_worker 섹션 변경 시 restart_required=True"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"session_worker": {"heartbeat": 60}},
            })

            assert response.status_code == 200
            assert response.json()["restart_required"] is True

    def test_restart_required_for_browsers(self):
        """browsers 섹션 변경 시 restart_required=True"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"browsers": {"chrome": "C:/new/path/chrome.exe"}},
            })

            assert response.status_code == 200
            assert response.json()["restart_required"] is True

    def test_no_restart_required_for_brightness(self):
        """brightness 섹션 변경 시 restart_required=False"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"brightness": {"dim_brightness": 20}},
            })

            assert response.status_code == 200
            assert response.json()["restart_required"] is False


# ===== Phase 6-5: POST /config/schedule/exceptions =====

class TestPostScheduleExceptions:
    """POST /config/schedule/exceptions — 날짜 예외 추가/수정 테스트"""

    def test_post_new_date_exception(self):
        """새 날짜 예외 추가"""
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value={"schedule": {"exceptions": {}}}), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.post(f"{BASE_URL}/config/schedule/exceptions", json={
                "password": "correct_password",
                "date": "2026-02-25",
                "enabled": True,
                "reason": "특별한 날",
            })

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "2026-02-25" in data["message"]

    def test_post_update_existing_exception(self):
        """기존 날짜 예외 수정 (덮어쓰기)"""
        existing_config = {
            "schedule": {
                "exceptions": {
                    "2026-02-25": {"enabled": True, "reason": "기존 이유"},
                },
            },
        }

        saved = {}

        def capture_save(c):
            saved.clear()
            saved.update(c)

        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=existing_config), \
             patch("app.routes.sleep_now._save_config", side_effect=capture_save), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True), \
             patch("app.routes.sleep_now._log_event"):

            response = client.post(f"{BASE_URL}/config/schedule/exceptions", json={
                "password": "correct_password",
                "date": "2026-02-25",
                "enabled": False,
                "reason": "변경된 이유",
            })

            assert response.status_code == 200
            assert saved["schedule"]["exceptions"]["2026-02-25"]["reason"] == "변경된 이유"
            assert saved["schedule"]["exceptions"]["2026-02-25"]["enabled"] is False

    def test_post_invalid_date_format_returns_422(self):
        """잘못된 날짜 형식 시 422 (Pydantic validator) 에러"""
        response = client.post(f"{BASE_URL}/config/schedule/exceptions", json={
            "password": "correct_password",
            "date": "20260225",  # 잘못된 형식
            "enabled": True,
            "reason": "",
        })

        assert response.status_code in (400, 422)

    def test_post_invalid_date_slash_format_returns_422(self):
        """슬래시 구분자 날짜 형식도 거부"""
        response = client.post(f"{BASE_URL}/config/schedule/exceptions", json={
            "password": "correct_password",
            "date": "2026/02/25",  # 잘못된 형식
            "enabled": True,
            "reason": "",
        })

        assert response.status_code in (400, 422)

    def test_post_wrong_password_returns_401(self):
        """잘못된 비밀번호 시 401 에러"""
        with patch("app.routes.sleep_now._verify_password", return_value=False), \
             patch("app.routes.sleep_now._load_config", return_value={"schedule": {"exceptions": {}}}), \
             patch("app.routes.sleep_now._log_event"):

            response = client.post(f"{BASE_URL}/config/schedule/exceptions", json={
                "password": "wrong_password",
                "date": "2026-02-25",
                "enabled": True,
                "reason": "",
            })

            assert response.status_code == 401


# ===== Phase 6-6: DELETE /config/schedule/exceptions/{date} =====

class TestDeleteScheduleExceptions:
    """DELETE /config/schedule/exceptions/{date} — 날짜 예외 삭제 테스트"""

    def test_delete_existing_exception(self):
        """존재하는 날짜 예외 삭제"""
        config = {
            "schedule": {
                "exceptions": {
                    "2026-02-20": {"enabled": True, "reason": "테스트 예외"},
                },
            },
        }

        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=config), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True):

            response = client.request(
                "DELETE",
                f"{BASE_URL}/config/schedule/exceptions/2026-02-20",
                json={"password": "correct_password"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "2026-02-20" in data["message"]

    def test_delete_nonexistent_exception_returns_404(self):
        """존재하지 않는 날짜 예외 삭제 시 404 에러"""
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value={"schedule": {"exceptions": {}}}):

            response = client.request(
                "DELETE",
                f"{BASE_URL}/config/schedule/exceptions/2026-03-01",
                json={"password": "correct_password"},
            )

            assert response.status_code == 404

    def test_delete_invalid_date_format_returns_400(self):
        """잘못된 날짜 형식 시 400 에러"""
        with patch("app.routes.sleep_now._verify_password", return_value=True):
            response = client.request(
                "DELETE",
                f"{BASE_URL}/config/schedule/exceptions/invalid-date",
                json={"password": "correct_password"},
            )

            assert response.status_code == 400

    def test_delete_wrong_password_returns_401(self):
        """잘못된 비밀번호 시 401 에러"""
        config = {
            "schedule": {
                "exceptions": {
                    "2026-02-20": {"enabled": True, "reason": "예외"},
                },
            },
        }

        with patch("app.routes.sleep_now._verify_password", return_value=False), \
             patch("app.routes.sleep_now._load_config", return_value=config), \
             patch("app.routes.sleep_now._log_event"):

            response = client.request(
                "DELETE",
                f"{BASE_URL}/config/schedule/exceptions/2026-02-20",
                json={"password": "wrong_password"},
            )

            assert response.status_code == 401


# ===== Phase 6-7: 비밀번호 인증 통합 테스트 =====

class TestPasswordAuthentication:
    """모든 변경 API에서 잘못된 비밀번호 → 401 확인"""

    def test_put_config_unauthorized(self):
        """PUT /config — 잘못된 비밀번호 → 401"""
        with patch("app.routes.sleep_now._verify_password", return_value=False), \
             patch("app.routes.sleep_now._load_config", return_value={}), \
             patch("app.routes.sleep_now._log_event"):

            response = client.put(f"{BASE_URL}/config", json={
                "password": "bad_password",
                "config": {"brightness": {"enabled": False}},
            })
            assert response.status_code == 401

    def test_post_exceptions_unauthorized(self):
        """POST /config/schedule/exceptions — 잘못된 비밀번호 → 401"""
        with patch("app.routes.sleep_now._verify_password", return_value=False), \
             patch("app.routes.sleep_now._load_config", return_value={"schedule": {"exceptions": {}}}), \
             patch("app.routes.sleep_now._log_event"):

            response = client.post(f"{BASE_URL}/config/schedule/exceptions", json={
                "password": "bad_password",
                "date": "2026-02-25",
                "enabled": True,
                "reason": "",
            })
            assert response.status_code == 401

    def test_delete_exceptions_unauthorized(self):
        """DELETE /config/schedule/exceptions/{date} — 잘못된 비밀번호 → 401"""
        config = {"schedule": {"exceptions": {"2026-02-25": {"enabled": True, "reason": ""}}}}

        with patch("app.routes.sleep_now._verify_password", return_value=False), \
             patch("app.routes.sleep_now._load_config", return_value=config), \
             patch("app.routes.sleep_now._log_event"):

            response = client.request(
                "DELETE",
                f"{BASE_URL}/config/schedule/exceptions/2026-02-25",
                json={"password": "bad_password"},
            )
            assert response.status_code == 401


# ===== Phase 6-8: reload_trigger 연동 테스트 =====

class TestReloadTrigger:
    """설정 변경 후 _trigger_reload 호출 확인"""

    def test_put_config_calls_trigger_reload(self):
        """PUT /config 성공 시 _trigger_reload 호출"""
        import copy
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=copy.deepcopy(SAMPLE_CONFIG)), \
             patch("app.routes.sleep_now._validate_config", return_value=None), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True) as mock_trigger, \
             patch("app.routes.sleep_now._log_event"):

            client.put(f"{BASE_URL}/config", json={
                "password": "correct_password",
                "config": {"brightness": {"dim_brightness": 25}},
            })

            mock_trigger.assert_called_once()

    def test_post_exception_calls_trigger_reload(self):
        """POST /config/schedule/exceptions 성공 시 _trigger_reload 호출"""
        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value={"schedule": {"exceptions": {}}}), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True) as mock_trigger, \
             patch("app.routes.sleep_now._log_event"):

            client.post(f"{BASE_URL}/config/schedule/exceptions", json={
                "password": "correct_password",
                "date": "2026-02-25",
                "enabled": True,
                "reason": "테스트",
            })

            mock_trigger.assert_called_once()

    def test_delete_exception_calls_trigger_reload(self):
        """DELETE /config/schedule/exceptions/{date} 성공 시 _trigger_reload 호출"""
        config = {"schedule": {"exceptions": {"2026-02-25": {"enabled": True, "reason": ""}}}}

        with patch("app.routes.sleep_now._verify_password", return_value=True), \
             patch("app.routes.sleep_now._load_config", return_value=config), \
             patch("app.routes.sleep_now._save_config"), \
             patch("app.routes.sleep_now._trigger_reload", return_value=True) as mock_trigger:

            client.request(
                "DELETE",
                f"{BASE_URL}/config/schedule/exceptions/2026-02-25",
                json={"password": "correct_password"},
            )

            mock_trigger.assert_called_once()

    def test_reload_trigger_file_creation(self, tmp_path):
        """_trigger_reload가 실제로 파일을 생성하는지 확인 (유닛 테스트)"""
        from app.routes.sleep_now import _trigger_reload
        import app.routes.sleep_now as module

        original_path = module.SLEEP_NOW_PATH
        module.SLEEP_NOW_PATH = tmp_path

        try:
            result = _trigger_reload()
            assert result is True
            trigger_file = tmp_path / "data" / "reload_trigger"
            assert trigger_file.exists()
            content = trigger_file.read_text(encoding="utf-8")
            assert len(content) > 0  # ISO 날짜/시간 문자열 포함
        finally:
            module.SLEEP_NOW_PATH = original_path
