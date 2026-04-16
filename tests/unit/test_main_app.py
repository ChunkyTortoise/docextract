"""Tests for app.main module (app factory, middleware, exception handlers)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_app_no_lifespan():
    """Create the app with a no-op lifespan to avoid DB/Redis connections."""
    from app.main import create_app

    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield

    with patch("app.main.lifespan", noop_lifespan):
        return create_app()


def test_create_app_returns_fastapi():
    """create_app returns a FastAPI instance with expected metadata."""
    app = _create_app_no_lifespan()
    assert app.title == "DocExtract AI"
    assert app.version == "1.0.0"


def test_request_id_middleware():
    """Request ID middleware adds X-Request-ID header."""
    app = _create_app_no_lifespan()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/health")
        assert "X-Request-ID" in response.headers
        request_id = response.headers["X-Request-ID"]
        assert len(request_id) == 36  # UUID length


def test_cors_headers():
    """CORS middleware is configured."""
    app = _create_app_no_lifespan()

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200


def test_app_includes_api_router():
    """App includes the API router with expected prefixed routes."""
    app = _create_app_no_lifespan()
    route_paths = [r.path for r in app.routes]
    # Health endpoint should be accessible
    assert any("/health" in p for p in route_paths)
