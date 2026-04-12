"""LLM Profile E2E — 저장→조회→select→실행까지 전체 흐름 검증.

mock 범위: subprocess.run / subprocess.Popen 만.
파일시스템 / os.environ / profile_store 는 실물 사용.
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import app.modules.claude_worker.services.profile_store as ps


@pytest.fixture(autouse=True)
def isolate_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", tmp_path / "llm_profiles.json")
    yield tmp_path


@pytest.mark.e2e
def test_profile_crud_flow_e2e(isolate_profiles):
    """저장 → 조회 → select → llm_service 실행 시 선택된 profile env 사용까지 전체 흐름."""
    # 1) profile 저장 (real fs write)
    ps.save_profiles({
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": str(isolate_profiles / ".claude-work"), "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })

    # 2) select "work"
    ps.select("claude", "work")

    # 3) load 확인
    loaded = ps.load_profiles()
    assert loaded["selected"]["claude"] == "work"

    # 4) llm_service execute 시 env에 CLAUDE_CONFIG_DIR 주입
    captured_envs = []

    def capture_run(*args, **kwargs):
        captured_envs.append(kwargs.get("env", {}))
        m = MagicMock()
        m.returncode = 0
        m.stdout = "ok"
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.llm_service import LLMService
        svc = LLMService(MagicMock())
        try:
            svc.execute_claude("test prompt", timeout=5)
        except Exception:
            pass  # 결과 파싱 실패는 무시

    assert len(captured_envs) > 0, "subprocess.run 이 호출되지 않음"
    env_used = captured_envs[0]
    assert "CLAUDE_CONFIG_DIR" in env_used, "CLAUDE_CONFIG_DIR 이 env 에 없음"
    assert str(isolate_profiles / ".claude-work") in env_used["CLAUDE_CONFIG_DIR"]


@pytest.mark.e2e
def test_profile_delete_selected_fallback_e2e(isolate_profiles):
    """selected profile 삭제 후 default 로 전환되고 이후 실행에 반영."""
    # work profile 저장 + 선택
    ps.save_profiles({
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": str(isolate_profiles / ".claude-work"), "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })

    # 선택된 "work" 삭제
    saved = ps.delete("claude", "work")

    # default 로 fallback 됐는지 확인
    assert saved["selected"]["claude"] == "default"
    names = [p["name"] for p in saved["profiles"] if p["engine"] == "claude"]
    assert "work" not in names

    # 이후 실행 시 CLAUDE_CONFIG_DIR 없음 (default)
    captured_envs = []

    def capture_run(*args, **kwargs):
        captured_envs.append(kwargs.get("env", {}))
        m = MagicMock()
        m.returncode = 0
        m.stdout = "ok"
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.llm_service import LLMService
        svc = LLMService(MagicMock())
        try:
            svc.execute_claude("test prompt", timeout=5)
        except Exception:
            pass

    assert len(captured_envs) > 0
    env_used = captured_envs[0]
    assert "CLAUDE_CONFIG_DIR" not in env_used, "default profile 이후 CLAUDE_CONFIG_DIR 가 남아있음"


# ────────────────────────────────────────────
# T3: 원본 버그 재현 fixture + 통합 TC
# ────────────────────────────────────────────

@pytest.mark.e2e
def test_save_profile_with_pythonioencoding_blocked_e2e(isolate_profiles):
    """T3: extra_env={"PYTHONIOENCODING": "ascii"} 포함 프로필을 save_profiles()로 저장 시도 → ValueError.

    원본 버그 재현: 수정 전에는 profile_env.FORBIDDEN_EXTRA_ENV 에 PYTHONIOENCODING 이 없어
    save_profiles() 검증을 통과했고, dev-runner 실행 시점에만 ValueError 가 발생했다.
    수정 후에는 저장 시점에도 ValueError 를 raise 해야 한다.
    """
    import app.modules.claude_worker.services.profile_store as ps_real

    bad_payload = {
        "selected": {"claude": "bad", "gemini": "default"},
        "profiles": [
            {
                "engine": "claude",
                "name": "bad",
                "config_dir": None,
                "extra_env": {"PYTHONIOENCODING": "ascii"},
            },
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    with pytest.raises(ValueError, match="forbidden env key"):
        ps_real.save_profiles(bad_payload)


@pytest.mark.e2e
def test_forbidden_env_set_symmetric_e2e(isolate_profiles):
    """T3: _dr_subprocess._FORBIDDEN_EXTRA_ENV ⊆ profile_env.FORBIDDEN_EXTRA_ENV 집합 포함 관계 검증.

    두 집합이 불일치하면 "저장 성공 → 실행 실패" 경로가 열린다는 것을 증명한다.
    이 TC 가 회귀 시 실패하면 두 집합의 동기화가 깨진 것이다.
    """
    import importlib.util
    import sys
    from pathlib import Path
    from unittest.mock import MagicMock

    import app.modules.claude_worker.services.profile_env as pe

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "_dr_subprocess_e2e", scripts_dir / "_dr_subprocess.py"
    )
    dr_sub = importlib.util.module_from_spec(spec)

    stub_names = ["redis", "_dr_constants", "_dr_state"]
    stubs = {}
    for mod_name in stub_names:
        if mod_name not in sys.modules:
            stub = MagicMock()
            sys.modules[mod_name] = stub
            stubs[mod_name] = stub

    try:
        spec.loader.exec_module(dr_sub)
    finally:
        for mod_name, stub in stubs.items():
            if sys.modules.get(mod_name) is stub:
                del sys.modules[mod_name]

    sub_forbidden: set = dr_sub._FORBIDDEN_EXTRA_ENV
    assert sub_forbidden <= pe.FORBIDDEN_EXTRA_ENV, (
        "저장→실행 파이프라인에서 두 집합 불일치 — '저장 성공·실행 실패' 경로 열림. "
        f"누락 키: {sub_forbidden - pe.FORBIDDEN_EXTRA_ENV}"
    )
