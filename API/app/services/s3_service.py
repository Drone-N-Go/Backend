"""
app/services/s3_service.py
---------------------------
AWS S3 integration for drone condition image uploads.
All uploaded files are stored under the `drone-images/` prefix.
Public read access is granted via pre-signed URLs or public bucket policy.
"""

import logging
import uuid
from pathlib import Path

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
        # Validate MIME type
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type: {file.content_type}. Allowed: JPEG, PNG, WEBP, HEIC.",
            )

        # Read content
        contents = await file.read()

        # Validate file size
        size_mb = len(contents) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File '{file.filename}' exceeds the {MAX_FILE_SIZE_MB}MB limit.",
            )

        # Build a unique S3 key
        extension = Path(file.filename).suffix.lower() if file.filename else ".jpg"
        unique_filename = f"{uuid.uuid4()}{extension}"
        s3_key = f"{folder}/{unique_filename}"

        try:
            s3.put_object(
                Bucket=_require_s3_settings()[2],
                Key=s3_key,
                Body=contents,
                ContentType=file.content_type,
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
    """Upload raw image bytes (e.g. from base64 decode) to S3. Returns the public URL."""
    s3 = _get_s3_client()
    unique_filename = f"{uuid.uuid4()}.jpg"
    s3_key = f"{prefix}/{unique_filename}"
    try:
        s3.put_object(
            Bucket=_require_s3_settings()[2],
            Key=s3_key,
            Body=image_bytes,
            ContentType=content_type,
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
    """
    if file.content_type not in ALLOWED_VIDEO_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported video type. Allowed: MP4, MOV, M4V.",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_VIDEO_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File '{file.filename}' exceeds the {MAX_VIDEO_FILE_SIZE_MB}MB limit.",
        )

    extension = Path(file.filename).suffix.lower() if file.filename else ".mp4"
    s3_key = f"{folder}/{uuid.uuid4()}{extension}"

    try:
        _get_s3_client().put_object(
            Bucket=_require_s3_settings()[2],
            Key=s3_key,
            Body=contents,
            ContentType=file.content_type,
        )
    except (BotoCoreError, ClientError) as e:
        logger.error("S3 video upload failed for key %s: %s", s3_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload video to storage. Please try again.",
        )

    logger.info("Uploaded return video to S3: %s", s3_key)
    return _build_public_url(s3_key)
