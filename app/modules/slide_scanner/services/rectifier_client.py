"""Client for calling slide-rectifier external CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.modules.slide_scanner.config import settings


class RectifierClient:
    def _run(self, args: list[str]) -> str:
        if not settings.RECTIFIER_PYTHON.exists():
            raise RuntimeError(f"Rectifier python not found: {settings.RECTIFIER_PYTHON}")
        if not settings.RECTIFIER_ROOT.exists():
            raise RuntimeError(f"Rectifier root not found: {settings.RECTIFIER_ROOT}")

        command = [str(settings.RECTIFIER_PYTHON), "-m", "slide_rectifier", *args]
        result = subprocess.run(
            command,
            cwd=str(settings.RECTIFIER_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or "unknown error"
            raise RuntimeError(f"slide_rectifier failed: {stderr}")
        return result.stdout.strip()

    def detect(self, image_path: Path) -> list[tuple[float, float]]:
        payload = self._run(["detect", str(image_path)])
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid detect output: {payload}") from exc

        if not isinstance(parsed, list):
            raise RuntimeError(f"Unexpected detect payload type: {type(parsed).__name__}")

        points: list[tuple[float, float]] = []
        for item in parsed:
            if isinstance(item, dict) and "x" in item and "y" in item:
                points.append((float(item["x"]), float(item["y"])))
                continue
            if isinstance(item, list) and len(item) == 2:
                points.append((float(item[0]), float(item[1])))
                continue
            raise RuntimeError(f"Unsupported point payload: {item!r}")

        if len(points) != 4:
            raise RuntimeError(f"Detect should return 4 points, got {len(points)}")
        return points

    def transform(
        self,
        image_path: Path,
        points: list[tuple[float, float]],
        output_path: Path,
        aspect_ratio: str | None = None,
    ) -> Path:
        points_payload = [{"x": float(x), "y": float(y)} for x, y in points]
        args = [
            "transform",
            str(image_path),
            json.dumps(points_payload, ensure_ascii=False),
            str(output_path),
        ]
        if aspect_ratio:
            args.extend(["--aspect-ratio", aspect_ratio])

        output = self._run(args)
        path = Path(output)
        if not path.exists():
            raise RuntimeError(f"Transform output not found: {path}")
        return path


rectifier_client = RectifierClient()
