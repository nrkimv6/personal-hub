from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
from typing import Dict, Any

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
        
        if engine not in full_config:
            full_config[engine] = {}
            
        # 기존 설정에 업데이트 병합
        full_config[engine].update(config)
        
        with open(ENGINES_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(full_config, f, indent=2, ensure_ascii=False)
            
        return {"success": True, "message": f"Engine '{engine}' updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")
