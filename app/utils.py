import re
from typing import Optional


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
