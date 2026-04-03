from pathlib import Path
import json
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter()

# engines.json 경로 설정 (plan-runner 위치 기준)
ENGINES_JSON_PATH = Path("D:/work/project/service/wtools/common/tools/plan-runner/engines.json")


@router.get("")
async def get_engines_config():
    """모든 엔진 설정 조회"""
    if not ENGINES_JSON_PATH.exists():
        raise HTTPException(status_code=404, detail="engines.json file not found")

    try:
        content = ENGINES_JSON_PATH.read_text(encoding="utf-8-sig")
        return json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read settings: {str(e)}")


@router.put("/{engine}")
async def update_engine_config(engine: str, config: Dict[str, Any]):
    """특정 엔진의 설정(모델, 플래그 등) 업데이트"""
    if not ENGINES_JSON_PATH.exists():
        raise HTTPException(status_code=404, detail="engines.json file not found")

    try:
        content = ENGINES_JSON_PATH.read_text(encoding="utf-8-sig")
        full_config = json.loads(content)

        engine_config = full_config.get(engine, {})
        if not isinstance(engine_config, dict):
            engine_config = {}

        overwrite_all_phases = bool(config.get("overwrite_all_phases", False))

        # models는 key 단위 deep-merge + 타입 검증
        has_models_patch = "models" in config
        models_patch = config.get("models")
        if has_models_patch and not isinstance(models_patch, dict):
            raise HTTPException(status_code=400, detail="'models' must be an object")

        next_engine_config = dict(engine_config)
        if overwrite_all_phases:
            requested_default_model = config.get("default_model")
            if requested_default_model is not None and not isinstance(requested_default_model, str):
                requested_default_model = str(requested_default_model)
            requested_default_model = (requested_default_model or "").strip()

            existing_default_model = next_engine_config.get("default_model")
            if existing_default_model is not None and not isinstance(existing_default_model, str):
                existing_default_model = str(existing_default_model)
            existing_default_model = (existing_default_model or "").strip()

            bulk_model = requested_default_model or existing_default_model
            if not bulk_model:
                raise HTTPException(
                    status_code=400,
                    detail="'overwrite_all_phases=true' requires non-empty default_model (current or requested)",
                )

            existing_models = next_engine_config.get("models", {})
            if not isinstance(existing_models, dict):
                existing_models = {}

            phase_keys = set(existing_models.keys())
            if has_models_patch:
                phase_keys.update(models_patch.keys())
            if not phase_keys:
                phase_keys = {"plan", "impl", "done"}

            next_engine_config["default_model"] = bulk_model
            next_engine_config["models"] = {
                str(phase): bulk_model for phase in sorted(phase_keys)
            }
        elif has_models_patch:
            existing_models = next_engine_config.get("models", {})
            if not isinstance(existing_models, dict):
                existing_models = {}
            next_engine_config["models"] = {**existing_models, **models_patch}

        # models 외 top-level 키는 기존 update 동작 유지
        for key, value in config.items():
            if key in {"models", "overwrite_all_phases"}:
                continue
            next_engine_config[key] = value

        full_config[engine] = next_engine_config
        ENGINES_JSON_PATH.write_text(
            json.dumps(full_config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"success": True, "message": f"Engine '{engine}' updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")
