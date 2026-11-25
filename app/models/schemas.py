from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class CleanupMode(str, Enum):
    REPLACE_TRACKS = "replace_tracks"
    HARD_DELETE = "hard_delete"


class TrackInfo(BaseModel):
    id: str
    uri: str
    name: str
    primary_artist: str
    album_name: str = ""
    duration_ms: int = 0
    isrc: str | None = None


class LanguageResult(BaseModel):
    language: str
    confidence: float = 0.0
    source: str


class OrganizeRequest(BaseModel):
    cleanup_mode: CleanupMode = CleanupMode.REPLACE_TRACKS
    public_playlists: bool = False
    create_quarantine_playlist: bool = False
    dry_run: bool = False
    force_reclassify: bool = False


class JobStats(BaseModel):
    total_fetched: int = 0
    unique_tracks: int = 0
    duplicates_removed: int = 0
    cache_hits: int = 0
    processed_tracks: int = 0
    counts_by_language: dict[str, int] = Field(default_factory=dict)
    playlists_deleted: int = 0
    playlists_updated: list[str] = Field(default_factory=list)


class JobStatus(BaseModel):
    job_id: str
    status: Literal[
        "queued",
        "ingesting",
        "classifying",
        "cleaning",
        "populating",
        "completed",
        "failed",
    ]
    dry_run: bool
    stats: JobStats = Field(default_factory=JobStats)
    error: str | None = None
