import re
import unicodedata
from typing import Any

_TITLE_NOISE_RE = re.compile(
    r"\s*[\(\[]"
    r"(?:"
    r"(?:feat|ft|with)\b\.?[^\)\]]*"
    r"|(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?[^\)\]]*"
    r"|(?:live|acoustic|ao vivo|radio edit|deluxe|bonus|mono|stereo|single version|album version|explicit|clean|edit|remix)\b[^\)\]]*"
    r")"
    r"[\)\]]"
    r"|\s+-\s+(?:"
    r"(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?.*"
    r"|(?:live|acoustic|ao vivo|single version|radio edit|bonus track|deluxe|mono|stereo|remix)\b.*"
    r")$",
    flags=re.IGNORECASE,
)
_LYRICS_SECTION_HEADER_RE = re.compile(
    r"\[(?:verse(?:\s+\d+)?|chorus|refrain|bridge|intro|outro|pre-?chorus|hook|interlude)\]\s*",
    flags=re.IGNORECASE,
)
_LRC_TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}(?:\.\d{2,3})?\]\s*")
_NON_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|\bfeat\.?\b|\bft\.?\b|\band\b|\bx\b)\s*", flags=re.IGNORECASE
)


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
    text: str, min_chars: int = 80, min_unique_words: int = 12
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
