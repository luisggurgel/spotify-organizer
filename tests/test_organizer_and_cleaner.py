import pytest

from app.config import Settings
from app.core.organizer import SpotifyOrganizer
from app.database.cache import CacheDB
from app.models.schemas import CleanupMode, JobStatus, LanguageResult, OrganizeRequest, TrackInfo
from app.services.lyrics_service import LyricsLookupResult


class FakeSpotify:
    def __init__(self, tracks, playlists):
        self._tracks = tracks
        self._playlists = playlists
        self.deleted_uris = []
        self.replaced = []
        self.created = []
        self.added = []

    async def get_current_user(self):
        return {"id": "me"}

    async def get_liked_tracks(self):
        return self._tracks

    async def get_user_playlists(self):
        return self._playlists

    async def delete_playlists(self, uris):
        self.deleted_uris.extend(uris)

    async def replace_playlist_items(self, playlist_id, uris):
        self.replaced.append((playlist_id, list(uris)))

    async def create_playlist(self, name, description="", public=False):
        pid = f"new_{len(self.created) + 1}"
        self.created.append((pid, name, public))
        return {"id": pid, "name": name}

    async def add_playlist_items(self, playlist_id, uris):
        self.added.append((playlist_id, list(uris)))


class FakeLyrics:
    async def fetch_lyrics(self, track):
        return LyricsLookupResult(lyrics=track.name)


class FakeLanguage:
    def classify(self, lookup, isrc=None):
        if "PT" in (lookup.lyrics or ""):
            return LanguageResult(language="pt", confidence=0.95, source="lyrics_nlp")
        return LanguageResult(language="en", confidence=0.95, source="lyrics_nlp")


@pytest.mark.asyncio
async def test_pipeline_replace_mode_cleans_duplicates_and_empties_stale(tmp_path):
    settings = Settings(spotify_client_id="id", spotify_client_secret="sec")
    db = CacheDB(str(tmp_path / "org.db"))

    tracks = [
        TrackInfo(id="1", uri="spotify:track:1", name="Song PT", primary_artist="A", isrc="BR001"),
        TrackInfo(id="2", uri="spotify:track:2", name="Song PT (Album)", primary_artist="A", isrc="BR001"),
        TrackInfo(id="3", uri="spotify:track:3", name="Song EN", primary_artist="B"),
    ]
    playlists = [
        {"id": "p_pt_1", "uri": "spotify:playlist:p_pt_1", "name": "Songs - Portuguese", "owner": {"id": "me"}},
        {"id": "p_pt_2", "uri": "spotify:playlist:p_pt_2", "name": "Songs - Portuguese", "owner": {"id": "me"}},
        {"id": "p_es", "uri": "spotify:playlist:p_es", "name": "Songs - Spanish", "owner": {"id": "me"}},
        {"id": "stranger", "uri": "spotify:playlist:stranger", "name": "Songs - Portuguese", "owner": {"id": "other"}},
    ]

    spotify = FakeSpotify(tracks, playlists)
    organizer = SpotifyOrganizer(settings, db, spotify, FakeLyrics(), FakeLanguage())
    job = JobStatus(job_id="j1", status="queued", dry_run=False)

    await organizer.run_pipeline(OrganizeRequest(cleanup_mode=CleanupMode.REPLACE_TRACKS), job)

    assert job.status == "completed"
    assert job.stats.duplicates_removed == 1
    assert spotify.deleted_uris == ["spotify:playlist:p_pt_2"]
    assert ("p_es", []) in spotify.replaced
    assert ("p_pt_1", ["spotify:track:1"]) in spotify.replaced
    assert spotify.created == [("new_1", "Songs - English", False)]
    assert spotify.added == [("new_1", ["spotify:track:3"])]
