"""Service helpers for MP4 -> GIF conversion."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import PROJECT_ROOT, settings

_SAFE_FILE_RE = re.compile(r"[^0-9A-Za-z가-힣._-]+")


def get_work_root() -> Path:
    root = Path(settings.MP4_GIF_WORK_ROOT)
    return root if root.is_absolute() else (PROJECT_ROOT / root).resolve()


def sanitize_source_name(source_name: str) -> str:
    base_name = Path(source_name).name.strip() or "video.mp4"
    stem = _SAFE_FILE_RE.sub("_", Path(base_name).stem).strip("._")
    if not stem:
        stem = "video"
    return f"{stem}.mp4"


def get_task_workdir(task_id: str) -> Path:
    return get_work_root() / task_id


def get_task_input_path(task_id: str, source_name: str) -> Path:
    return get_task_workdir(task_id) / sanitize_source_name(source_name)


def get_task_output_path(task_id: str, source_name: str) -> Path:
    return get_task_workdir(task_id) / f"{Path(sanitize_source_name(source_name)).stem}.gif"


def validate_mp4_upload(file_name: str, size_bytes: int | None) -> None:
    if Path(file_name).suffix.lower() != ".mp4":
        raise ValueError("MP4 파일만 업로드할 수 있습니다.")

    if size_bytes is not None:
        max_bytes = int(settings.MP4_GIF_MAX_UPLOAD_MB) * 1024 * 1024
        if size_bytes > max_bytes:
            raise ValueError(
                f"업로드 크기 제한을 초과했습니다. 최대 {settings.MP4_GIF_MAX_UPLOAD_MB}MB까지 허용됩니다."
            )


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    fps: int,
    *,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> list[str]:
    if start_seconds is not None and start_seconds < 0:
        raise ValueError(f"start_seconds must be >= 0, got {start_seconds}")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be > 0, got {duration_seconds}")

    filter_graph = (
        f"fps={fps},split[s0][s1];"
        f"[s0]palettegen[p];"
        f"[s1][p]paletteuse"
    )
    cmd: list[str] = ["ffmpeg", "-y"]
    if start_seconds is not None:
        cmd += ["-ss", str(start_seconds)]
    cmd += ["-i", str(input_path)]
    if duration_seconds is not None:
        cmd += ["-t", str(duration_seconds)]
    cmd += ["-vf", filter_graph, str(output_path)]
    return cmd


def decode_process_output(raw: bytes | None) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def summarize_ffmpeg_error(stderr_text: str) -> str:
    candidates = [line.strip() for line in stderr_text.splitlines() if line.strip()]
    for line in reversed(candidates):
        lowered = line.lower()
        if "error" in lowered or "failed" in lowered or "invalid" in lowered:
            return line
    return candidates[-1] if candidates else "ffmpeg 변환에 실패했습니다."


def run_ffmpeg_conversion(
    input_path: Path,
    output_path: Path,
    fps: int,
    *,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> str | None:
    command = build_ffmpeg_command(
        input_path, output_path, fps,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=True,
            timeout=300,
        )
    except FileNotFoundError:
        return "ffmpeg 실행 파일을 찾을 수 없습니다. PATH 설정을 확인하세요."
    except subprocess.TimeoutExpired:
        return "ffmpeg 변환 시간이 초과되었습니다."
    except subprocess.CalledProcessError as exc:
        return summarize_ffmpeg_error(decode_process_output(exc.stderr))

    if completed.returncode != 0:
        return summarize_ffmpeg_error(decode_process_output(completed.stderr))

    if not output_path.exists() or output_path.stat().st_size <= 0:
        return "GIF 결과 파일이 생성되지 않았습니다."

    return None


def ffmpeg_health() -> tuple[bool, str | None]:
    ffmpeg_path = shutil.which("ffmpeg")
    return ffmpeg_path is not None, ffmpeg_path


def cleanup_expired_workdirs(now: datetime | None = None) -> int:
    current = now or datetime.now()
    cutoff = current - timedelta(hours=24)
    removed = 0
    root = get_work_root()
    if not root.exists():
        return 0

    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            resolved = child.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        modified_at = datetime.fromtimestamp(child.stat().st_mtime)
        if modified_at < cutoff:
            shutil.rmtree(resolved, ignore_errors=True)
            removed += 1
    return removed
