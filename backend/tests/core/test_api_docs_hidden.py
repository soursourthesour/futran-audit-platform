"""Go-live gap: the internal API reference (/api/docs, /api/openapi.json) listed every operation without sign-in.
Outside test mode it is not served; the public API's own reference stays available for client tools."""
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _client(engine, **live):
    s = Settings(database_url="sqlite://", secret_key="test-secret-key-not-for-production-0123456789", disable_scheduler=True, seed_on_start=False, **live)
    return TestClient(create_app(s, engine=engine))


def test_internal_api_reference_is_hidden_outside_test_mode(engine):
    with _client(engine, mfa_required=True, email_mode="smtp") as c:
        assert c.get("/api/docs").status_code == 404
        assert c.get("/api/openapi.json").status_code == 404
        assert c.get("/api/public/v1/openapi.json").status_code == 200


def test_internal_api_reference_is_served_in_test_mode(engine):
    with _client(engine, mfa_required=False, email_mode="outbox") as c:
        assert c.get("/api/openapi.json").status_code == 200
