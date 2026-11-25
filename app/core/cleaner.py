from app.models.schemas import CleanupMode
from app.services.spotify_service import SpotifyService


class PlaylistCleaner:
    def __init__(self, spotify: SpotifyService):
        self.spotify = spotify

    async def prepare_target_playlists(
        self,
        user_id: str,
        target_names: list[str],
        mode: CleanupMode,
    ) -> tuple[dict[str, dict], int]:
        all_playlists = await self.spotify.get_user_playlists()
        normalized_targets = {name.strip().lower() for name in target_names}

        collisions_by_name: dict[str, list[dict]] = {}
        for pl in all_playlists:
            if not pl:
                continue
            owner_id = (pl.get("owner") or {}).get("id")
            pl_name_norm = (pl.get("name") or "").strip().lower()
            if owner_id == user_id and pl_name_norm in normalized_targets:
                collisions_by_name.setdefault(pl_name_norm, []).append(pl)

        reusable: dict[str, dict] = {}
        uris_to_delete: list[str] = []

        for norm_name, matched in collisions_by_name.items():
            if mode == CleanupMode.HARD_DELETE:
                uris_to_delete.extend(pl["uri"] for pl in matched if pl.get("uri"))
            else:
                reusable[norm_name] = matched[0]
                if len(matched) > 1:
                    uris_to_delete.extend(pl["uri"] for pl in matched[1:] if pl.get("uri"))

        if uris_to_delete:
            await self.spotify.delete_playlists(uris_to_delete)

        return reusable, len(uris_to_delete)
