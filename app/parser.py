"""
Parses free-text WhatsApp messages into an (amount, category) pair.

Design choice: people won't remember a strict syntax, so this accepts loose,
natural phrasing rather than requiring something like "/expense 20 coffee".
If we can't confidently find an amount, we return None rather than guessing -
a silent wrong entry is worse than a message asking the user to rephrase.
"""

import re
from dataclasses import dataclass
from typing import Optional

# Words that show intent but aren't part of the category itself.
FILLER_WORDS = {
    "spent", "spend", "paid", "pay", "for", "on", "expense", "cost",
    "bought", "buy", "lei", "ron", "eur", "usd", "$", "€",
}

AMOUNT_PATTERN = re.compile(r"(\d+(?:[.,]\d{1,2})?)")

# How someone might name a currency in passing, mapped to its ISO code. Only
# the currencies the app converts between - an unrecognised word is left to be
# read as part of the category, which is usually what it is.
CURRENCY_WORDS = {
    "lei": "RON", "leu": "RON", "ron": "RON",
    "eur": "EUR", "euro": "EUR", "euros": "EUR", "euri": "EUR", "€": "EUR",
    "usd": "USD", "dollar": "USD", "dollars": "USD", "dolari": "USD", "$": "USD",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "lire": "GBP", "£": "GBP",
}

# Longest-first so "euros" isn't matched as "euro", and letter-bounded so the
# "usd" inside a word can't be mistaken for a currency.
CURRENCY_PATTERN = re.compile(
    r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(w) for w in CURRENCY_WORDS), key=len, reverse=True)) + r")(?![A-Za-z])",
    re.IGNORECASE,
)


@dataclass
class ParsedExpense:
    amount: float
    category: Optional[str]  # None if no category words were found
    currency: Optional[str] = None  # ISO code if the message named one, else None


def parse_expense_message(text: str) -> Optional[ParsedExpense]:
    text = text.strip()
    if not text:
        return None

    match = AMOUNT_PATTERN.search(text)
    if not match:
        return None

    amount_str = match.group(1).replace(",", ".")
    try:
        amount = float(amount_str)
    except ValueError:
        return None

    if amount <= 0:
        return None

    # Category = whatever words are left after removing the amount and filler words.
    remainder = text[:match.start()] + text[match.end():]

    # Read the currency from what's left after the amount, so "50 eur" and
    # "eur 50" both work and the digits can't be mistaken for a code.
    currency_match = CURRENCY_PATTERN.search(remainder)
    currency = CURRENCY_WORDS[currency_match.group(1).lower()] if currency_match else None

    words = [w for w in re.findall(r"[A-Za-z\u00C0-\u024F]+", remainder)]
    category_words = [w for w in words if w.lower() not in FILLER_WORDS and w.lower() not in CURRENCY_WORDS]
    category = " ".join(category_words).strip().lower() or None

    return ParsedExpense(amount=amount, category=category, currency=currency)
