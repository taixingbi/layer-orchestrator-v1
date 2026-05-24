"""GET /version."""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_version_returns_version_id():
    client = TestClient(app)
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version_id": settings.app_version}
