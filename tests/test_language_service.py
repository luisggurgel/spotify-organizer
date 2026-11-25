from app.config import Settings
from app.models.schemas import TrackInfo
from app.services.language_service import LanguageService
from app.services.lyrics_service import LyricsLookupResult


def _settings():
    return Settings(spotify_client_id="id", spotify_client_secret="secret")


def test_language_detection_and_fallbacks():
    service = LanguageService(_settings())

    pt_lyrics = (
        "Olha que coisa mais linda mais cheia de graça é ela menina que vem e que passa "
        "num doce balanço a caminho do mar moça do corpo dourado do sol de Ipanema"
    )
    en_lyrics = (
        "Is this the real life is this just fantasy caught in a landslide no escape from reality "
        "open your eyes look up to the skies and see I am just a poor boy I need no sympathy"
    )
    fr_lyrics = (
        "Alors on danse et puis on oublie tout ce qui nous fait mal dans la vie quotidienne "
        "quand la musique joue fort toute la nuit sans jamais s'arrêter"
    )

    assert service.classify(LyricsLookupResult(lyrics=en_lyrics), isrc="BR1234567890").language == "en"
    assert service.classify(LyricsLookupResult(lyrics=pt_lyrics), isrc="BR1234567890").language == "pt"
    assert service.classify(LyricsLookupResult(lyrics=fr_lyrics)).language == "fr"

    # Transient API error must be tagged distinctly so organizer never caches it
    err = service.classify(LyricsLookupResult(lyrics=None, transient_error=True))
    assert err.language == "unclassified"
    assert err.source == "provider_error"

    # Script fallback for Japanese / Korean without lyrics
    ja_track = TrackInfo(id="j1", uri="spotify:track:j1", name="夜に駆ける", primary_artist="YOASOBI")
    assert service.classify_from_metadata(ja_track).language == "ja"

    # Diacritics + ISRC fallback for PT / ES without lyrics
    pt_track = TrackInfo(
        id="p1", uri="spotify:track:p1", name="Coração Partido", primary_artist="Artista", isrc="BR001"
    )
    assert service.classify_from_metadata(pt_track).language == "pt"