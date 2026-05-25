"""HTTP route paths for v1 orchestrator API."""

from fastapi.testclient import TestClient

from app.main import app


def test_v1_orchestrator_answer_default_sse():
    client = TestClient(app)
    response = client.post(
        "/v1/orchestrator/answer",
        json={"question": "hello"},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code != 404
    assert "text/event-stream" in (response.headers.get("content-type") or "")


def test_v1_orchestrator_answer_stream_false_json():
    client = TestClient(app)
    response = client.post(
        "/v1/orchestrator/answer",
        json={"question": "hello", "stream": False},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code != 404
    assert "application/json" in (response.headers.get("content-type") or "")


def test_v1_orchestrator_eval_router_exists():
    client = TestClient(app)
    response = client.post(
        "/v1/orchestrator/eval/router",
        json={"question": "hello"},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code != 404


def test_v1_feedback_returns_sse():
    client = TestClient(app)
    response = client.post(
        "/v1/feedback",
        json={"rating": "thumbs_up"},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in (response.headers.get("content-type") or "")
    assert '"type": "done"' in response.text


def test_legacy_orchestrator_answer_not_found():
    client = TestClient(app)
    response = client.post(
        "/orchestrator/answer",
        json={"question": "hello", "stream": False},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code == 404


def test_legacy_eval_router_not_found():
    client = TestClient(app)
    response = client.post(
        "/orchestrator/eval/router",
        json={"question": "hello"},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code == 404


def test_legacy_feedback_not_found():
    client = TestClient(app)
    response = client.post(
        "/feedback",
        json={"rating": 1},
        headers={"X-Request-Id": "test-req"},
    )
    assert response.status_code == 404
