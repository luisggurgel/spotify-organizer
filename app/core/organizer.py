import asyncio

from app.config import Settings
from app.core.cleaner import PlaylistCleaner
from app.database.cache import CacheDB
from app.models.schemas import JobStatus, LanguageResult, OrganizeRequest, TrackInfo
from app.services.language_service import LanguageService
from app.services.lyrics_service import LyricsService
from app.services.spotify_service import SpotifyService
from app.utils.text import clean_title, normalize_key


class SpotifyOrganizer:
    def __init__(
        self,
        settings: Settings,
        db: CacheDB,
        spotify: SpotifyService,
        lyrics: LyricsService,
        language: LanguageService,
    ):
        self.settings = settings
        self.db = db
        self.spotify = spotify
        self.lyrics = lyrics
        self.language = language
        self.cleaner = PlaylistCleaner(spotify)

    def deduplicate_tracks(self, tracks: list[TrackInfo]) -> list[TrackInfo]:
        seen_isrc: set[str] = set()
        seen_composite: set[str] = set()
        unique: list[TrackInfo] = []

        for track in tracks:
            if track.isrc:
                isrc_upper = track.isrc.upper()
                if isrc_upper in seen_isrc:
                    continue
                seen_isrc.add(isrc_upper)

            comp_key = (
                f"{normalize_key(track.primary_artist)}::{normalize_key(clean_title(track.name))}"
            )
            if comp_key != "::":
                if comp_key in seen_composite:
                    continue
                seen_composite.add(comp_key)

            unique.append(track)

        return unique

    async def _classify_track(
        self, track: TrackInfo, force_reclassify: bool, job: JobStatus
    ) -> tuple[TrackInfo, LanguageResult]:
        if not force_reclassify:
            cached = self.db.get_track_language(track.id)
            if cached:
                job.stats.cache_hits += 1
                job.stats.processed_tracks += 1
                return track, cached

        lookup = await self.lyrics.fetch_lyrics(track)
        result = self.language.classify(lookup, isrc=track.isrc)
        self.db.save_track_language(track.id, result, isrc=track.isrc)
        job.stats.processed_tracks += 1
        return track, result

    async def run_pipeline(self, request: OrganizeRequest, job: JobStatus) -> None:
        try:
            job.status = "ingesting"
            user = await self.spotify.get_current_user()
            user_id = user["id"]

            raw_tracks = await self.spotify.get_liked_tracks()
            job.stats.total_fetched = len(raw_tracks)

            tracks = self.deduplicate_tracks(raw_tracks)
            job.stats.unique_tracks = len(tracks)
            job.stats.duplicates_removed = len(raw_tracks) - len(tracks)

            job.status = "classifying"
            tasks = [
                self._classify_track(track, request.force_reclassify, job)
                for track in tracks
            ]
            classified_pairs = await asyncio.gather(*tasks)

            grouped_uris: dict[str, list[str]] = {}
            for track, res in classified_pairs:
                job.stats.counts_by_language[res.language] = (
                    job.stats.counts_by_language.get(res.language, 0) + 1
                )
                grouped_uris.setdefault(res.language, []).append(track.uri)

            if request.dry_run:
                job.status = "completed"
                return

            playlist_plan: dict[str, list[str]] = {}
            for iso_code, pl_name in self.settings.target_playlists.items():
                uris = grouped_uris.get(iso_code, [])
                if uris:
                    playlist_plan[pl_name] = uris

            if request.create_quarantine_playlist:
                quarantine_uris = grouped_uris.get("unclassified", [])
                if quarantine_uris:
                    playlist_plan[self.settings.quarantine_playlist_name] = quarantine_uris

            job.status = "cleaning"
            all_managed_names = list(self.settings.target_playlists.values())
            if request.create_quarantine_playlist:
                all_managed_names.append(self.settings.quarantine_playlist_name)

            reusable_playlists, deleted_count = await self.cleaner.prepare_target_playlists(
                user_id=user_id,
                target_names=all_managed_names,
                mode=request.cleanup_mode,
            )
            job.stats.playlists_deleted = deleted_count

            job.status = "populating"
            planned_norm = {name.strip().lower() for name in playlist_plan}
            for norm_name, existing in reusable_playlists.items():
                if norm_name not in planned_norm:
                    await self.spotify.replace_playlist_items(existing["id"], [])
                    job.stats.playlists_updated.append(f"{existing['name']} (emptied)")

            for pl_name, uris in playlist_plan.items():
                norm_name = pl_name.strip().lower()
                existing = reusable_playlists.get(norm_name)

                if existing:
                    await self.spotify.replace_playlist_items(existing["id"], uris)
                else:
                    created = await self.spotify.create_playlist(
                        name=pl_name,
                        description="Automatically generated by Spotify Language Organizer (NLP + ISRC).",
                        public=request.public_playlists,
                    )
                    await self.spotify.add_playlist_items(created["id"], uris)

                job.stats.playlists_updated.append(f"{pl_name} ({len(uris)} tracks)")

            job.status = "completed"

        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
