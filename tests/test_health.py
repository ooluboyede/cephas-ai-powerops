from fastapi.testclient import TestClient

from powerops.main import app

client = TestClient(app)


def test_liveness_is_explicitly_process_only() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "powerops"}


def test_readiness_reports_foundation_stage() -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "stage": "foundation"}
