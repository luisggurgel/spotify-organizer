import asyncio
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.config import Settings
from app.models.schemas import TrackInfo
from app.utils.text import (
    artists_match,
    clean_title,
    parse_retry_after,
    strip_lyrics_noise,
    titles_match,
)


@dataclass
class LyricsLookupResult:
    lyrics: str | None
    is_instrumental: bool = False
    transient_error: bool = False
    provider: str = "none"


class LyricsService:
    LRCLIB_BASE = "https://lrclib.net/api"
    LYRICS_OVH_BASE = "https://api.lyrics.ovh/v1"
    VAGALUME_URL = "https://api.vagalume.com.br/search.php"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.lrclib_sem = asyncio.Semaphore(settings.lrclib_max_concurrency)
        self.ovh_sem = asyncio.Semaphore(settings.lyrics_ovh_max_concurrency)
        self.vagalume_sem = asyncio.Semaphore(3)
        self.client = client or httpx.AsyncClient(
            timeout=12.0,
            headers={"User-Agent": settings.lrclib_user_agent},
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _extract_lrclib_text(self, payload: dict) -> LyricsLookupResult:
        if payload.get("instrumental") is True:
            return LyricsLookupResult(lyrics=None, is_instrumental=True, provider="lrclib")

        plain = (payload.get("plainLyrics") or "").strip()
        if plain:
            return LyricsLookupResult(lyrics=strip_lyrics_noise(plain) or None, provider="lrclib")

        synced = (payload.get("syncedLyrics") or "").strip()
        if synced:
            return LyricsLookupResult(lyrics=strip_lyrics_noise(synced) or None, provider="lrclib")

        return LyricsLookupResult(lyrics=None)

    async def _get_with_retry(
        self, url: str, sem: asyncio.Semaphore, params: dict | None = None, retries: int = 3
    ) -> tuple[httpx.Response | None, bool]:
        """Returns (response, had_transient_error)."""
        had_transient = False
        for attempt in range(retries):
            async with sem:
                try:
                    resp = await self.client.get(url, params=params)
                except httpx.HTTPError:
                    had_transient = True
                    await asyncio.sleep(1.0 + attempt)
                    continue

            if resp.status_code == 429:
                had_transient = True
                wait = parse_retry_after(resp.headers.get("Retry-After"), default=3.0)
                await asyncio.sleep(wait)
                continue

            if resp.status_code >= 500:
                had_transient = True
                if attempt < retries - 1:
                    await asyncio.sleep(1.0 + attempt)
                    continue
                return None, True

            return resp, False
        return None, had_transient

    async def _fetch_from_lrclib(
        self, track: TrackInfo, normalized_title: str
    ) -> LyricsLookupResult:
        duration_sec = round(track.duration_ms / 1000) if track.duration_ms else None
        params: dict[str, str | int] = {
            "artist_name": track.primary_artist,
            "track_name": normalized_title,
        }
        if track.album_name:
            params["album_name"] = clean_title(track.album_name)
        if duration_sec:
            params["duration"] = duration_sec

        resp, err1 = await self._get_with_retry(f"{self.LRCLIB_BASE}/get", self.lrclib_sem, params)
        if resp and resp.status_code == 200:
            res = self._extract_lrclib_text(resp.json())
            if res.is_instrumental or res.lyrics:
                return res

        # Structured search
        s_resp, err2 = await self._get_with_retry(
            f"{self.LRCLIB_BASE}/search",
            self.lrclib_sem,
            {"track_name": normalized_title, "artist_name": track.primary_artist},
        )
        if s_resp and s_resp.status_code == 200:
            res = self._pick_lrclib_candidate(s_resp.json(), track)
            if res:
                return res

        # Free-text search fallback (recovers accent / artist spelling mismatches)
        q_resp, err3 = await self._get_with_retry(
            f"{self.LRCLIB_BASE}/search",
            self.lrclib_sem,
            {"q": f"{track.primary_artist} {normalized_title}"},
        )
        if q_resp and q_resp.status_code == 200:
            res = self._pick_lrclib_candidate(q_resp.json(), track, require_title_match=True)
            if res:
                return res

        return LyricsLookupResult(lyrics=None, transient_error=(err1 or err2 or err3))

    def _pick_lrclib_candidate(
        self, candidates: object, track: TrackInfo, require_title_match: bool = False
    ) -> LyricsLookupResult | None:
        if not isinstance(candidates, list):
            return None
        for item in candidates[:6]:
            cand_artist = item.get("artistName") or ""
            cand_title = item.get("trackName") or ""
            if not artists_match(track.primary_artist, cand_artist):
                continue
            if require_title_match and not titles_match(track.name, cand_title):
                continue
            res = self._extract_lrclib_text(item)
            if res.is_instrumental or res.lyrics:
                return res
        return None

    async def _fetch_from_lyrics_ovh(
        self, artist: str, normalized_title: str
    ) -> LyricsLookupResult:
        url = f"{self.LYRICS_OVH_BASE}/{quote(artist, safe='')}/{quote(normalized_title, safe='')}"
        resp, err = await self._get_with_retry(url, self.ovh_sem, retries=2)
        if resp and resp.status_code == 200:
            try:
                text = (resp.json().get("lyrics") or "").strip()
            except ValueError:
                text = ""
            if text:
                cleaned = strip_lyrics_noise(text)
                if cleaned:
                    return LyricsLookupResult(lyrics=cleaned, provider="lyrics_ovh")
        return LyricsLookupResult(lyrics=None, transient_error=err)

    async def _fetch_from_vagalume(
        self, artist: str, normalized_title: str
    ) -> LyricsLookupResult:
        if not self.settings.vagalume_api_key:
            return LyricsLookupResult(lyrics=None)

        resp, err = await self._get_with_retry(
            self.VAGALUME_URL,
            self.vagalume_sem,
            params={
                "art": artist,
                "mus": normalized_title,
                "apikey": self.settings.vagalume_api_key,
            },
            retries=2,
        )
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if data.get("type") in {"exact", "aprox"}:
                mus = data.get("mus") or []
                if mus and isinstance(mus, list):
                    text = (mus[0].get("text") or "").strip()
                    if text:
                        return LyricsLookupResult(
                            lyrics=strip_lyrics_noise(text) or None,
                            provider="vagalume",
                        )
        return LyricsLookupResult(lyrics=None, transient_error=err)

    async def fetch_lyrics(self, track: TrackInfo) -> LyricsLookupResult:
        normalized_title = clean_title(track.name)

        # Provider 1: LRCLIB
        res = await self._fetch_from_lrclib(track, normalized_title)
        if res.is_instrumental or res.lyrics:
            return res
        any_transient = res.transient_error

        # Provider 2: Vagalume (if API key configured — highest accuracy for PT/BR & ES)
        if self.settings.vagalume_api_key:
            vag = await self._fetch_from_vagalume(track.primary_artist, normalized_title)
            if vag.lyrics:
                return vag
            any_transient = any_transient or vag.transient_error

        # Provider 3: Lyrics.ovh (free, no key)
        ovh = await self._fetch_from_lyrics_ovh(track.primary_artist, normalized_title)
        if ovh.lyrics:
            return ovh
        any_transient = any_transient or ovh.transient_error

        return LyricsLookupResult(lyrics=None, is_instrumental=False, transient_error=any_transient)