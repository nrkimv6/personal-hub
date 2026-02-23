"""비디오 파일 메타데이터 추출"""
import json
import subprocess
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text


def extract(file_id: int, file_path: str, db: Session) -> dict:
    meta = {}

    try:
        size = Path(file_path).stat().st_size
        meta["size_mb"] = round(size / 1024 / 1024, 1)
        meta["extension"] = Path(file_path).suffix.lower()
    except Exception:
        pass

    # ffprobe로 duration/resolution 추출 시도
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", file_path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json as _json
            probe = _json.loads(result.stdout)
            fmt = probe.get("format", {})
            if "duration" in fmt:
                meta["duration_seconds"] = int(float(fmt["duration"]))
            for stream in probe.get("streams", []):
                if stream.get("codec_type") == "video":
                    meta["width"] = stream.get("width")
                    meta["height"] = stream.get("height")
                    meta["codec"] = stream.get("codec_name")
                    break
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass  # ffprobe 없으면 파일크기/확장자만 사용

    try:
        db.execute(text(
            "UPDATE fc_files SET metadata_json = :meta WHERE id = :id"
        ), {"meta": json.dumps(meta), "id": file_id})
    except Exception as e:
        return {"error": str(e)}

    return meta
