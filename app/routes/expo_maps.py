"""Expo 배치도 이미지 업로드/조회 API.

admin write: POST /api/v1/expo/maps/{slug}/upload
admin delete: DELETE /api/v1/expo/maps/{slug}
public read:  GET  /api/v1/expo/maps/{slug}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse as _FileResponse

from app.core.auth import UserInfo, get_current_user_required
from app.core.config import settings
from app.schemas.expo import ExpoMapMetaResponse, ExpoMapUploadResponse

router = APIRouter(prefix="/api/v1/expo/maps", tags=["expo-maps"])

# 허용 slug 목록 (신규 expo 추가 시 확장)
ALLOWED_SLUGS: frozenset[str] = frozenset({"coffee-expo-2026"})

# 허용 MIME 타입 & 확장자
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/webp"})
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})

# 업로드 파일 최대 크기: 20 MB
MAX_FILE_BYTES = 20 * 1024 * 1024

# 저장 루트: {settings.DATA_DIR}/expo/{slug}/ — ExpoService._export_record_path()와 동일 기준
DATA_ROOT = Path(settings.DATA_DIR) / "expo"

# 공개 이미지 URL prefix — /api/v1/expo/maps/{slug}/image 엔드포인트로 서빙
# 프론트엔드 vite proxy가 /api → API 서버로 중계하므로 /data 직접 서빙 불필요
_IMAGE_ENDPOINT_PREFIX = "/api/v1/expo/maps"


def _slug_dir(slug: str) -> Path:
    return DATA_ROOT / slug


def _meta_path(slug: str) -> Path:
    return _slug_dir(slug) / "map_meta.json"


def _load_meta(slug: str) -> dict | None:
    path = _meta_path(slug)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_meta(slug: str, meta: dict) -> None:
    path = _meta_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _delete_meta(slug: str) -> None:
    path = _meta_path(slug)
    if path.exists():
        path.unlink()


def _image_dimensions(data: bytes, content_type: str) -> tuple[int, int]:
    """업로드된 이미지의 (width, height)를 반환한다. 실패 시 (0, 0)."""
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(data))
        return img.width, img.height
    except Exception:
        return 0, 0


async def _require_authenticated_admin(
    user: UserInfo = Depends(get_current_user_required),
) -> UserInfo:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user


@router.get("/{slug}", response_model=ExpoMapMetaResponse)
async def get_expo_map_meta(slug: str) -> ExpoMapMetaResponse:
    """배치도 업로드 override 메타데이터를 조회한다. 인증 불필요 (public)."""
    if slug not in ALLOWED_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expo slug '{slug}'이(가) 존재하지 않습니다.",
        )

    meta = _load_meta(slug)
    if not meta or not meta.get("image_url"):
        # override 없음 — null 응답 반환
        return ExpoMapMetaResponse(slug=slug)

    return ExpoMapMetaResponse(
        slug=slug,
        image_url=meta.get("image_url"),
        width=meta.get("width"),
        height=meta.get("height"),
        title=meta.get("title"),
        alt=meta.get("alt"),
        uploaded_at=meta.get("uploaded_at"),
    )


@router.post("/{slug}/upload", response_model=ExpoMapUploadResponse)
async def upload_expo_map(
    slug: str,
    file: UploadFile = File(...),
    _: UserInfo = Depends(_require_authenticated_admin),
) -> ExpoMapUploadResponse:
    """배치도 이미지를 업로드한다. admin 전용."""
    if slug not in ALLOWED_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expo slug '{slug}'이(가) 존재하지 않습니다.",
        )

    # content-type 검증
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"지원하지 않는 파일 형식입니다: {content_type}. "
                   f"허용: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
        )

    # 확장자 검증
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"허용되지 않는 확장자입니다: {suffix}. "
                   f"허용: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 파일 데이터 읽기 + 크기 검증
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"파일 크기가 {MAX_FILE_BYTES // (1024 * 1024)} MB를 초과합니다.",
        )

    # 이미지 dimension 추출
    width, height = _image_dimensions(data, content_type)

    # 기존 이미지 파일 정리
    slug_dir = _slug_dir(slug)
    slug_dir.mkdir(parents=True, exist_ok=True)
    for ext in ALLOWED_EXTENSIONS:
        old_file = slug_dir / f"map{ext}"
        if old_file.exists():
            old_file.unlink()

    # 새 파일 저장
    dest = slug_dir / f"map{suffix}"
    dest.write_bytes(data)

    # public URL — /api/v1/expo/maps/{slug}/image 엔드포인트로 서빙 (vite proxy → API 서버)
    image_url = f"{_IMAGE_ENDPOINT_PREFIX}/{slug}/image"
    uploaded_at = datetime.now(tz=timezone.utc).isoformat()

    # 메타 JSON 저장
    _save_meta(
        slug,
        {
            "slug": slug,
            "image_url": image_url,
            "width": width,
            "height": height,
            "title": None,
            "alt": None,
            "uploaded_at": uploaded_at,
        },
    )

    return ExpoMapUploadResponse(
        slug=slug,
        image_url=image_url,
        width=width,
        height=height,
        uploaded_at=datetime.fromisoformat(uploaded_at),
    )


@router.get("/{slug}/image", response_class=_FileResponse)
async def serve_expo_map_image(slug: str) -> _FileResponse:
    """업로드된 배치도 이미지를 서빙한다. 인증 불필요 (public). 없으면 404."""
    if slug not in ALLOWED_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expo slug '{slug}'이(가) 존재하지 않습니다.",
        )

    slug_dir = _slug_dir(slug)
    for ext in ALLOWED_EXTENSIONS:
        candidate = slug_dir / f"map{ext}"
        if candidate.exists():
            media_type_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }
            return _FileResponse(
                path=str(candidate),
                media_type=media_type_map.get(ext, "application/octet-stream"),
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="업로드된 배치도 이미지가 없습니다.",
    )


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_expo_map_override(
    slug: str,
    _: UserInfo = Depends(_require_authenticated_admin),
) -> Response:
    """배치도 업로드 override를 삭제한다. admin 전용. 이후 public은 static fallback으로 복원."""
    if slug not in ALLOWED_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expo slug '{slug}'이(가) 존재하지 않습니다.",
        )

    slug_dir = _slug_dir(slug)
    for ext in ALLOWED_EXTENSIONS:
        old_file = slug_dir / f"map{ext}"
        if old_file.exists():
            old_file.unlink()

    _delete_meta(slug)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
