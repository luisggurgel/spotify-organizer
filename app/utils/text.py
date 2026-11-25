import re
import unicodedata
from typing import Any

_TITLE_NOISE_RE = re.compile(
    r"\s*[\(\[]"
    r"(?:"
    r"(?:feat|ft|with|part|participa[cç][aã]o)\b\.?[^\)\]]*"
    r"|(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?[^\)\]]*"
    r"|(?:live|acoustic|ac[uú]stico|ao vivo|radio edit|deluxe|bonus|mono|stereo|single version|album version|vers[aã]o|explicit|clean|edit|remix|sped up|slowed|reverb)\b[^\)\]]*"
    r")"
    r"[\)\]]"
    r"|\s+-\s+(?:"
    r"(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?.*"
    r"|(?:live|acoustic|ac[uú]stico|ao vivo|single version|radio edit|bonus track|deluxe|mono|stereo|remix|sped up|slowed)\b.*"
    r")$",
    flags=re.IGNORECASE,
)
_LYRICS_SECTION_HEADER_RE = re.compile(r"\[[^\]]{1,40}\]")
_LRC_TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}(?:\.\d{2,3})?\]\s*")
_NON_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|\bfeat\.?\b|\bft\.?\b|\bpart\.?\b|\band\b|\bx\b)\s*",
    flags=re.IGNORECASE,
)

_HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_PT_EXCLUSIVE_DIACRITICS_RE = re.compile(r"[ãõÃÕ]")
_ES_EXCLUSIVE_CHARS_RE = re.compile(r"[ñÑ¿¡]")


def clean_title(title: str) -> str:
    cleaned = _TITLE_NOISE_RE.sub("", title).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or title.strip()


def normalize_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = no_accents.lower().replace("_", "")
    return _NON_WORD_RE.sub("", lowered)


def strip_lyrics_noise(text: str) -> str:
    text = _LRC_TIMESTAMP_RE.sub("", text)
    text = _LYRICS_SECTION_HEADER_RE.sub("", text)
    return text.strip()


def has_sufficient_lyrics(
    text: str, min_chars: int = 45, min_unique_words: int = 7
) -> bool:
    clean_chars = len("".join(text.split()))
    if clean_chars < min_chars:
        return False
    unique_words = {w.lower() for w in _WORD_RE.findall(text) if len(w) > 1}
    return len(unique_words) >= min_unique_words


def artists_match(expected: str, candidate: str) -> bool:
    exp_norm = normalize_key(expected)
    cand_norm = normalize_key(candidate)
    if not exp_norm or not cand_norm:
        return False
    if exp_norm == cand_norm:
        return True

    for part in _ARTIST_SPLIT_RE.split(candidate):
        if normalize_key(part) == exp_norm:
            return True

    if len(exp_norm) >= 4 and len(cand_norm) >= 4:
        return exp_norm in cand_norm or cand_norm in exp_norm
    return False


def titles_match(expected: str, candidate: str) -> bool:
    exp_norm = normalize_key(clean_title(expected))
    cand_norm = normalize_key(clean_title(candidate))
    if not exp_norm or not cand_norm:
        return False
    if exp_norm == cand_norm:
        return True
    if len(exp_norm) >= 5 and len(cand_norm) >= 5:
        return exp_norm in cand_norm or cand_norm in exp_norm
    return False


def detect_script_language(text: str, isrc: str | None = None) -> str | None:
    if _HIRAGANA_KATAKANA_RE.search(text):
        return "ja"
    if _HANGUL_RE.search(text):
        return "ko"
    if _CYRILLIC_RE.search(text):
        return "ru"
    if _ARABIC_RE.search(text):
        return "ar"
    if _DEVANAGARI_RE.search(text):
        return "hi"
    if _CJK_RE.search(text):
        cc = (isrc or "")[:2].upper()
        if cc == "JP":
            return "ja"
        return "zh"
    return None


def has_pt_exclusive_diacritics(text: str) -> bool:
    return bool(_PT_EXCLUSIVE_DIACRITICS_RE.search(text))


def has_es_exclusive_chars(text: str) -> bool:
    return bool(_ES_EXCLUSIVE_CHARS_RE.search(text))


def parse_retry_after(header_value: str | None, default: float = 2.0) -> float:
    if not header_value:
        return default
    try:
        val = float(header_value.strip())
        return max(0.5, min(val, 120.0))
    except ValueError:
        return default


def chunked(items: list[Any], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]