from app.database.cache import CacheDB
from app.models.schemas import LanguageResult


def test_cache_tokens_and_languages(tmp_path):
    db = CacheDB(str(tmp_path / "test.db"))
    assert db.get_tokens() is None

    db.save_tokens("tok1", "ref1", 3600)
    assert db.get_tokens()["access_token"] == "tok1"

    db.save_track_language("t1", LanguageResult(language="pt", confidence=0.97, source="lyrics_nlp"), "BR001")
    got = db.get_track_language("t1")
    assert got is not None
    assert got.language == "pt"
    assert got.source == "cache"

    assert db.clear_language_cache() == 1
    assert db.get_track_language("t1") is None
