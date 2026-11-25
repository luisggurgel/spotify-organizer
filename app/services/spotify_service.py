import asyncio
import base64
import time
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.database.cache import CacheDB
from app.models.schemas import TrackInfo
from app.utils.text import chunked, parse_retry_after


class SpotifyAuthError(Exception):
    pass


class SpotifyService:
    AUTH_URL = "https://accounts.spotify.com/authorize"
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"

    def __init__(self, settings: Settings, db: CacheDB, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.db = db
        self.client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._refresh_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def get_authorize_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.spotify_client_id,
            "response_type": "code",
            "redirect_uri": self.settings.spotify_redirect_uri,
            "scope": self.settings.spotify_scopes,
            "state": state,
            "show_dialog": "true",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def _basic_auth_header(self) -> str:
        raw = f"{self.settings.spotify_client_id}:{self.settings.spotify_client_secret}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    async def exchange_code(self, code: str) -> None:
        resp = await self.client.post(
            self.TOKEN_URL,
            headers={"Authorization": self._basic_auth_header()},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.spotify_redirect_uri,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        refresh_token = data.get("refresh_token")
        if not refresh_token:
            raise SpotifyAuthError("Spotify response did not include a refresh_token.")
        self.db.save_tokens(
            access_token=data["access_token"],
            refresh_token=refresh_token,
            expires_in=data["expires_in"],
        )

    async def _refresh_access_token(self, expected_old_token: str | None = None) -> str:
        async with self._refresh_lock:
            tokens = self.db.get_tokens()
            if not tokens:
                raise SpotifyAuthError("User not authenticated. Visit /auth/login first.")

            if expected_old_token is not None and tokens["access_token"] != expected_old_token:
                return tokens["access_token"]
            if expected_old_token is None and tokens["expires_at"] - 60 > int(time.time()):
                return tokens["access_token"]

            resp = await self.client.post(
                self.TOKEN_URL,
                headers={"Authorization": self._basic_auth_header()},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            new_refresh = data.get("refresh_token", tokens["refresh_token"])
            self.db.save_tokens(
                access_token=data["access_token"],
                refresh_token=new_refresh,
                expires_in=data["expires_in"],
            )
            return data["access_token"]

    async def _get_valid_access_token(self) -> str:
        tokens = self.db.get_tokens()
        if not tokens:
            raise SpotifyAuthError("User not authenticated. Visit /auth/login first.")
        if tokens["expires_at"] - 60 > int(time.time()):
            return tokens["access_token"]
        return await self._refresh_access_token()

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        max_retries: int = 5,
    ) -> dict | None:
        url = endpoint if endpoint.startswith("http") else f"{self.API_BASE}{endpoint}"
        refreshed_after_401 = False

        for attempt in range(max_retries):
            token = await self._get_valid_access_token()
            resp = await self.client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                json=json_body,
            )

            if resp.status_code == 401 and not refreshed_after_401:
                await self._refresh_access_token(expected_old_token=token)
                refreshed_after_401 = True
                continue

            if resp.status_code == 429:
                wait = parse_retry_after(resp.headers.get("Retry-After"), default=2.0)
                await asyncio.sleep(wait + 0.5)
                continue

            if resp.status_code >= 500 and attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
                continue

            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()

        raise RuntimeError(f"Request failed after {max_retries} attempts for {method} {url}")

    async def get_current_user(self) -> dict:
        return await self._request("GET", "/me") or {}

    async def get_liked_tracks(self) -> list[TrackInfo]:
        tracks: list[TrackInfo] = []
        next_url: str | None = f"{self.API_BASE}/me/tracks?limit=50"

        while next_url:
            data = await self._request("GET", next_url)
            if not data:
                break

            for entry in data.get("items", []):
                if not entry:
                    continue
                track = entry.get("track")
                if not track or not track.get("id") or track.get("is_local"):
                    continue

                uri = track.get("uri") or ""
                if not uri.startswith("spotify:track:"):
                    continue

                artists = track.get("artists") or []
                primary_artist = artists[0]["name"] if artists else "Unknown"
                isrc = (track.get("external_ids") or {}).get("isrc")

                tracks.append(
                    TrackInfo(
                        id=track["id"],
                        uri=uri,
                        name=track["name"],
                        primary_artist=primary_artist,
                        album_name=(track.get("album") or {}).get("name", ""),
                        duration_ms=track.get("duration_ms", 0),
                        isrc=isrc,
                    )
                )

            next_url = data.get("next")

        return tracks

    async def get_user_playlists(self) -> list[dict]:
        playlists: list[dict] = []
        next_url: str | None = f"{self.API_BASE}/me/playlists?limit=50"

        while next_url:
            data = await self._request("GET", next_url)
            if not data:
                break
            playlists.extend(pl for pl in data.get("items", []) if pl)
            next_url = data.get("next")

        return playlists

    async def create_playlist(
        self, name: str, description: str = "", public: bool = False
    ) -> dict:
        return (
            await self._request(
                "POST",
                "/me/playlists",
                json_body={"name": name, "description": description, "public": public},
            )
            or {}
        )

    async def delete_playlists(self, playlist_uris: list[str]) -> None:
        for batch in chunked(playlist_uris, 40):
            await self._request(
                "DELETE",
                "/me/library",
                params={"uris": ",".join(batch)},
            )

    async def replace_playlist_items(self, playlist_id: str, track_uris: list[str]) -> None:
        if not track_uris:
            await self._request("PUT", f"/playlists/{playlist_id}/items", json_body={"uris": []})
            return

        first_batch = track_uris[:100]
        await self._request(
            "PUT", f"/playlists/{playlist_id}/items", json_body={"uris": first_batch}
        )

        remaining = track_uris[100:]
        if remaining:
            await self.add_playlist_items(playlist_id, remaining)

    async def add_playlist_items(self, playlist_id: str, track_uris: list[str]) -> None:
        for batch in chunked(track_uris, 100):
            await self._request(
                "POST",
                f"/playlists/{playlist_id}/items",
                json_body={"uris": batch},
            )
