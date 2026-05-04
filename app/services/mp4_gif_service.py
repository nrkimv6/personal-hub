"""Service helpers for MP4 -> GIF conversion."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import PROJECT_ROOT, settings

_SAFE_FILE_RE = re.compile(r"[^0-9A-Za-z가-힣._-]+")

# ── 후속 범위 밖 (1차 통합에서 제외된 옵션) ────────────────────────────────
# 아래 ffmpeg 옵션은 이번 후속 계획 범위 밖이다.
# loop_count, dither_mode, palette_stats_mode, crop, reverse, caption
# 필요할 때 별도 계획으로 추가한다.
# ────────────────────────────────────────────────────────────────────────────

# 허용하는 overwrite 모드 (route 상수와 일치)
ALLOWED_OVERWRITE_MODES = ("overwrite", "suffix", "fail_if_exists")


@dataclass
class Mp4GifOptionPreset:
    fps: int
    width: int | None


def resolve_preset(name: str) -> Mp4GifOptionPreset:
    """preset 이름을 옵션 조합으로 변환한다.

    preset 이름과 화면 문구는 REQUIREMENTS.md 기준 wording을 따른다.
    - 고화질: fps=15, 원본 해상도
    - 균형:   fps=10, 720px 폭
    - 저용량:  fps=6,  480px 폭
    """
    presets: dict[str, Mp4GifOptionPreset] = {
        "고화질": Mp4GifOptionPreset(fps=15, width=None),
        "균형": Mp4GifOptionPreset(fps=10, width=720),
        "저용량": Mp4GifOptionPreset(fps=6, width=480),
    }
    if name not in presets:
        raise ValueError(f"알 수 없는 preset 이름입니다: {name!r}. 허용: {list(presets)}")
    return presets[name]


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
    width: int | None = None,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> list[str]:
    if fps <= 0:
        raise ValueError(f"fps must be >= 1, got {fps}")
    if width is not None and width <= 0:
        raise ValueError(f"width must be >= 1, got {width}")
    if start_seconds is not None and start_seconds < 0:
        raise ValueError(f"start_seconds must be >= 0, got {start_seconds}")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be > 0, got {duration_seconds}")

    # scale 필터: width가 있으면 축소, 없으면 원본 해상도
    if width is not None:
        scale_filter = f"scale={width}:-1,"
    else:
        scale_filter = ""

    # palette 필터는 scale 뒤에 고정 위치로 작성해 테스트 가능성을 높인다
    filter_graph = (
        f"{scale_filter}fps={fps},split[s0][s1];"
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


def build_internal_output_name(source_name: str) -> str:
    """task 내부 저장에 쓰는 GIF 파일명을 계산한다.

    task 디렉토리는 UUID별로 격리되므로 파일명은 stem + .gif만으로 충분하다.
    """
    stem = Path(sanitize_source_name(source_name)).stem
    return f"{stem}.gif"


def build_download_filename(
    source_name: str,
    *,
    fps: int | None = None,
    width: int | None = None,
    overwrite_mode: str = "overwrite",
) -> str:
    """사용자 다운로드 파일명을 계산한다.

    - overwrite_mode='suffix' → stem_gif_fpsN_wW.gif (옵션 요약 suffix)
    - 그 외 → stem.gif (기본)
    """
    stem = Path(sanitize_source_name(source_name)).stem
    if overwrite_mode == "suffix":
        parts: list[str] = ["gif"]
        if fps is not None:
            parts.append(f"fps{fps}")
        if width is not None:
            parts.append(f"w{width}")
        suffix_str = "_".join(parts)
        return f"{stem}_{suffix_str}.gif"
    return f"{stem}.gif"


def run_ffmpeg_conversion(
    input_path: Path,
    output_path: Path,
    fps: int,
    *,
    width: int | None = None,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> str | None:
    command = build_ffmpeg_command(
        input_path, output_path, fps,
        width=width,
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
