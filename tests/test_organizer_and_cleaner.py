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
        if track.id == "no_lyr":
            return LyricsLookupResult(lyrics=None)
        return LyricsLookupResult(lyrics=track.name)


class FakeLanguage:
    def classify(self, lookup, isrc=None):
        if not lookup.lyrics:
            return LanguageResult(language="unclassified", confidence=0.0, source="no_lyrics")
        if "PT" in lookup.lyrics:
            return LanguageResult(language="pt", confidence=0.95, source="lyrics_nlp")
        return LanguageResult(language="fr", confidence=0.95, source="lyrics_nlp")

    def classify_from_metadata(self, track):
        return None

    def title_conflicts_with_language(self, title, expected_lang):
        return False


@pytest.mark.asyncio
async def test_pipeline_dynamic_languages_and_artist_consensus(tmp_path):
    settings = Settings(spotify_client_id="id", spotify_client_secret="sec")
    db = CacheDB(str(tmp_path / "org.db"))

    tracks = [
        TrackInfo(id="1", uri="spotify:track:1", name="Song PT 1", primary_artist="Djavan", isrc="BR001"),
        TrackInfo(id="2", uri="spotify:track:2", name="Song PT 2", primary_artist="Djavan", isrc="BR002"),
        # No lyrics, but Djavan has 2/2 verified PT tracks -> artist_consensus recovers it!
        TrackInfo(id="no_lyr", uri="spotify:track:3", name="Live Track", primary_artist="Djavan"),
        TrackInfo(id="4", uri="spotify:track:4", name="Chanson FR", primary_artist="Stromae"),
    ]
    playlists = [
        {"id": "p_pt", "uri": "spotify:playlist:p_pt", "name": "Songs - Portuguese", "owner": {"id": "me"}},
        {"id": "p_es", "uri": "spotify:playlist:p_es", "name": "Songs - Spanish", "owner": {"id": "me"}},
    ]

    spotify = FakeSpotify(tracks, playlists)
    organizer = SpotifyOrganizer(settings, db, spotify, FakeLyrics(), FakeLanguage())
    job = JobStatus(job_id="j1", status="queued", dry_run=False)

    await organizer.run_pipeline(
        OrganizeRequest(cleanup_mode=CleanupMode.REPLACE_TRACKS, min_tracks_per_playlist=1),
        job,
    )

    assert job.status == "completed"
    assert job.stats.counts_by_language == {"pt": 3, "fr": 1}
    assert job.stats.counts_by_source["artist_consensus"] == 1
    assert ("p_es", []) in spotify.replaced
    assert ("p_pt", ["spotify:track:1", "spotify:track:2", "spotify:track:3"]) in spotify.replaced
    assert spotify.created == [("new_1", "Songs - French", False)]