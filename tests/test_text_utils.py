from app.utils.text import (
    artists_match,
    chunked,
    clean_title,
    has_sufficient_lyrics,
    normalize_key,
    parse_retry_after,
    strip_lyrics_noise,
)


def test_clean_title_preserves_valid_titles():
    assert clean_title("(Don't Fear) The Reaper") == "(Don't Fear) The Reaper"
    assert clean_title("Love (Without You)") == "Love (Without You)"
    assert clean_title("Live Forever") == "Live Forever"


def test_clean_title_strips_spotify_suffixes():
    assert clean_title("Bohemian Rhapsody - Remastered 2011") == "Bohemian Rhapsody"
    assert clean_title("Bohemian Rhapsody (2011 Remaster)") == "Bohemian Rhapsody"
    assert clean_title("Envolver (feat. Justin Quiles)") == "Envolver"
    assert clean_title("Tempo Perdido (Ao Vivo)") == "Tempo Perdido"
    assert clean_title("Creep [Acoustic] (Radio Edit)") == "Creep"


def test_normalize_key_handles_accents_and_non_latin():
    assert normalize_key("Coração") == normalize_key("Coracao")
    assert normalize_key("夜に駆ける") != ""
    assert normalize_key("夜に駆ける") != normalize_key("アイドル")


def test_strip_lyrics_and_uniqueness_guard():
    raw = "[00:10.00] [Chorus]\n[00:12.00] la la la yeah oh " * 10
    cleaned = strip_lyrics_noise(raw)
    assert "[Chorus]" not in cleaned
    assert not has_sufficient_lyrics(cleaned)


def test_artists_match_avoids_short_false_positives():
    assert artists_match("Anitta", "Anitta, Peso Pluma")
    assert artists_match("U2", "U2 & Green Day")
    assert not artists_match("X", "Coldplay x BTS")
    assert not artists_match("M", "Madonna")


def test_parse_retry_after_and_chunked():
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("invalid", default=3.0) == 3.0
    assert [len(b) for b in chunked(list(range(250)), 100)] == [100, 100, 50]
