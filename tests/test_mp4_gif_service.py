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


def test_run_ffmpeg_conversion_success_requires_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output_path = tmp_path / "result.gif"

    def fake_run(*_args, **_kwargs):
        output_path.write_bytes(b"GIF89a")
        return subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    message = mp4_gif_service.run_ffmpeg_conversion(tmp_path / "a.mp4", output_path, 10)
    assert message is None
    assert output_path.read_bytes() == b"GIF89a"
