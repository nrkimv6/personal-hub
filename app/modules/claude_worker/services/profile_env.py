"""LLM Engine Profile Env Builder — subprocess 실행 시 env 조립."""

from __future__ import annotations

import logging
import os
import sys
from typing import Dict, Optional

logger = logging.getLogger("claude_worker.profile_env")

# engine → config_dir 주입에 사용할 env 변수명
# Gemini CLI 는 config dir env 변수 미확인 → None (주입 스킵, extra_env 로만 제어)
ENGINE_ENV_KEYS: Dict[str, Optional[str]] = {
    "claude": "CLAUDE_CONFIG_DIR",
    "gemini": None,
}

# extra_env 에 덮어쓰기를 허용하지 않는 시스템 핵심 키
# subprocess UTF-8 env 덮어쓰기 방어 (_dr_subprocess._FORBIDDEN_EXTRA_ENV 와 동기화)
# ⚠ scripts/_dr_subprocess._FORBIDDEN_EXTRA_ENV 를 수정할 때 이 집합도 함께 업데이트할 것
FORBIDDEN_EXTRA_ENV = {
    "COMSPEC",
    "HOME",
    "PATH",
    "PATHEXT",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "PYTHONUNBUFFERED",
    "SYSTEMROOT",
    "USERPROFILE",
}

# Claude CLI 중첩 세션 방지를 위해 제거할 env 키 (engine=="claude" 시)
_CLAUDE_SESSION_VARS = ("CLAUDECODE", "CLAUDE_CODE_SESSION", "CLAUDE_CODE_ENTRYPOINT")


def build_cli_env(engine: str, base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """subprocess 실행용 env 딕셔너리 조립.

    시맨틱:
    - base_env is None  → os.environ.copy() 로 시작
    - base_env 제공     → 해당 dict 를 보존 (chat_executor 의 필터된 env 깨지지 않음)
    - Windows: HOME/USERPROFILE 보정 + npm bin PATH 앞에 추가
    - selected profile 의 config_dir 가 있고 ENGINE_ENV_KEYS[engine] 이 str 이면 주입
    - extra_env merge (FORBIDDEN_EXTRA_ENV 키 포함 시 ValueError)
    - engine=="claude" 일 때만 CLAUDE_CODE_* 세션 변수 제거
    """
    if engine not in ENGINE_ENV_KEYS:
        raise ValueError(f"unsupported engine: {engine!r}. supported: {sorted(ENGINE_ENV_KEYS)}")

    env: Dict[str, str] = dict(base_env) if base_env is not None else dict(os.environ)

    # Windows 보정 (base_env 미제공 시에만 — 이미 보정된 base_env 는 건드리지 않음)
    if base_env is None and sys.platform == "win32":
        npm_path = os.path.expanduser("~/AppData/Roaming/npm")
        if npm_path not in env.get("PATH", ""):
            env["PATH"] = npm_path + ";" + env.get("PATH", "")

        userprofile = env.get("USERPROFILE", "")
        home = env.get("HOME", "")
        if not home and userprofile:
            env["HOME"] = userprofile
            logger.debug(f"[profile-env] HOME 환경변수 설정: {userprofile}")

    # Claude 중첩 세션 방지
    if engine == "claude":
        for var in _CLAUDE_SESSION_VARS:
            env.pop(var, None)

    # selected profile 로드 (import 는 런타임에 — 순환 의존 방지)
    from app.modules.claude_worker.services.profile_store import get_selected

    profile = get_selected(engine)

    # config_dir 주입
    env_key = ENGINE_ENV_KEYS.get(engine)
    if env_key and profile.config_dir:
        env[env_key] = profile.config_dir
        logger.debug(f"[profile-env] {env_key}={profile.config_dir!r} ({engine}/{profile.name})")
    elif env_key and not profile.config_dir:
        # null config_dir → 기존 env 에서 해당 키 제거 (혹여 기존 값 있으면 오염 방지)
        env.pop(env_key, None)

    # extra_env merge
    for k, v in (profile.extra_env or {}).items():
        if k in FORBIDDEN_EXTRA_ENV:
            raise ValueError(
                f"forbidden env key in extra_env: {k!r}. "
                f"forbidden set: {sorted(FORBIDDEN_EXTRA_ENV)}"
            )
        env[k] = v

    return env
