"""
app/services/firebase_service.py
---------------------------------
Google Firebase (Cloud Storage) integration for drone condition image uploads.
Replaces the former S3-based app/services/s3_service.py — same validation
rules, same function signatures, same public-URL return shape, so callers
did not need to change beyond their import line.

All uploaded files are stored under the `drone-images/` prefix (or whatever
folder/prefix the caller passes). Files are made public on upload, matching
the previous S3 bucket's public-read behavior.
"""

import base64
import json
import logging
import uuid

import firebase_admin
from firebase_admin import credentials, storage
from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
ALLOWED_VIDEO_CONTENT_TYPES = {"video/mp4", "video/quicktime", "video/x-m4v"}
MAX_FILE_SIZE_MB = 20
MAX_VIDEO_FILE_SIZE_MB = 250

_HEIC_FTYP_BRANDS = {b"heic", b"heis", b"mif1", b"msf1", b"heix", b"hevc"}

_firebase_app = None  # lazily-initialized firebase_admin App singleton


def _detect_image_type(data: bytes) -> str | None:
    """Return the detected MIME type from magic bytes, or None if unrecognised."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12].lower() in _HEIC_FTYP_BRANDS:
        return "image/heic"
    return None


def _detect_video_type(data: bytes) -> str | None:
    """Return the detected video MIME type from magic bytes, or None if unrecognised."""
    if len(data) < 12:
        return None
    box_type = data[4:8]
    if box_type == b"ftyp":
        brand = data[8:12]
        mp4_brands = {b"mp41", b"mp42", b"isom", b"iso2", b"avc1", b"M4V ", b"M4A ", b"f4v "}
        qt_brands = {b"qt  "}
        if brand in mp4_brands:
            return "video/mp4"
        if brand in qt_brands:
            return "video/quicktime"
        return "video/mp4"
    return None


def _require_firebase_settings() -> tuple[str, str]:
    try:
        return settings.require_firebase_settings()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )


def _get_bucket():
    """Return the Firebase Storage bucket, initializing the Admin SDK app once."""
    global _firebase_app
    creds_b64, bucket_name = _require_firebase_settings()
    if _firebase_app is None:
        try:
            cred_json = json.loads(base64.b64decode(creds_b64))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FIREBASE_CREDENTIALS_JSON is not valid base64-encoded JSON.",
            ) from exc
        cred = credentials.Certificate(cred_json)
        _firebase_app = firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
    return storage.bucket(app=_firebase_app)


def _upload_and_publish(bucket, key: str, data: bytes, content_type: str) -> str:
    # NOTE: does not call blob.make_public() — that uses the legacy per-object ACL API,
    # which is rejected with a 400 when the bucket has Uniform bucket-level access enabled
    # (the default for new buckets). Public read access is instead granted once at the
    # bucket level via IAM (allUsers -> Storage Object Viewer), so every object under this
    # bucket is already publicly readable and blob.public_url just needs to be constructed.
    blob = bucket.blob(key)
    blob.upload_from_string(data, content_type=content_type)
    return blob.public_url


async def upload_images(files: list[UploadFile], folder: str) -> list[str]:
    """
    Upload a list of image files to Firebase Storage.

    Args:
        files:  List of FastAPI UploadFile objects.
        folder: Storage key prefix, e.g. "drone-images/pre-rental/<booking_id>"

    Returns:
        List of public Firebase Storage URLs for the uploaded files.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided.",
        )

    bucket = _get_bucket()
    uploaded_urls: list[str] = []

    for file in files:
        contents = await file.read()

        size_mb = len(contents) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File '{file.filename}' exceeds the {MAX_FILE_SIZE_MB}MB limit.",
            )

        detected_type = _detect_image_type(contents)
        if detected_type is None or detected_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported file type. Allowed: JPEG, PNG, WEBP, HEIC.",
            )
        safe_content_type = detected_type

        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/heic": ".heic",
            "image/heif": ".heif",
        }
        extension = ext_map.get(detected_type, ".jpg")
        unique_filename = f"{uuid.uuid4()}{extension}"
        object_key = f"{folder}/{unique_filename}"

        try:
            url = _upload_and_publish(bucket, object_key, contents, safe_content_type)
            uploaded_urls.append(url)
            logger.info("Uploaded image to Firebase Storage: %s", object_key)
        except Exception as e:
            logger.error("Firebase upload failed for key %s: %s", object_key, str(e))
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

    bucket = _get_bucket()
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }
    unique_filename = f"{uuid.uuid4()}{ext_map.get(detected_type, '.jpg')}"
    object_key = f"{prefix}/{unique_filename}"
    try:
        url = _upload_and_publish(bucket, object_key, image_bytes, detected_type)
        logger.info("Uploaded image bytes to Firebase Storage: %s", object_key)
        return url
    except Exception as e:
        logger.error("Firebase upload_image_bytes failed for key %s: %s", object_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            # TEMPORARY: real exception text included for diagnosis — revert to generic message once fixed.
            detail=f"Failed to upload image to storage: {type(e).__name__}: {e}",
        )


async def upload_video(file: UploadFile, folder: str) -> str:
    """
    Upload a single return video to Firebase Storage.
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
    object_key = f"{folder}/{uuid.uuid4()}{extension}"

    try:
        bucket = _get_bucket()
        url = _upload_and_publish(bucket, object_key, contents, safe_content_type)
    except Exception as e:
        logger.error("Firebase video upload failed for key %s: %s", object_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload video to storage. Please try again.",
        )

    logger.info("Uploaded return video to Firebase Storage: %s", object_key)
    return url
