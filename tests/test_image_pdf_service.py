from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
import importlib.util
import re

import pytest
from PIL import Image

from app.schemas.image_pdf import ImagePdfConvertOptions
from app.services import image_pdf_service
from app.services.image_pdf_service import ImagePdfError


def _image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (24, 16), color=(255, 0, 0), **save_kwargs) -> bytes:
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _page_count(pdf_bytes: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))


def test_convert_single_jpg_R():
    pdf = image_pdf_service.convert_images_to_pdf(
        [("a.jpg", _image_bytes())],
        ImagePdfConvertOptions(),
    )
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 1


def test_convert_multiple_order_preserved_R():
    pdf = image_pdf_service.convert_images_to_pdf(
        [
            ("one.jpg", _image_bytes(color=(255, 0, 0))),
            ("two.png", _image_bytes("PNG", color=(0, 255, 0))),
            ("three.webp", _image_bytes("WEBP", color=(0, 0, 255))),
        ],
        ImagePdfConvertOptions(),
    )
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 3


def test_convert_empty_list_E():
    with pytest.raises(ImagePdfError, match="1개 이상"):
        image_pdf_service.convert_images_to_pdf([], ImagePdfConvertOptions())


def test_convert_unsupported_extension_E():
    with pytest.raises(ImagePdfError) as exc:
        image_pdf_service.convert_images_to_pdf([("a.txt", b"hello")], ImagePdfConvertOptions())
    assert exc.value.error == "unsupported_extension"


def test_convert_corrupt_image_E():
    with pytest.raises(ImagePdfError) as exc:
        image_pdf_service.convert_images_to_pdf([("a.jpg", b"not-image")], ImagePdfConvertOptions())
    assert exc.value.error == "corrupt"


def test_exif_orientation_applied_C():
    img = Image.new("RGB", (10, 20), (255, 0, 0))
    exif = img.getexif()
    exif[274] = 6
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())

    opened = image_pdf_service._open_image("rotated.jpg", buf.getvalue())

    assert opened.size == (20, 10)


def test_alpha_composited_white_C():
    img = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    img.putpixel((1, 0), (10, 20, 30, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")

    opened = image_pdf_service._open_image("alpha.png", buf.getvalue())

    assert opened.mode == "RGB"
    assert opened.getpixel((0, 0)) == (255, 255, 255)
    assert opened.getpixel((1, 0)) == (10, 20, 30)


def test_bw_threshold_validation_B():
    with pytest.raises(ValueError, match="white"):
        ImagePdfConvertOptions(bw=True, white=80, black=80)


def test_quality_boundary_B():
    for quality in (1, 100):
        pdf = image_pdf_service.convert_images_to_pdf(
            [("a.jpg", _image_bytes())],
            ImagePdfConvertOptions(quality=quality),
        )
        assert pdf[:4] == b"%PDF"


def test_max_files_exceeded_B():
    files = [
        SimpleNamespace(filename=f"{index}.jpg", size=1)
        for index in range(image_pdf_service.MAX_FILES + 1)
    ]
    with pytest.raises(ImagePdfError) as exc:
        image_pdf_service.validate_uploads(files)
    assert exc.value.status_code == 413
    assert exc.value.error == "too_many_files"


def test_health_returns_supported_extensions_R():
    health = image_pdf_service.image_pdf_health()
    assert {"jpg", "png", "webp"}.issubset(set(health["supported_extensions"]))
    assert health["max_files"] == image_pdf_service.MAX_FILES


def test_health_heic_flag_matches_import_C():
    health = image_pdf_service.image_pdf_health()
    assert health["heic_supported"] is (importlib.util.find_spec("pillow_heif") is not None)
