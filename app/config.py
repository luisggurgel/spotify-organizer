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

    language_confidence_threshold: float = 0.70
    language_confidence_margin: float = 0.20
    isrc_fallback_threshold: float = 0.50
    isrc_fallback_margin: float = 0.12
    min_lyrics_chars: int = 45
    min_unique_words: int = 7

    lrclib_user_agent: str = "SpotifyOrganizer/1.1.0 (contact@example.com)"
    lrclib_max_concurrency: int = 3
    lyrics_ovh_max_concurrency: int = 3
    vagalume_api_key: str = ""

    language_playlist_names: dict[str, str] = {
        "pt": "Songs - Portuguese",
        "en": "Songs - English",
        "es": "Songs - Spanish",
        "fr": "Songs - French",
        "it": "Songs - Italian",
        "de": "Songs - German",
        "ja": "Songs - Japanese",
        "ko": "Songs - Korean",
        "ru": "Songs - Russian",
        "nl": "Songs - Dutch",
        "sv": "Songs - Swedish",
        "pl": "Songs - Polish",
        "tr": "Songs - Turkish",
        "ar": "Songs - Arabic",
        "hi": "Songs - Hindi",
        "zh": "Songs - Chinese",
    }
    quarantine_playlist_name: str = "Review - Unclassified Language"


@lru_cache
def get_settings() -> Settings:
    return Settings()