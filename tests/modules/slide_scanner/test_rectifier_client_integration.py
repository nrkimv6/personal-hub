from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.services.rectifier_client import RectifierClient


def _make_sample_image(path: Path) -> None:
    image = Image.new("RGB", (256, 192), color=(245, 245, 245))
    image.save(path, format="JPEG")


def test_rectifier_client_integration_returns_detect_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not settings.RECTIFIER_ROOT.exists() or not settings.RECTIFIER_PYTHON.exists():
        pytest.skip("real rectifier runtime is not configured")

    image_path = tmp_path / "integration.jpg"
    _make_sample_image(image_path)
    monkeypatch.setattr(settings, "RECTIFIER_DETECT_ENGINE", "dl")

    client = RectifierClient()
    result = client.detect_with_meta(image_path)
    assert len(result["points"]) == 4
    assert result["meta"]["requested_engine"] in {"opencv", "dl"}
    assert result["meta"]["selected_engine"] in {"opencv", "dl"}
