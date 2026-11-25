from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse

from app.config import get_settings
from app.core.organizer import SpotifyOrganizer
from app.database.cache import CacheDB
from app.models.schemas import JobStatus, OrganizeRequest
from app.services.language_service import LanguageService
from app.services.lyrics_service import LyricsService
from app.services.spotify_service import SpotifyService

ACTIVE_JOB_STATUSES = {"queued", "ingesting", "classifying", "cleaning", "populating"}
MAX_STORED_JOBS = 50
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db = CacheDB(settings.database_path)
    spotify = SpotifyService(settings, db)
    lyrics = LyricsService(settings)
    language = LanguageService(settings)

    app.state.db = db
    app.state.spotify = spotify
    app.state.organizer = SpotifyOrganizer(settings, db, spotify, lyrics, language)
    app.state.jobs: OrderedDict[str, JobStatus] = OrderedDict()
    app.state.oauth_states: set[str] = set()
    yield
    await spotify.close()
    await lyrics.close()


app = FastAPI(
    title="Spotify Language Organizer API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}


@app.get("/auth/status", summary="Check Spotify authentication status")
async def auth_status():
    if not app.state.db.get_tokens():
        return {"authenticated": False, "display_name": None}

    try:
        user = await app.state.spotify.get_current_user()
        return {
            "authenticated": True,
            "display_name": user.get("display_name") or user.get("id"),
        }
    except Exception:
        return {"authenticated": True, "display_name": None}


@app.get("/auth/login", summary="Redirect to Spotify OAuth login")
async def auth_login():
    state = secrets.token_urlsafe(32)
    app.state.oauth_states.add(state)
    return RedirectResponse(url=app.state.spotify.get_authorize_url(state=state))


@app.get("/auth/callback", summary="Spotify OAuth callback")
async def auth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Authorization denied by Spotify: {error}")
    if not state or state not in app.state.oauth_states:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth 'state' parameter.")
    app.state.oauth_states.discard(state)

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    await app.state.spotify.exchange_code(code)
    return RedirectResponse(url="/?auth=success")


@app.post("/organize/run", response_model=JobStatus, summary="Start organization pipeline in background")
async def run_organizer(request: OrganizeRequest, background_tasks: BackgroundTasks):
    if not app.state.db.get_tokens():
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Open /auth/login in your browser first.",
        )

    for existing in app.state.jobs.values():
        if existing.status in ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Another job is already running ({existing.job_id}).",
            )

    job_id = str(uuid.uuid4())
    job = JobStatus(job_id=job_id, status="queued", dry_run=request.dry_run)
    app.state.jobs[job_id] = job

    while len(app.state.jobs) > MAX_STORED_JOBS:
        app.state.jobs.popitem(last=False)

    background_tasks.add_task(app.state.organizer.run_pipeline, request, job)
    return job


@app.get("/organize/jobs/{job_id}", response_model=JobStatus, summary="Get job progress and statistics")
async def get_job_status(job_id: str):
    job = app.state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.delete("/cache", summary="Clear local track language cache")
async def clear_cache():
    removed = app.state.db.clear_language_cache()
    return {"removed_entries": removed}
