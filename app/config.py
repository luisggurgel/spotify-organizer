from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://127.0.0.1:8000/auth/callback"
    spotify_scopes: str = (
        "user-library-read "
        "playlist-read-private "
        "playlist-read-collaborative "
        "playlist-modify-public "
        "playlist-modify-private"
    )

    database_path: str = "spotify_organizer.db"

    language_confidence_threshold: float = 0.85
    isrc_fallback_threshold: float = 0.70
    min_lyrics_chars: int = 80
    min_unique_words: int = 12

    lrclib_user_agent: str = "SpotifyOrganizer/1.0.0 (contact@example.com)"
    lrclib_max_concurrency: int = 5

    target_playlists: dict[str, str] = {
        "pt": "Songs - Portuguese",
        "en": "Songs - English",
        "es": "Songs - Spanish",
    }
    quarantine_playlist_name: str = "Review - Unclassified Language"


@lru_cache
def get_settings() -> Settings:
    return Settings()
