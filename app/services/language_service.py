from lingua import Language, LanguageDetectorBuilder

from app.config import Settings
from app.models.schemas import LanguageResult, TrackInfo
from app.services.lyrics_service import LyricsLookupResult
from app.utils.text import (
    clean_title,
    detect_script_language,
    has_es_exclusive_chars,
    has_pt_exclusive_diacritics,
    has_sufficient_lyrics,
    strip_lyrics_noise,
)

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
    Language.DUTCH,
    Language.SWEDISH,
    Language.POLISH,
    Language.TURKISH,
    Language.ARABIC,
    Language.HINDI,
    Language.CHINESE,
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
    Language.DUTCH: "nl",
    Language.SWEDISH: "sv",
    Language.POLISH: "pl",
    Language.TURKISH: "tr",
    Language.ARABIC: "ar",
    Language.HINDI: "hi",
    Language.CHINESE: "zh",
}

_ISRC_LANGUAGE_MAP = {
    "pt": {"BR", "PT", "AO", "MZ"},
    "en": {"US", "GB", "UK", "AU", "CA", "NZ", "IE", "ZA"},
    "es": {"ES", "MX", "AR", "CO", "CL", "PE", "VE", "UY", "PR", "DO", "EC", "BO", "PY", "GT", "CR"},
    "fr": {"FR", "BE", "CH", "CA"},
    "it": {"IT"},
    "de": {"DE", "AT", "CH"},
    "ja": {"JP"},
    "ko": {"KR"},
    "ru": {"RU", "UA", "BY", "KZ"},
    "nl": {"NL", "BE"},
    "sv": {"SE"},
    "pl": {"PL"},
    "tr": {"TR"},
    "hi": {"IN"},
    "zh": {"CN", "TW", "HK"},
}


class LanguageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.detector = (
            LanguageDetectorBuilder.from_languages(*_LINGUA_LANGUAGES)
            .with_preloaded_language_models()
            .build()
        )

    def isrc_matches_language(self, isrc: str | None, lang_iso: str) -> bool:
        if not isrc or len(isrc) < 2:
            return False
        return isrc[:2].upper() in _ISRC_LANGUAGE_MAP.get(lang_iso, set())

    def _detect_top_two(self, text: str) -> tuple[str | None, float, float]:
        confidences = self.detector.compute_language_confidence_values(text)
        if not confidences:
            return None, 0.0, 0.0
        top_iso = _LINGUA_TO_ISO.get(confidences[0].language)
        top_val = round(confidences[0].value, 4)
        second_val = round(confidences[1].value, 4) if len(confidences) > 1 else 0.0
        return top_iso, top_val, second_val

    def classify(
        self, lookup: LyricsLookupResult, isrc: str | None = None
    ) -> LanguageResult:
        if lookup.is_instrumental:
            return LanguageResult(language="instrumental", confidence=1.0, source="instrumental")

        if not lookup.lyrics:
            if lookup.transient_error:
                return LanguageResult(language="unclassified", confidence=0.0, source="provider_error")
            return LanguageResult(language="unclassified", confidence=0.0, source="no_lyrics")

        lyrics = strip_lyrics_noise(lookup.lyrics)

        # Non-Latin scripts in lyrics are unambiguous even if short
        script_lang = detect_script_language(lyrics, isrc=isrc)
        if script_lang and len("".join(lyrics.split())) >= 20:
            return LanguageResult(language=script_lang, confidence=0.98, source="lyrics_nlp")

        if not has_sufficient_lyrics(
            lyrics,
            min_chars=self.settings.min_lyrics_chars,
            min_unique_words=self.settings.min_unique_words,
        ):
            return LanguageResult(language="unclassified", confidence=0.0, source="too_short")

        top_iso, top_val, second_val = self._detect_top_two(lyrics)
        if not top_iso:
            return LanguageResult(language="unclassified", confidence=0.0, source="low_confidence")

        margin = round(top_val - second_val, 4)

        # Layer 1: Calibrated Threshold + Margin (fixes PT/ES probability split in Lingua)
        if (
            top_val >= self.settings.language_confidence_threshold
            and margin >= self.settings.language_confidence_margin
        ):
            return LanguageResult(language=top_iso, confidence=top_val, source="lyrics_nlp")

        # Layer 2: Moderate confidence + ISRC corroboration
        if (
            top_val >= self.settings.isrc_fallback_threshold
            and margin >= self.settings.isrc_fallback_margin
            and self.isrc_matches_language(isrc, top_iso)
        ):
            return LanguageResult(language=top_iso, confidence=top_val, source="lyrics_nlp+isrc")

        return LanguageResult(language="unclassified", confidence=top_val, source="low_confidence")

    def classify_from_metadata(self, track: TrackInfo) -> LanguageResult | None:
        """High-precision fallback used ONLY when no lyrics are available."""
        title = clean_title(track.name)
        if not title:
            return None

        # 1. Unambiguous non-Latin script in title (Japanese, Korean, Cyrillic, Arabic, Hindi, Chinese)
        script_lang = detect_script_language(title, isrc=track.isrc)
        if script_lang:
            return LanguageResult(language=script_lang, confidence=0.95, source="title_script")

        words = [w for w in title.split() if len(w) > 1]
        top_iso, top_val, second_val = self._detect_top_two(title)
        margin = round(top_val - second_val, 4)

        # 2. Language-exclusive diacritics (Portuguese ã/õ, Spanish ñ/¿/¡)
        if has_pt_exclusive_diacritics(title) and (
            (top_iso == "pt" and top_val >= 0.50) or self.isrc_matches_language(track.isrc, "pt")
        ):
            return LanguageResult(language="pt", confidence=max(top_val, 0.80), source="title_diacritics")

        if has_es_exclusive_chars(title) and (
            (top_iso == "es" and top_val >= 0.50) or self.isrc_matches_language(track.isrc, "es")
        ):
            return LanguageResult(language="es", confidence=max(top_val, 0.80), source="title_diacritics")

        # 3. Multi-word title (3+ words) with strong NLP + matching ISRC country
        if (
            len(words) >= 3
            and top_iso
            and top_val >= 0.75
            and margin >= 0.30
            and self.isrc_matches_language(track.isrc, top_iso)
        ):
            return LanguageResult(language=top_iso, confidence=top_val, source="title+isrc")

        return None

    def title_conflicts_with_language(self, title: str, expected_lang: str) -> bool:
        """Safety guard for Artist Consensus: blocks inheriting PT/ES if title is clearly another language."""
        cleaned = clean_title(title)
        script_lang = detect_script_language(cleaned)
        if script_lang and script_lang != expected_lang:
            return True

        words = [w for w in cleaned.split() if len(w) > 1]
        if len(words) < 2:
            return False

        top_iso, top_val, second_val = self._detect_top_two(cleaned)
        if top_iso and top_iso != expected_lang and top_val >= 0.82 and (top_val - second_val) >= 0.45:
            return True
        return False