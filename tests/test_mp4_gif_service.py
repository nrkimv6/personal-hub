from pathlib import Path
import subprocess

import pytest

from app.services import mp4_gif_service


def test_build_ffmpeg_command_right_basic(tmp_path: Path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.gif"

    command = mp4_gif_service.build_ffmpeg_command(input_path, output_path, 10)

    assert command[:4] == ["ffmpeg", "-y", "-i", str(input_path)]
    assert "-vf" in command
    assert "fps=10" in command[command.index("-vf") + 1]
    assert command[-1] == str(output_path)


def test_build_ffmpeg_command_boundary_fps_1(tmp_path: Path):
    command = mp4_gif_service.build_ffmpeg_command(tmp_path / "a.mp4", tmp_path / "a.gif", 1)
    assert "fps=1" in command[command.index("-vf") + 1]


def test_decode_process_output_error_cp949():
    raw = "잘못된 입력 파일".encode("cp949")
    assert mp4_gif_service.decode_process_output(raw) == "잘못된 입력 파일"


def test_run_ffmpeg_conversion_error_when_binary_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)

    message = mp4_gif_service.run_ffmpeg_conversion(tmp_path / "a.mp4", tmp_path / "a.gif", 10)
    assert "ffmpeg" in message.lower()


def test_run_ffmpeg_conversion_error_from_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["ffmpeg"],
            stderr="Invalid data found when processing input".encode("utf-8"),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    message = mp4_gif_service.run_ffmpeg_conversion(tmp_path / "a.mp4", tmp_path / "a.gif", 10)
    assert message == "Invalid data found when processing input"


# ─── trim TC (Phase T1, item 15) ──────────────────────────────────────────────

def test_build_ffmpeg_command_right_no_trim(tmp_path: Path):
    """Right: trim 인자가 없으면 -ss, -t가 모두 빠진다."""
    cmd = mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10)
    assert "-ss" not in cmd
    assert "-t" not in cmd


def test_build_ffmpeg_command_right_start_only(tmp_path: Path):
    """Right: start_seconds=5.0이면 -ss 인덱스가 -i보다 앞에 온다."""
    cmd = mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, start_seconds=5.0)
    assert "-ss" in cmd
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-t" not in cmd


def test_build_ffmpeg_command_right_both_trim(tmp_path: Path):
    """Right: start=3.0, duration=10.0일 때 -ss와 -t가 둘 다 포함되고 순서가 맞다."""
    cmd = mp4_gif_service.build_ffmpeg_command(
        tmp_path / "i.mp4", tmp_path / "o.gif", 10, start_seconds=3.0, duration_seconds=10.0
    )
    assert "-ss" in cmd
    assert "-t" in cmd
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd.index("-t") > cmd.index("-i")
    assert cmd.index("-t") < cmd.index("-vf")
    assert cmd[-1] == str(tmp_path / "o.gif")


def test_build_ffmpeg_command_boundary_zero_start(tmp_path: Path):
    """Boundary: start_seconds=0.0은 허용된다."""
    cmd = mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, start_seconds=0.0)
    assert "-ss" in cmd


def test_build_ffmpeg_command_error_negative_start(tmp_path: Path):
    """Error: 음수 시작점은 ValueError를 던진다."""
    with pytest.raises(ValueError, match="start_seconds"):
        mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, start_seconds=-1.0)


def test_build_ffmpeg_command_error_zero_duration(tmp_path: Path):
    """Error: duration_seconds=0.0은 ValueError를 던진다."""
    with pytest.raises(ValueError, match="duration_seconds"):
        mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, duration_seconds=0.0)


# ──────────────────────────────────────────────────────────────────────────────

def test_run_ffmpeg_conversion_success_requires_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output_path = tmp_path / "result.gif"

    def fake_run(*_args, **_kwargs):
        output_path.write_bytes(b"GIF89a")
        return subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    message = mp4_gif_service.run_ffmpeg_conversion(tmp_path / "a.mp4", output_path, 10)
    assert message is None
    assert output_path.read_bytes() == b"GIF89a"


