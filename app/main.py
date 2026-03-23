"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import demo as demo_module
from app.api.router import api_router
from app.config import settings

STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}',
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    import arq
    logger.info("DocExtract AI starting up...")
    app.state.arq_pool = await arq.create_pool(
        arq.connections.RedisSettings.from_dsn(settings.redis_url)
    )
    yield
    logger.info("DocExtract AI shutting down...")
    await app.state.arq_pool.aclose()
    from app.models.database import engine
    await engine.dispose()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="DocExtract AI",
        description="AI-Powered Document Data Extraction & Processing System",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        contact={"name": "Cayman Roden", "url": "https://chunkytortoise.github.io"},
        license_info={"name": "MIT"},
        openapi_tags=[
            {"name": "health", "description": "Health check and dependency status endpoints"},
            {"name": "documents", "description": "Document upload, batch upload, and deletion"},
            {"name": "jobs", "description": "Job status, cancellation, and SSE progress streaming"},
            {"name": "records", "description": "Extracted record listing, search, and review submission"},
            {"name": "export", "description": "Streaming CSV/JSON export of extracted records"},
            {"name": "webhooks", "description": "Webhook test endpoint for verifying receiver configuration"},
            {"name": "stats", "description": "Aggregate dashboard statistics"},
            {"name": "api-keys", "description": "Self-service API key creation, listing, and revocation"},
            {"name": "review", "description": "Human-in-the-loop review queue: claim, approve, correct"},
            {"name": "roi", "description": "ROI attribution, trends, and executive report generation"},
            {"name": "agent-search", "description": "Agentic RAG with ReAct reasoning loop over document corpus"},
        ],
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID middleware
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Exception handlers
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "Validation error",
                "detail": exc.errors(),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception",
            exc_info=exc,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    app.include_router(api_router)
    app.include_router(demo_module.router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    from app.observability import setup_telemetry
    setup_telemetry(app)

    from app.langsmith_tracing import setup_langsmith
    setup_langsmith()

    return app


app = create_app()
