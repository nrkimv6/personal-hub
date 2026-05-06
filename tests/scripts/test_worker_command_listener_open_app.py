import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "services" / "worker-command-listener.py"


def _load_listener():
    spec = importlib.util.spec_from_file_location("worker_command_listener_open_app", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_execute_open_app_right_explorer_select(tmp_path):
    listener = _load_listener()
    target = tmp_path / "sample.png"
    target.write_text("x")

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = listener.execute_open_app({"app_name": "explorer", "args": ["/select,", str(target)]})

    assert result["success"] is True
    assert mock_popen.call_args.args[0] == ["explorer", "/select,", str(target)]


def test_execute_open_app_boundary_code_goto_option(tmp_path):
    listener = _load_listener()
    target = tmp_path / "sample.py"
    target.write_text("print('x')")

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = listener.execute_open_app({"app_name": "code", "args": ["--goto", f"{target}:7"]})

    assert result["success"] is True
    assert mock_popen.call_args.args[0] == ["code", "--goto", f"{target}:7"]


def test_execute_open_app_error_rejects_relative_path():
    listener = _load_listener()

    with patch("subprocess.Popen") as mock_popen:
        result = listener.execute_open_app({"app_name": "explorer", "args": ["relative\\file.txt"]})

    assert result["success"] is False
    assert "absolute" in result["message"]
    mock_popen.assert_not_called()