# ─── width TC (Phase T1/T2) ───────────────────────────────────────────────────

def test_build_ffmpeg_command_right_width(tmp_path: Path):
    """Right: width=540 이면 -vf 값에 scale=540:-1 이 포함된다."""
    cmd = mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, width=540)
    vf_value = cmd[cmd.index("-vf") + 1]
    assert "scale=540:-1" in vf_value


def test_build_ffmpeg_command_right_no_width_no_scale(tmp_path: Path):
    """Right: width 없으면 scale 필터가 포함되지 않는다."""
    cmd = mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10)
    vf_value = cmd[cmd.index("-vf") + 1]
    assert "scale=" not in vf_value


def test_build_ffmpeg_command_error_fps_zero(tmp_path: Path):
    """Error: fps=0은 ValueError를 던진다."""
    with pytest.raises(ValueError, match="fps"):
        mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 0)


def test_build_ffmpeg_command_error_fps_negative(tmp_path: Path):
    """Error: 음수 fps는 ValueError를 던진다."""
    with pytest.raises(ValueError, match="fps"):
        mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", -1)


def test_build_ffmpeg_command_error_width_zero(tmp_path: Path):
    """Error: width=0은 ValueError를 던진다."""
    with pytest.raises(ValueError, match="width"):
        mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, width=0)


def test_build_ffmpeg_command_error_width_negative(tmp_path: Path):
    """Error: 음수 width는 ValueError를 던진다."""
    with pytest.raises(ValueError, match="width"):
        mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, width=-10)


def test_build_ffmpeg_command_boundary_trim_zero_rejected(tmp_path: Path):
    """Boundary: duration_seconds=0은 ValueError(duration_seconds)를 던진다."""
    with pytest.raises(ValueError, match="duration_seconds"):
        mp4_gif_service.build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, duration_seconds=0.0)


# ─── overwrite mode TC ────────────────────────────────────────────────────────

def test_build_download_filename_overwrite_mode_default(tmp_path: Path):
    """Right: overwrite 모드에서는 기본 stem.gif 반환."""
    name = mp4_gif_service.build_download_filename("sample.mp4", fps=10, width=540, overwrite_mode="overwrite")
    assert name == "sample.gif"


def test_build_download_filename_suffix_mode_includes_options(tmp_path: Path):
    """Right: suffix 모드에서는 fps/width 요약 suffix가 붙는다."""
    name = mp4_gif_service.build_download_filename("clip.mp4", fps=8, width=540, overwrite_mode="suffix")
    assert name == "clip_gif_fps8_w540.gif"


def test_build_download_filename_suffix_no_width(tmp_path: Path):
    """Right: suffix 모드 + width=None 이면 width suffix가 없다."""
    name = mp4_gif_service.build_download_filename("clip.mp4", fps=10, width=None, overwrite_mode="suffix")
    assert name == "clip_gif_fps10.gif"


def test_build_ffmpeg_command_error_unknown_overwrite_mode(tmp_path: Path):
    """Error: resolve_preset에서 알 수 없는 이름이면 ValueError를 던진다."""
    with pytest.raises(ValueError, match="preset"):
        mp4_gif_service.resolve_preset("존재하지않는프리셋")


# ─── resolve_preset TC ────────────────────────────────────────────────────────

def test_resolve_preset_균형():
    """Right: '균형' preset은 fps=10, width=720 이다."""
    p = mp4_gif_service.resolve_preset("균형")
    assert p.fps == 10
    assert p.width == 720


def test_resolve_preset_저용량():
    """Right: '저용량' preset은 fps=6, width=480 이다."""
    p = mp4_gif_service.resolve_preset("저용량")
    assert p.fps == 6
    assert p.width == 480


def test_resolve_preset_고화질():
    """Right: '고화질' preset은 fps=15, width=None 이다."""
    p = mp4_gif_service.resolve_preset("고화질")
    assert p.fps == 15
    assert p.width is None
