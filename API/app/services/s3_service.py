"""
app/services/s3_service.py
---------------------------
AWS S3 integration for drone condition image uploads.
All uploaded files are stored under the `drone-images/` prefix.
Public read access is granted via pre-signed URLs or public bucket policy.
"""

import logging
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
ALLOWED_VIDEO_CONTENT_TYPES = {"video/mp4", "video/quicktime", "video/x-m4v"}
MAX_FILE_SIZE_MB = 20
MAX_VIDEO_FILE_SIZE_MB = 250

# Magic-byte signatures used to verify the actual file type regardless of the
# client-supplied Content-Type header (which is fully attacker-controlled).
_IMAGE_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff",       "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    # WebP: RIFF....WEBP
    (b"RIFF",               "image/webp"),   # confirmed by bytes[8:12] == b"WEBP" below
    # HEIC/HEIF: ftyp box at offset 4
    # We accept them if the header matches "ftypheic", "ftypheis", "ftypmif1", "ftypmsf1"
]
_HEIC_FTYP_BRANDS = {b"heic", b"heis", b"mif1", b"msf1", b"heix", b"hevc"}
_VIDEO_MAGIC: list[tuple[bytes, str]] = [
    (b"\x00\x00\x00", "video/mp4"),       # 4-byte big-endian box size + "ftyp"
    (b"ftyp",         "video/mp4"),
]


def _detect_image_type(data: bytes) -> str | None:
    """Return the detected MIME type from magic bytes, or None if unrecognised."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # HEIC/HEIF: ftyp box. The box size is a big-endian uint32 at offset 0.
    # The brand (4 bytes) is at offset 8.
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12].lower() in _HEIC_FTYP_BRANDS:
        return "image/heic"
    return None


def _detect_video_type(data: bytes) -> str | None:
    """Return the detected video MIME type from magic bytes, or None if unrecognised."""
    if len(data) < 12:
        return None
    # ISO base media file format (MP4/MOV/M4V): big-endian box size + "ftyp"
    box_type = data[4:8]
    if box_type == b"ftyp":
        brand = data[8:12]
        # Common brands for accepted formats
        mp4_brands  = {b"mp41", b"mp42", b"isom", b"iso2", b"avc1", b"M4V ", b"M4A ", b"f4v "}
        qt_brands   = {b"qt  "}                        # QuickTime .mov
        if brand in mp4_brands:
            return "video/mp4"
        if brand in qt_brands:
            return "video/quicktime"
        # Accept any ftyp-boxed file as mp4 to cover edge cases (M4V etc.)
        return "video/mp4"
    return None


def _get_s3_client():
    access_key_id, secret_access_key, _bucket = _require_s3_settings()
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def _require_s3_settings() -> tuple[str, str, str]:
    try:
        return settings.require_s3_settings()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )


def _build_public_url(key: str) -> str:
    """Construct the public S3 URL for a given object key."""
    _access_key_id, _secret_access_key, bucket = _require_s3_settings()
    return f"https://{bucket}.s3.{settings.aws_region}.amazonaws.com/{key}"


async def upload_images(files: list[UploadFile], folder: str) -> list[str]:
    """
    Upload a list of image files to S3.

    Args:
        files:  List of FastAPI UploadFile objects.
        folder: S3 key prefix, e.g. "drone-images/pre-rental/<booking_id>"

    Returns:
        List of public S3 URLs for the uploaded files.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided.",
        )

    s3 = _get_s3_client()
    uploaded_urls: list[str] = []

    for file in files:
        # Read content first so we can inspect magic bytes.
        contents = await file.read()

        # Validate file size before expensive operations.
        size_mb = len(contents) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File '{file.filename}' exceeds the {MAX_FILE_SIZE_MB}MB limit.",
            )

        # Validate MIME type via magic bytes — do NOT trust client-supplied Content-Type.
        detected_type = _detect_image_type(contents)
        if detected_type is None or detected_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported file type. Allowed: JPEG, PNG, WEBP, HEIC.",
            )
        # Use the server-detected content type for the S3 object, not the client header.
        safe_content_type = detected_type

        # Build a unique S3 key using only the detected extension — ignore client filename.
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png":  ".png",
            "image/webp": ".webp",
            "image/heic": ".heic",
            "image/heif": ".heif",
        }
        extension = ext_map.get(detected_type, ".jpg")
        unique_filename = f"{uuid.uuid4()}{extension}"
        s3_key = f"{folder}/{unique_filename}"

        try:
            s3.put_object(
                Bucket=_require_s3_settings()[2],
                Key=s3_key,
                Body=contents,
                ContentType=safe_content_type,
            )
            url = _build_public_url(s3_key)
            uploaded_urls.append(url)
            logger.info("Uploaded image to S3: %s", s3_key)
        except (BotoCoreError, ClientError) as e:
            logger.error("S3 upload failed for key %s: %s", s3_key, str(e))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to upload image to storage. Please try again.",
            )

    return uploaded_urls


async def upload_image_bytes(image_bytes: bytes, content_type: str = "image/jpeg", prefix: str = "drone-images") -> str:
    """Upload raw image bytes after server-side MIME validation. Returns the public URL."""
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds the {MAX_FILE_SIZE_MB}MB limit.",
        )

    detected_type = _detect_image_type(image_bytes)
    if detected_type is None or detected_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Allowed: JPEG, PNG, WEBP, HEIC.",
        )

    s3 = _get_s3_client()
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }
    unique_filename = f"{uuid.uuid4()}{ext_map.get(detected_type, '.jpg')}"
    s3_key = f"{prefix}/{unique_filename}"
    try:
        s3.put_object(
            Bucket=_require_s3_settings()[2],
            Key=s3_key,
            Body=image_bytes,
            ContentType=detected_type,
        )
        url = _build_public_url(s3_key)
        logger.info("Uploaded image bytes to S3: %s", s3_key)
        return url
    except (BotoCoreError, ClientError) as e:
        logger.error("S3 upload_image_bytes failed for key %s: %s", s3_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload image to storage.",
        )


async def upload_video(file: UploadFile, folder: str) -> str:
    """
    Upload a single return video to S3.
    File type is validated via magic bytes — client Content-Type header is ignored.
    """
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_VIDEO_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File '{file.filename}' exceeds the {MAX_VIDEO_FILE_SIZE_MB}MB limit.",
        )

    detected_type = _detect_video_type(contents)
    if detected_type is None or detected_type not in ALLOWED_VIDEO_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported video type. Allowed: MP4, MOV, M4V.",
        )
    safe_content_type = detected_type
    ext_map = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-m4v": ".m4v"}
    extension = ext_map.get(detected_type, ".mp4")
    s3_key = f"{folder}/{uuid.uuid4()}{extension}"

    try:
        _get_s3_client().put_object(
            Bucket=_require_s3_settings()[2],
            Key=s3_key,
            Body=contents,
            ContentType=safe_content_type,
        )
    except (BotoCoreError, ClientError) as e:
        logger.error("S3 video upload failed for key %s: %s", s3_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload video to storage. Please try again.",
        )

    logger.info("Uploaded return video to S3: %s", s3_key)
    return _build_public_url(s3_key)
