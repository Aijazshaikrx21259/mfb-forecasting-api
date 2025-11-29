"""Tests for health check endpoint."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
def test_health_endpoint_returns_ok(test_client: TestClient):
    """Test that health endpoint returns 200 OK."""
    response = test_client.get("/health")
    assert response.status_code == 200


@pytest.mark.unit
def test_health_endpoint_returns_json(test_client: TestClient):
    """Test that health endpoint returns JSON response."""
    response = test_client.get("/health")
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert "status" in data


@pytest.mark.unit
def test_health_endpoint_no_auth_required(test_client: TestClient):
    """Test that health endpoint does not require authentication."""
    response = test_client.get("/health")
    assert response.status_code == 200
    # Should work without X-API-Key header
