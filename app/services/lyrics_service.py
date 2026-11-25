import asyncio
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.models.schemas import TrackInfo
from app.utils.text import artists_match, clean_title, parse_retry_after, strip_lyrics_noise


@dataclass
class LyricsLookupResult:
    lyrics: str | None
    is_instrumental: bool = False


class LyricsService:
    BASE_URL = "https://lrclib.net/api"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.semaphore = asyncio.Semaphore(settings.lrclib_max_concurrency)
        self.client = client or httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": settings.lrclib_user_agent},
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _extract_text(self, payload: dict) -> LyricsLookupResult:
        if payload.get("instrumental") is True:
            return LyricsLookupResult(lyrics=None, is_instrumental=True)

        plain = (payload.get("plainLyrics") or "").strip()
        if plain:
            return LyricsLookupResult(lyrics=strip_lyrics_noise(plain) or None)

        synced = (payload.get("syncedLyrics") or "").strip()
        if synced:
            return LyricsLookupResult(lyrics=strip_lyrics_noise(synced) or None)

        return LyricsLookupResult(lyrics=None)

    async def _safe_get(self, path: str, params: dict) -> httpx.Response | None:
        for attempt in range(3):
            async with self.semaphore:
                try:
                    resp = await self.client.get(f"{self.BASE_URL}{path}", params=params)
                except httpx.HTTPError:
                    await asyncio.sleep(1 + attempt)
                    continue

            if resp.status_code == 429:
                wait = parse_retry_after(resp.headers.get("Retry-After"), default=3.0)
                await asyncio.sleep(wait)
                continue

            if resp.status_code >= 500 and attempt < 2:
                await asyncio.sleep(1 + attempt)
                continue

            return resp
        return None

    async def fetch_lyrics(self, track: TrackInfo) -> LyricsLookupResult:
        normalized_title = clean_title(track.name)
        duration_sec = round(track.duration_ms / 1000) if track.duration_ms else None

        params: dict[str, str | int] = {
            "artist_name": track.primary_artist,
            "track_name": normalized_title,
        }
        if track.album_name:
            params["album_name"] = clean_title(track.album_name)
        if duration_sec:
            params["duration"] = duration_sec

        resp = await self._safe_get("/get", params)
        if resp and resp.status_code == 200:
            res = self._extract_text(resp.json())
            if res.is_instrumental or res.lyrics:
                return res

        search_resp = await self._safe_get(
            "/search",
            {"track_name": normalized_title, "artist_name": track.primary_artist},
        )
        if search_resp and search_resp.status_code == 200:
            candidates = search_resp.json()
            if isinstance(candidates, list):
                for item in candidates[:5]:
                    cand_artist = item.get("artistName") or ""
                    if artists_match(track.primary_artist, cand_artist):
                        res = self._extract_text(item)
                        if res.is_instrumental or res.lyrics:
                            return res

        return LyricsLookupResult(lyrics=None, is_instrumental=False)
