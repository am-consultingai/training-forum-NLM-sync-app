import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import paths
from backend.config import settings
from backend.database import init_db
from backend.jobs.scheduler import init_scheduler, shutdown_scheduler
from backend.api.files import router as files_router
from backend.api.sync import router as sync_router
from backend.api.progress import router as progress_router
from backend.api.config import router as config_router
from backend.api.status import router as status_router
from backend.api.auth import router as auth_router
from win_app.app_core.setup_api import router as setup_router

app = FastAPI(title="sHaRe sync")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files_router)
app.include_router(sync_router)
app.include_router(progress_router)
app.include_router(config_router)
app.include_router(status_router)
app.include_router(auth_router)
app.include_router(setup_router)


@app.on_event("startup")
async def startup():
    init_db()
    # Daily cron is opt-in (manual-sync-only in the packaged build).
    if settings.enable_scheduler:
        init_scheduler()


@app.on_event("shutdown")
async def shutdown():
    if settings.enable_scheduler:
        shutdown_scheduler()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Serve the built frontend (same origin as the API) ────────────────────────
# The React app calls a relative /api and same-origin SSE, so serving its build
# from here means no separate dev server in the packaged app. Registered AFTER the
# API routers so /api/* always wins; the catch-all below is the SPA fallback.
_DIST = paths.frontend_dist_dir()
if os.path.isdir(_DIST):
    _ASSETS = os.path.join(_DIST, "assets")
    if os.path.isdir(_ASSETS):
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")

    @app.get("/")
    def _index():
        return FileResponse(os.path.join(_DIST, "index.html"))

    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        # Never let the SPA fallback swallow unmatched API calls.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = os.path.join(_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))
