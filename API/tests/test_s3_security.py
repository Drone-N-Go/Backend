import os
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch

from fastapi import HTTPException

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/dronengo_test")
os.environ.setdefault("SECRET_KEY", "x" * 64)

from app.services import s3_service


class S3SecurityTests(IsolatedAsyncioTestCase):
    async def test_upload_image_bytes_rejects_non_image_payload(self):
        with patch.object(s3_service, "_get_s3_client") as get_client:
            with self.assertRaises(HTTPException) as raised:
                await s3_service.upload_image_bytes(
                    b"<html><script>alert(1)</script></html>",
                    content_type="image/jpeg",
                    prefix="drone-intake/test-drone",
                )

        self.assertEqual(raised.exception.status_code, 415)
        get_client.assert_not_called()

    async def test_upload_image_bytes_uses_detected_content_type(self):
        client = Mock()
        with (
            patch.object(s3_service, "_get_s3_client", return_value=client),
            patch.object(s3_service, "_require_s3_settings", return_value=("access", "secret", "bucket")),
            patch.object(s3_service, "_build_public_url", return_value="https://cdn.example/test.jpg"),
        ):
            url = await s3_service.upload_image_bytes(
                b"\xff\xd8\xff\xe0" + b"\x00" * 32,
                content_type="text/html",
                prefix="drone-intake/test-drone",
            )

        self.assertEqual(url, "https://cdn.example/test.jpg")
        _, kwargs = client.put_object.call_args
        self.assertEqual(kwargs["ContentType"], "image/jpeg")
