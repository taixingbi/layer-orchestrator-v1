"""HTTP route paths for v1 orchestrator answer."""

from fastapi.testclient import TestClient

from app.main import app


def test_v1_orchestrator_answer_exists():
    client = TestClient(app)
    response = client.post(
        "/v1/orchestrator/answer",
        json={"question": "hello", "stream": False},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code != 404


def test_legacy_orchestrator_answer_not_found():
    client = TestClient(app)
    response = client.post(
        "/orchestrator/answer",
        json={"question": "hello", "stream": False},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code == 404
