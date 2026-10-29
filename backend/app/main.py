"""
FastAPI main application entry point for the Smart Home Activity Recognition System.
"""

import os
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.database import init_db, get_active_db_info
from app.api import sensors, datasets, predictions, dashboard, ml_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup."""
    logger.info("🚀 Starting Smart Home Activity Recognition System...")
    init_db()
    logger.info("✅ System ready.")
    yield
    logger.info("🛑 Shutting down...")


app = FastAPI(
    title="Smart Home Activity Recognition System",
    description=(
        "A 5-layer smart home activity recognition prototype using "
        "ARAS/CASAS datasets, Powerformer/WC-MHA (demo mode), and MySQL/SQLite storage."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:8080", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── API routers ──────────────────────────────────────────────────────────────
app.include_router(sensors.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(predictions.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(ml_routes.router, prefix="/api")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "Smart Home Activity Recognition System",
        "version": "1.0.0",
        "database": get_active_db_info(),
    }


# Backwards-compatible aliases for documentation endpoints under /api prefix
@app.get("/api/docs", include_in_schema=False)
def api_docs_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


@app.get("/api/redoc", include_in_schema=False)
def api_redoc_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/redoc")


@app.get("/api/openapi.json", include_in_schema=False)
def api_openapi_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/openapi.json")


@app.get("/api/download-zip")
def download_project_zip():
    zip_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "smarthome.zip"))
    if not os.path.exists(zip_path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Zip archive not found")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="smarthome_project.zip",
    )


# ─── Serve frontend static files (production) ─────────────────────────────────
FRONTEND_BUILD = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(FRONTEND_BUILD):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_BUILD, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        from fastapi import HTTPException
        clean_path = full_path.lstrip("/")
        # Never let the SPA catch-all intercept API, docs, redoc, or openapi.json routes
        if clean_path.startswith("api/") or clean_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")

        # Serve static assets from dist root if they exist (e.g. favicon.ico)
        dist_asset = os.path.join(FRONTEND_BUILD, clean_path)
        if clean_path and os.path.isfile(dist_asset):
            return FileResponse(dist_asset)

        # Fallback to SPA index.html for frontend client routing
        index = os.path.join(FRONTEND_BUILD, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
