from app.config import Settings
from app.services.language_service import LanguageService
from app.services.lyrics_service import LyricsLookupResult


def _settings():
    return Settings(spotify_client_id="id", spotify_client_secret="secret")


def test_language_detection_strict_mode():
    service = LanguageService(_settings())

    pt_lyrics = (
        "Olha que coisa mais linda mais cheia de graça é ela menina que vem e que passa "
        "num doce balanço a caminho do mar moça do corpo dourado do sol de Ipanema "
        "o seu balançado é mais que um poema é a coisa mais linda que eu já vi passar"
    )
    en_lyrics = (
        "Is this the real life is this just fantasy caught in a landslide no escape from reality "
        "open your eyes look up to the skies and see I am just a poor boy I need no sympathy "
        "because I am easy come easy go little high little low anyway the wind blows"
    )

    res_en = service.classify(LyricsLookupResult(lyrics=en_lyrics), isrc="BR1234567890")
    assert res_en.language == "en"
    assert res_en.source == "lyrics_nlp"

    res_pt = service.classify(LyricsLookupResult(lyrics=pt_lyrics), isrc="BR1234567890")
    assert res_pt.language == "pt"

    res_inst = service.classify(LyricsLookupResult(lyrics=None, is_instrumental=True))
    assert res_inst.language == "instrumental"

    res_missing = service.classify(LyricsLookupResult(lyrics=None))
    assert res_missing.language == "unclassified"
