"""
Tests for FastAPI Documentation Endpoints, OpenAPI Schema, and Static/SPA Route Fallback.
Validates:
1. GET /docs returns Swagger UI HTML (not intercepted by React SPA).
2. GET /openapi.json returns valid OpenAPI JSON schema specification.
3. GET /redoc returns ReDoc UI HTML.
4. GET /api/docs and /api/openapi.json redirect cleanly to /docs and /openapi.json.
5. GET /api/dashboard/stats?hours=24 returns valid dashboard stats JSON.
6. Frontend SPA fallback correctly serves index.html for UI page routes without hijacking /api or /docs.
7. Unmatched /api routes return 404 JSON error instead of returning index.html.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_DB_URL = "sqlite:///:memory:"
os.environ["DATABASE_URL"] = TEST_DB_URL

from app.main import app, FRONTEND_BUILD


class TestDocumentationAndRouteIntegrity:
    """Verify OpenAPI, Swagger Docs, ReDoc, and Static SPA routing."""

    def test_docs_returns_swagger_ui_html(self, client):
        """GET /docs must return FastAPI's Swagger UI HTML, not React index.html."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        # Swagger UI specifically contains SwaggerUIBundle and swagger-ui
        assert "swagger-ui" in response.text.lower()
        # Ensure it is NOT the React index.html
        assert '<div id="root">' not in response.text

    def test_openapi_json_returns_specification(self, client):
        """GET /openapi.json must return valid JSON with openapi version and routes."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")
        data = response.json()
        assert "openapi" in data
        assert "info" in data
        assert data["info"]["title"] == "Smart Home Activity Recognition System"
        assert "paths" in data
        # Verify key endpoints exist in the OpenAPI schema
        paths = data["paths"]
        assert "/api/dashboard/stats" in paths
        assert "/api/sensors/events" in paths
        assert "/api/predictions/run" in paths

    def test_redoc_returns_redoc_ui_html(self, client):
        """GET /redoc must return ReDoc HTML documentation."""
        response = client.get("/redoc")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "redoc" in response.text.lower()
        assert '<div id="root">' not in response.text

    def test_api_docs_redirects_to_docs(self, client):
        """GET /api/docs redirects cleanly to /docs."""
        response = client.get("/api/docs", follow_redirects=False)
        assert response.status_code in (301, 302, 307)
        assert response.headers.get("location") == "/docs"

    def test_api_openapi_redirects_to_openapi(self, client):
        """GET /api/openapi.json redirects cleanly to /openapi.json."""
        response = client.get("/api/openapi.json", follow_redirects=False)
        assert response.status_code in (301, 302, 307)
        assert response.headers.get("location") == "/openapi.json"

    def test_dashboard_stats_endpoint_returns_json(self, client):
        """GET /api/dashboard/stats?hours=24 returns valid 200 OK JSON with active DB info."""
        response = client.get("/api/dashboard/stats?hours=24")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")
        data = response.json()
        assert "sensor_events" in data
        assert "predictions" in data
        assert "pipeline_status" in data
        assert "database" in data
        assert data["database"]["active_backend"] in ("sqlite", "mysql")

    def test_frontend_spa_fallback_serves_html(self, client):
        """When frontend build exists, UI paths return index.html with #root element."""
        if not os.path.isdir(FRONTEND_BUILD):
            pytest.skip("frontend/dist is not built")
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert '<div id="root">' in response.text

        # Client-side router path
        monitoring_res = client.get("/monitoring")
        assert monitoring_res.status_code == 200
        assert '<div id="root">' in monitoring_res.text

    def test_invalid_api_path_returns_404_json_not_html(self, client):
        """Unmatched /api/* routes must return 404 JSON, NOT frontend index.html."""
        response = client.get("/api/nonexistent-route-xyz")
        assert response.status_code == 404
        assert "application/json" in response.headers.get("content-type", "")
        data = response.json()
        assert "detail" in data
