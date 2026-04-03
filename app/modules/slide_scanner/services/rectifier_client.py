"""Client for calling slide-rectifier external CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, TypedDict

from app.modules.slide_scanner.config import settings

LEGACY_CLI_CONTRACT_REASON = "legacy_cli_contract"


class SlideFilterOptions(TypedDict):
    white_balance: bool
    contrast: float
    document_mode: bool


class DetectMeta(TypedDict):
    requested_engine: str
    selected_engine: str
    confidence: float | None
    fallback_reason: str | None
    selection_reason: str | None


class DetectResult(TypedDict):
    points: list[tuple[float, float]]
    meta: DetectMeta


class RectifierClient:
    def _normalize_detect_engine(self, value: str | None) -> str:
        normalized = (value or "opencv").strip().lower()
        if normalized in {"opencv", "dl"}:
            return normalized
        return "opencv"

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

    def _is_with_meta_contract_error(self, error_message: str) -> bool:
        lowered = error_message.lower()
        return "--with-meta" in lowered and (
            "unrecognized arguments" in lowered
            or "unknown option" in lowered
            or "invalid choice" in lowered
        )

    def _parse_points(self, payload: object) -> list[tuple[float, float]]:
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected detect payload type: {type(payload).__name__}")

        points: list[tuple[float, float]] = []
        for item in payload:
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

    def _parse_detect_payload(self, payload: str, requested_engine: str) -> DetectResult:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid detect output: {payload}") from exc

        if isinstance(parsed, list):
            return {
                "points": self._parse_points(parsed),
                "meta": {
                    "requested_engine": requested_engine,
                    "selected_engine": requested_engine,
                    "confidence": None,
                    "fallback_reason": LEGACY_CLI_CONTRACT_REASON,
                    "selection_reason": LEGACY_CLI_CONTRACT_REASON,
                },
            }

        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected detect payload type: {type(parsed).__name__}")

        points = self._parse_points(parsed.get("points"))
        raw_meta = parsed.get("meta")
        if raw_meta is None:
            raw_meta = {}
        if not isinstance(raw_meta, dict):
            raise RuntimeError("Unexpected detect meta payload type")

        confidence: float | None
        raw_confidence = raw_meta.get("confidence")
        if raw_confidence is None:
            confidence = None
        else:
            confidence = float(raw_confidence)

        fallback_reason = raw_meta.get("fallback_reason")
        selection_reason = raw_meta.get("selection_reason")
        selected_engine = self._normalize_detect_engine(
            str(raw_meta.get("selected_engine") or requested_engine)
        )
        normalized_requested = self._normalize_detect_engine(
            str(raw_meta.get("requested_engine") or requested_engine)
        )
        return {
            "points": points,
            "meta": {
                "requested_engine": normalized_requested,
                "selected_engine": selected_engine,
                "confidence": confidence,
                "fallback_reason": str(fallback_reason) if fallback_reason is not None else None,
                "selection_reason": str(selection_reason) if selection_reason is not None else None,
            },
        }

    def detect_with_meta(self, image_path: Path) -> DetectResult:
        engine = self._normalize_detect_engine(settings.RECTIFIER_DETECT_ENGINE)
        with_meta_args = ["detect", str(image_path), "--engine", engine, "--with-meta"]
        try:
            payload = self._run(with_meta_args)
            return self._parse_detect_payload(payload, requested_engine=engine)
        except RuntimeError as exc:
            if not self._is_with_meta_contract_error(str(exc)):
                raise

        legacy_payload = self._run(["detect", str(image_path), "--engine", engine])
        result = self._parse_detect_payload(legacy_payload, requested_engine=engine)
        result["meta"]["fallback_reason"] = LEGACY_CLI_CONTRACT_REASON
        if not result["meta"]["selection_reason"]:
            result["meta"]["selection_reason"] = LEGACY_CLI_CONTRACT_REASON
        return result

    def detect(self, image_path: Path) -> list[tuple[float, float]]:
        return self.detect_with_meta(image_path)["points"]

    def transform(
        self,
        image_path: Path,
        points: list[tuple[float, float]],
        output_path: Path,
        aspect_ratio: str | None = None,
        filters: SlideFilterOptions | None = None,
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

        normalized_filters = self._normalize_filters(filters)
        if normalized_filters:
            path = self.filter_image(
                image_path=path,
                output_path=path,
                filters=normalized_filters,
            )
        return path

    def _normalize_filters(self, filters: SlideFilterOptions | None) -> SlideFilterOptions | None:
        if not filters:
            return None

        contrast = float(filters.get("contrast", 1.0))
        if contrast < 0.5 or contrast > 2.0:
            raise RuntimeError("contrast must be between 0.5 and 2.0")

        normalized: SlideFilterOptions = {
            "white_balance": bool(filters.get("white_balance", False)),
            "contrast": contrast,
            "document_mode": bool(filters.get("document_mode", False)),
        }
        if (
            not normalized["white_balance"]
            and not normalized["document_mode"]
            and abs(normalized["contrast"] - 1.0) < 1e-6
        ):
            return None
        return normalized

    def filter_image(
        self,
        image_path: Path,
        output_path: Path,
        filters: SlideFilterOptions,
    ) -> Path:
        args = ["filter", str(image_path), str(output_path)]
        if filters["white_balance"]:
            args.append("--white-balance")
        args.extend(["--contrast", str(filters["contrast"])])
        if filters["document_mode"]:
            args.append("--document-mode")

        output = self._run(args)
        path = Path(output)
        if not path.exists():
            raise RuntimeError(f"Filter output not found: {path}")
        return path

    def export_pdf(
        self,
        image_paths: list[Path],
        output_path: Path,
    ) -> Path:
        if not image_paths:
            raise RuntimeError("At least one image path is required for PDF export")

        args = ["pdf", str(output_path), *[str(path) for path in image_paths]]
        output = self._run(args)
        path = Path(output)
        if not path.exists():
            raise RuntimeError(f"PDF output not found: {path}")
        return path

    def extract_text(
        self,
        image_path: Path,
        languages: list[str] | None = None,
    ) -> str:
        args = ["ocr", str(image_path)]
        if languages:
            normalized = [lang.strip() for lang in languages if lang and lang.strip()]
            if normalized:
                args.extend(["--lang", ",".join(normalized)])
        return self._run(args)


rectifier_client = RectifierClient()
