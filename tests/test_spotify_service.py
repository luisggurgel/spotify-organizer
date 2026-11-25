import time
import httpx
import pytest

from app.config import Settings
from app.database.cache import CacheDB
from app.services.spotify_service import SpotifyService


@pytest.mark.asyncio
async def test_spotify_handles_401_refresh_and_429_retry(tmp_path, monkeypatch):
    calls = {"api": 0, "token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            calls["token"] += 1
            return httpx.Response(
                200,
                json={"access_token": "fresh_token", "expires_in": 3600},
            )
        calls["api"] += 1
        if calls["api"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        if calls["api"] == 2:
            return httpx.Response(429, headers={"Retry-After": "0.1"})
        return httpx.Response(200, json={"id": "user123"})

    async def fast_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", fast_sleep)

    db = CacheDB(str(tmp_path / "sp.db"))
    db.save_tokens("stale_token", "ref_token", 3600)
    settings = Settings(spotify_client_id="cid", spotify_client_secret="csec")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = SpotifyService(settings, db, client=client)

    user = await service.get_current_user()
    assert user["id"] == "user123"
    assert calls["token"] == 1
    assert calls["api"] == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_delete_playlists_chunks_by_40_and_uses_me_library(tmp_path):
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((request.method, request.url.path, request.url.params["uris"]))
        return httpx.Response(200)

    db = CacheDB(str(tmp_path / "sp2.db"))
    db.save_tokens("ok_token", "ref", int(time.time()) + 3600)
    settings = Settings(spotify_client_id="cid", spotify_client_secret="csec")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = SpotifyService(settings, db, client=client)

    uris = [f"spotify:playlist:id{i}" for i in range(85)]
    await service.delete_playlists(uris)

    assert len(recorded) == 3
    assert all(m == "DELETE" and p == "/v1/me/library" for m, p, _ in recorded)
    assert [len(u.split(",")) for _, _, u in recorded] == [40, 40, 5]
    await client.aclose()
