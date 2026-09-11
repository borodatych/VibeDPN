"""Core API."""

from fastapi.testclient import TestClient

from vibedpn import __version__
from vibedpn.api.app import create_app


def test_health() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
