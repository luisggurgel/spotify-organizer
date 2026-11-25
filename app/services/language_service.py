from lingua import Language, LanguageDetectorBuilder

from app.config import Settings
from app.models.schemas import LanguageResult
from app.services.lyrics_service import LyricsLookupResult
from app.utils.text import has_sufficient_lyrics, strip_lyrics_noise

_LINGUA_LANGUAGES = [
    Language.PORTUGUESE,
    Language.ENGLISH,
    Language.SPANISH,
    Language.FRENCH,
    Language.ITALIAN,
    Language.GERMAN,
    Language.JAPANESE,
    Language.KOREAN,
    Language.RUSSIAN,
]

_LINGUA_TO_ISO = {
    Language.PORTUGUESE: "pt",
    Language.ENGLISH: "en",
    Language.SPANISH: "es",
    Language.FRENCH: "fr",
    Language.ITALIAN: "it",
    Language.GERMAN: "de",
    Language.JAPANESE: "ja",
    Language.KOREAN: "ko",
    Language.RUSSIAN: "ru",
}

_ISRC_LANGUAGE_MAP = {
    "pt": {"BR", "PT", "AO", "MZ"},
    "en": {"US", "GB", "UK", "AU", "CA", "NZ", "IE", "ZA"},
    "es": {"ES", "MX", "AR", "CO", "CL", "PE", "VE", "UY", "PR", "DO", "EC"},
}


class LanguageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.detector = (
            LanguageDetectorBuilder.from_languages(*_LINGUA_LANGUAGES)
            .with_preloaded_language_models()
            .build()
        )

    def _isrc_matches_language(self, isrc: str | None, lang_iso: str) -> bool:
        if not isrc or len(isrc) < 2:
            return False
        return isrc[:2].upper() in _ISRC_LANGUAGE_MAP.get(lang_iso, set())

    def classify(
        self, lookup: LyricsLookupResult, isrc: str | None = None
    ) -> LanguageResult:
        if lookup.is_instrumental:
            return LanguageResult(language="instrumental", confidence=1.0, source="instrumental")

        lyrics = strip_lyrics_noise(lookup.lyrics or "")
        if not has_sufficient_lyrics(
            lyrics,
            min_chars=self.settings.min_lyrics_chars,
            min_unique_words=self.settings.min_unique_words,
        ):
            return LanguageResult(language="unclassified", confidence=0.0, source="quarantine")

        confidences = self.detector.compute_language_confidence_values(lyrics)
        if not confidences:
            return LanguageResult(language="unclassified", confidence=0.0, source="quarantine")

        top = confidences[0]
        detected_iso = _LINGUA_TO_ISO.get(top.language, "other")
        confidence = round(top.value, 4)

        if confidence >= self.settings.language_confidence_threshold:
            final_lang = detected_iso if detected_iso in self.settings.target_playlists else "other"
            return LanguageResult(language=final_lang, confidence=confidence, source="lyrics_nlp")

        if (
            confidence >= self.settings.isrc_fallback_threshold
            and detected_iso in self.settings.target_playlists
            and self._isrc_matches_language(isrc, detected_iso)
        ):
            return LanguageResult(
                language=detected_iso,
                confidence=confidence,
                source="lyrics_nlp+isrc",
            )

        return LanguageResult(language="unclassified", confidence=confidence, source="quarantine")
