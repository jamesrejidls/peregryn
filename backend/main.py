"""
Application entry point.
- Loads .env
- Initializes the database (creates tables if they don't exist)
- Mounts auth, intake, insights, query, PRD routers
- Serves the static SPA frontend from /
Run: uvicorn backend.main:app --reload --port 8000
"""
import os
import pathlib
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()  # MUST happen before importing anything that reads env at import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .auth import router as auth_router
from .intake import router as intake_router
from .insights import router as insights_router
from .query import router as query_router
from .prd import router as prd_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once on startup: ensures tables exist (idempotent — safe to run on every deploy).
    init_db()
    yield
    # No teardown needed — SQLAlchemy handles connection cleanup.


app = FastAPI(title="Peregryn", version="1.0.0", lifespan=lifespan)

# CORS — allow everything by default. Tighten via ALLOWED_ORIGINS env var in production
# (comma-separated list of origins) once you know your final deployed URL.
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in allowed_origins_env.split(",")] if allowed_origins_env != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "llm_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))}


@app.get("/api/config")
def config():
    """Expose non-sensitive config to the frontend (publishable Clerk key, etc).
    The publishable key is safe to expose — it's designed for browser use.
    The secret key stays server-side only.
    """
    return {
        "clerk_publishable_key": os.getenv("CLERK_PUBLISHABLE_KEY", ""),
        "clerk_enabled": bool(os.getenv("CLERK_PUBLISHABLE_KEY")),
    }


# Register API routers under /api so they don't collide with the SPA
app.include_router(auth_router, prefix="/api")
app.include_router(intake_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(prd_router, prefix="/api")


# ---- serve frontend ----
FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    # Serve any sub-paths (e.g. /static/whatever) from the frontend folder.
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def root():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"message": "Frontend not found. See README."}, status_code=200)

    @app.get("/{full_path:path}")
    def spa_catchall(full_path: str):
        # Don't shadow API
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        # Try to serve a real file from /frontend, otherwise fall back to index.html (SPA routing)
        candidate = FRONTEND_DIR / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"detail": "Not found"}, status_code=404)
