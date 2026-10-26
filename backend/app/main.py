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

from app.core.database import init_db
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
        "ARAS/CASAS datasets, Powerformer/WC-MHA (demo mode), and SQLite storage."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
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
    }


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
        index = os.path.join(FRONTEND_BUILD, "index.html")
        return FileResponse(index)
