"""T3 통합 TC: 실제 파일시스템 기반 mp4_gif_service 계약 검증.

서버 불필요 — tmp_path와 stub ffmpeg로 격리 실행.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.mp4_gif_task import Mp4GifTask
from app.services.mp4_gif_service import (
    build_ffmpeg_command,
    cleanup_expired_workdirs,
    get_task_input_path,
    get_task_output_path,
    get_task_workdir,
    get_work_root,
    run_ffmpeg_conversion,
)


# ───────────────────────── 헬퍼 ─────────────────────────

def _make_sqlite_session(work_root: Path):
    """Mp4GifTask 테이블만 담은 인메모리 SQLite 세션을 반환한다."""
    from app.core.database import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[Mp4GifTask.__table__])
    Session = sessionmaker(bind=engine)
    return Session(), engine



# ───────────────────────── Path 계약 ─────────────────────────

def test_input_path_is_under_task_workdir(tmp_path):
    """임시 작업 루트에서 input 경로가 task 폴더 아래에 생성된다."""
    with patch("app.services.mp4_gif_service.get_work_root", return_value=tmp_path):
        task_id = "test-task-abc"
        input_path = get_task_input_path(task_id, "sample.mp4")
        work_dir = get_task_workdir(task_id)

    assert input_path.parent == work_dir
    assert work_dir.parent == tmp_path


def test_output_gif_path_is_under_same_task_workdir(tmp_path):
    """임시 작업 루트에서 output GIF 경로가 같은 task 폴더 아래에 생성된다."""
    with patch("app.services.mp4_gif_service.get_work_root", return_value=tmp_path):
        task_id = "test-task-abc"
        output_path = get_task_output_path(task_id, "sample.mp4")
        work_dir = get_task_workdir(task_id)

    assert output_path.parent == work_dir
    assert output_path.suffix == ".gif"


# ───────────────────────── Retention 계약 ─────────────────────────

def test_cleanup_removes_only_expired_dirs(tmp_path):
    """오래된 폴더만 retention 대상으로 판정된다."""
    old_dir = tmp_path / "old-task"
    old_dir.mkdir()
    recent_dir = tmp_path / "new-task"
    recent_dir.mkdir()

    # old_dir mtime을 25시간 전으로 조작
    old_mtime = (datetime.now() - timedelta(hours=25)).timestamp()
    os.utime(str(old_dir), (old_mtime, old_mtime))

    now = datetime.now()
    with patch("app.services.mp4_gif_service.get_work_root", return_value=tmp_path):
        removed = cleanup_expired_workdirs(now=now)

    assert removed == 1
    assert not old_dir.exists()
    assert recent_dir.exists()


# ───────────────────────── stub ffmpeg 변환 ─────────────────────────

def test_run_ffmpeg_conversion_success_with_stub(tmp_path):
    """subprocess.run stub으로 성공 변환 시 GIF 산출물이 생기는지 검증한다.

    Note: Windows CreateProcess는 .bat/.cmd를 PATH로 찾지 못하므로
    subprocess.run 자체를 패치해 실제 파일 생성/반환값 계약을 검증한다.
    """
    import subprocess
    from unittest.mock import MagicMock

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"\x00" * 64)
    output_file = tmp_path / "output.gif"

    def _fake_run(cmd, **kwargs):
        # stub: output 경로(마지막 인자)에 가짜 GIF 파일 생성
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"GIF89a" + b"\x00" * 16)
        result = MagicMock()
        result.returncode = 0
        result.stderr = b""
        return result

    with patch("app.services.mp4_gif_service.subprocess.run", side_effect=_fake_run):
        error_msg = run_ffmpeg_conversion(input_file, output_file, fps=10)

    assert error_msg is None, f"성공 stub인데 에러: {error_msg}"
    assert output_file.exists(), "GIF 산출물이 생성되지 않았습니다."
    assert output_file.stat().st_size > 0


# ───────────────────────── 상태 전이 ─────────────────────────

def test_state_transition_queued_to_completed(tmp_path):
    """성공 변환 시 queued -> running -> completed 상태 전이가 저장된다."""
    from unittest.mock import MagicMock

    session, engine = _make_sqlite_session(tmp_path)

    input_file = tmp_path / "in.mp4"
    input_file.write_bytes(b"\x00" * 64)
    output_file = tmp_path / "out.gif"

    task = Mp4GifTask(
        task_id="t-success-001",
        status=Mp4GifTask.STATUS_QUEUED,
        source_name="in.mp4",
        stored_input_path=str(input_file),
        stored_output_path=str(output_file),
        fps=10,
    )
    session.add(task)
    session.commit()

    # running 전이 검증
    task.mark_running()
    session.commit()
    assert task.status == Mp4GifTask.STATUS_RUNNING
    assert task.started_at is not None

    # stub ffmpeg: output 파일 생성 후 success 반환
    def _fake_run(cmd, **kwargs):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"GIF89a" + b"\x00" * 16)
        m = MagicMock()
        m.returncode = 0
        m.stderr = b""
        return m

    with patch("app.services.mp4_gif_service.subprocess.run", side_effect=_fake_run):
        error_msg = run_ffmpeg_conversion(input_file, output_file, fps=10)

    if error_msg:
        task.mark_failed(error_msg)
    else:
        task.mark_completed()
    session.commit()

    reloaded = session.query(Mp4GifTask).filter_by(task_id="t-success-001").first()
    assert reloaded.status == Mp4GifTask.STATUS_COMPLETED
    assert reloaded.completed_at is not None
    assert reloaded.error_message is None

    session.close()
    engine.dispose()


def test_state_transition_queued_to_failed(tmp_path):
    """실패 stub 반환 시 failed와 error_message가 DB에 저장된다."""
    import subprocess as _subprocess
    from unittest.mock import MagicMock

    session, engine = _make_sqlite_session(tmp_path)

    input_file = tmp_path / "in.mp4"
    input_file.write_bytes(b"\x00" * 64)
    output_file = tmp_path / "out.gif"

    task = Mp4GifTask(
        task_id="t-fail-001",
        status=Mp4GifTask.STATUS_QUEUED,
        source_name="in.mp4",
        stored_input_path=str(input_file),
        stored_output_path=str(output_file),
        fps=10,
    )
    session.add(task)
    session.commit()

    task.mark_running()
    session.commit()

    # stub ffmpeg: output 파일 생성 없이 CalledProcessError 발생
    def _fake_fail(cmd, **kwargs):
        raise _subprocess.CalledProcessError(
            returncode=1,
            cmd=cmd,
            stderr=b"Error: invalid input file",
        )

    with patch("app.services.mp4_gif_service.subprocess.run", side_effect=_fake_fail):
        error_msg = run_ffmpeg_conversion(input_file, output_file, fps=10)

    assert error_msg is not None
    task.mark_failed(error_msg)
    session.commit()

    reloaded = session.query(Mp4GifTask).filter_by(task_id="t-fail-001").first()
    assert reloaded.status == Mp4GifTask.STATUS_FAILED
    assert reloaded.error_message is not None
    assert len(reloaded.error_message) > 0

    session.close()
    engine.dispose()


# ─── trim 통합 TC (Phase T3, item 20) ───────────────────────────────────────

def test_run_ffmpeg_conversion_with_trim_creates_output(tmp_path):
    """start_seconds=0, duration_seconds=3로 stub ffmpeg를 실행해도 output GIF가 생성된다."""
    from unittest.mock import MagicMock

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"\x00" * 64)
    output_file = tmp_path / "output.gif"

    def _fake_run(cmd, **kwargs):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"GIF89a" + b"\x00" * 16)
        result = MagicMock()
        result.returncode = 0
        result.stderr = b""
        return result

    with patch("app.services.mp4_gif_service.subprocess.run", side_effect=_fake_run):
        error_msg = run_ffmpeg_conversion(input_file, output_file, fps=10, start_seconds=0.0, duration_seconds=3.0)

    assert error_msg is None, f"성공 stub인데 에러: {error_msg}"
    assert output_file.exists(), "GIF 산출물이 생성되지 않았습니다."


def test_build_ffmpeg_command_ss_before_input(tmp_path):
    """-ss 인덱스가 -i보다 앞에 있는지 실제 반환 리스트로 검증한다."""
    cmd = build_ffmpeg_command(tmp_path / "i.mp4", tmp_path / "o.gif", 10, start_seconds=5.0)
    assert "-ss" in cmd
    assert "-i" in cmd
    assert cmd.index("-ss") < cmd.index("-i"), "-ss가 -i보다 앞에 있어야 합니다."


# ─── width 옵션 T3 TC ──────────────────────────────────────────────────────────

def test_run_ffmpeg_conversion_width_creates_output(tmp_path):
    """width=480로 stub ffmpeg를 실행해도 GIF가 생성된다."""
    from unittest.mock import MagicMock

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"\x00" * 64)
    output_file = tmp_path / "output.gif"

    def _fake_run(cmd, **kwargs):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"GIF89a" + b"\x00" * 16)
        result = MagicMock()
        result.returncode = 0
        result.stderr = b""
        return result

    with patch("app.services.mp4_gif_service.subprocess.run", side_effect=_fake_run):
        error_msg = run_ffmpeg_conversion(input_file, output_file, fps=10, width=480)

    assert error_msg is None, f"성공 stub인데 에러: {error_msg}"
    assert output_file.exists()


def test_run_ffmpeg_conversion_trim_creates_output_with_width(tmp_path):
    """width + trim 조합으로 stub ffmpeg를 실행해도 GIF가 생성된다."""
    from unittest.mock import MagicMock

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"\x00" * 64)
    output_file = tmp_path / "output.gif"

    def _fake_run(cmd, **kwargs):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"GIF89a" + b"\x00" * 16)
        result = MagicMock()
        result.returncode = 0
        result.stderr = b""
        return result

    with patch("app.services.mp4_gif_service.subprocess.run", side_effect=_fake_run):
        error_msg = run_ffmpeg_conversion(
            input_file, output_file, fps=8, width=540, start_seconds=2.0, duration_seconds=5.0
        )

    assert error_msg is None
    assert output_file.exists()


# ─── overwrite_mode / download_filename T3 TC ────────────────────────────────

def test_build_download_filename_suffix_roundtrip(tmp_path):
    """suffix 모드의 download_filename 계산이 저장된 파일명과 일치한다."""
    from app.services.mp4_gif_service import build_download_filename

    name = build_download_filename("i2.mp4", fps=6, width=480, overwrite_mode="suffix")
    assert name == "i2_gif_fps6_w480.gif"


def test_build_download_filename_fail_if_exists_default_name(tmp_path):
    """fail_if_exists 모드에서도 다운로드 파일명은 기본(stem.gif)이다."""
    from app.services.mp4_gif_service import build_download_filename

    name = build_download_filename("clip.mp4", fps=10, width=None, overwrite_mode="fail_if_exists")
    assert name == "clip.gif"
