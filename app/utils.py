import difflib
import re
from typing import List, Optional


def normalize_phone(phone_number: str) -> str:
    """
    Guards against a real failure mode: '+' is the URL-encoding character for
    a space, so a client that doesn't percent-encode it (or a proxy that
    mangles it) turns 'whatsapp:+407...' into 'whatsapp: 407...' silently.
    Applied consistently at every entry point so lookups and writes always
    agree on the same stored format.
    """
    return phone_number.strip().replace(" ", "+")


FALLBACK_CATEGORY_NAME = "Altele"  # kept for app/sheets.py, which only ever reads Romanian spreadsheets
# One fallback category name per app language (see app/quiz.py FALLBACK_NAMES_BY_LANG) -
# a user's fallback category is named for whichever language was active at signup/quiz
# time, so matching has to recognize all of them, not just the Romanian original.
FALLBACK_CATEGORY_NAMES = {"altele", "other", "otros", "autres"}
CATEGORY_MATCH_CUTOFF = 0.7


def best_category_match(category_word: Optional[str], category_names: List[str]) -> Optional[str]:
    """
    Same fuzzy-matching rule as the Google Sheet mirror (see app/sheets.py):
    typos are fine, but an unrelated word (a merchant name, say) falls back
    to the user's "Other"-equivalent category rather than risk filing it
    under the wrong one.
    """
    fallback = next((n for n in category_names if n.lower() in FALLBACK_CATEGORY_NAMES), None)

    if not category_word:
        return fallback

    names_lower = [n.lower() for n in category_names]
    match = difflib.get_close_matches(category_word.lower(), names_lower, n=1, cutoff=CATEGORY_MATCH_CUTOFF)
    if not match:
        return fallback

    return category_names[names_lower.index(match[0])]


CURRENCY_WORDS = re.compile(r"\b(lei|ron|eur|usd)\b", re.IGNORECASE)


def parse_european_amount(raw: str) -> Optional[float]:
    """
    Parses amounts shaped like the user's budget spreadsheets: dot as the
    thousands separator, comma as the decimal separator, an optional
    currency word/symbol suffix, e.g. "1.000,00 lei" -> 1000.0,
    "350,00" -> 350.0, "300" -> 300.0. Returns None if nothing numeric is
    found (blank cells, stray text like a keyboard-mash row).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    text = CURRENCY_WORDS.sub("", text)
    text = text.replace("lei", "").replace("€", "").replace("$", "").strip()
    if not text:
        return None

    # Reject anything that isn't digits/separators/sign - filters out noise
    # rows like "ASDFGHJ" or "H53+=-astyuiop[]\" that otherwise slip through.
    if not re.fullmatch(r"-?[\d.,\s]+", text):
        return None

    text = text.replace(" ", "")
    if "," in text:
        # Comma is the decimal separator; strip thousands dots first.
        text = text.replace(".", "").replace(",", ".")
    # else: plain integer or already dot-decimal - leave as is.

    try:
        value = float(text)
    except ValueError:
        return None
    return value
