import base64
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.models.smiota_event import SmiotaEvent
from app.schemas.webhook import SmiotaWebhookRequest
from app.services import webhook_service


class RequestStub:
    def __init__(self, authorization: str | None):
        self.headers = {}
        if authorization is not None:
            self.headers["Authorization"] = authorization


def basic_auth_header(credentials: str) -> str:
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


class SmiotaWebhookSchemaTests(TestCase):
    def test_tracking_id_is_accepted_and_preserved_in_payload(self):
        body = SmiotaWebhookRequest(
            notification_type="PackageDeposited",
            objectId="smiota-obj-abc123",
            lockerName="Locker-A3",
            passcode="849201",
            courierCode="COUR-XYZ",
            trackingID="TRK-9876543210",
        )

        self.assertEqual(body.trackingID, "TRK-9876543210")
        self.assertEqual(body.model_dump()["trackingID"], "TRK-9876543210")

    def test_tracking_id_is_optional(self):
        body = SmiotaWebhookRequest(
            notification_type="PackagePickedUp",
            objectId="smiota-obj-abc123",
        )

        self.assertIsNone(body.trackingID)

    def test_event_model_has_tracking_id_audit_field(self):
        event = SmiotaEvent(
            notification_type="PackageDeposited",
            object_id="smiota-obj-abc123",
            tracking_id="TRK-9876543210",
            raw_payload={"trackingID": "TRK-9876543210"},
            processed=False,
        )

        self.assertEqual(event.tracking_id, "TRK-9876543210")
        self.assertEqual(event.raw_payload["trackingID"], "TRK-9876543210")

    def test_event_model_tracks_processing_status_and_error_message(self):
        event = SmiotaEvent(
            notification_type="PackageDeposited",
            object_id="smiota-obj-abc123",
            raw_payload={"objectId": "smiota-obj-abc123"},
            processed=False,
            processing_status="failed",
            error_message="Invalid API key.",
        )

        self.assertEqual(event.processing_status, "failed")
        self.assertEqual(event.error_message, "Invalid API key.")


class SmiotaBasicAuthTests(TestCase):
    def assert_unauthorized(self, authorization: str | None):
        with self.assertRaises(HTTPException) as raised:
            webhook_service.verify_smiota_auth(RequestStub(authorization))

        self.assertEqual(raised.exception.status_code, 401)

    def test_accepts_api_key_username_with_empty_password(self):
        with patch.object(webhook_service.settings, "smiota_api_key", "correct-api-key"):
            webhook_service.verify_smiota_auth(RequestStub(basic_auth_header("correct-api-key:")))

    def test_rejects_missing_authorization(self):
        self.assert_unauthorized(None)

    def test_rejects_non_basic_authorization(self):
        self.assert_unauthorized("Bearer token")

    def test_rejects_invalid_base64(self):
        self.assert_unauthorized("Basic not-base64!!!")

    def test_rejects_missing_colon(self):
        with patch.object(webhook_service.settings, "smiota_api_key", "correct-api-key"):
            self.assert_unauthorized(basic_auth_header("correct-api-key"))

    def test_rejects_non_empty_password(self):
        with patch.object(webhook_service.settings, "smiota_api_key", "correct-api-key"):
            self.assert_unauthorized(basic_auth_header("correct-api-key:any-password"))

    def test_rejects_wrong_api_key(self):
        with patch.object(webhook_service.settings, "smiota_api_key", "correct-api-key"):
            self.assert_unauthorized(basic_auth_header("wrong-key:"))


class FakeAuditSession:
    def __init__(self):
        self.added = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, event):
        self.added.append(event)

    async def commit(self):
        self.committed = True


class SmiotaWebhookAuditTests(IsolatedAsyncioTestCase):
    async def test_failure_audit_uses_independent_session_and_commits(self):
        audit_session = FakeAuditSession()

        with patch.object(webhook_service, "AsyncSessionLocal", return_value=audit_session):
            await webhook_service.record_smiota_webhook_failure(
                {
                    "notification_type": "PackageDeposited",
                    "objectId": "smiota-obj-abc123",
                    "lockerName": "Locker-A3",
                    "trackingID": "TRK-9876543210",
                },
                status_value="auth_failed",
                error_message="Invalid API key.",
            )

        self.assertTrue(audit_session.committed)
        self.assertEqual(len(audit_session.added), 1)
        event = audit_session.added[0]
        self.assertEqual(event.notification_type, "PackageDeposited")
        self.assertEqual(event.object_id, "smiota-obj-abc123")
        self.assertEqual(event.processing_status, "auth_failed")
        self.assertEqual(event.error_message, "Invalid API key.")

    async def test_failure_audit_preserves_malformed_payload_as_visible_row(self):
        audit_session = FakeAuditSession()

        with patch.object(webhook_service, "AsyncSessionLocal", return_value=audit_session):
            await webhook_service.record_smiota_webhook_failure(
                {"payload": ["not", "a", "smiota", "object"]},
                status_value="failed",
                error_message="Invalid webhook payload.",
            )

        event = audit_session.added[0]
        self.assertEqual(event.notification_type, "InvalidWebhook")
        self.assertEqual(event.object_id, "unknown")
        self.assertEqual(event.processing_status, "failed")
        self.assertEqual(event.raw_payload, {"payload": ["not", "a", "smiota", "object"]})
