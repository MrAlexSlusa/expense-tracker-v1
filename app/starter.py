"""
The categories a brand-new account starts with.

This used to be a four-question quiz that scored tag matches to pick five
categories "tailored to how someone actually spends". It was answered once,
by someone who had not seen the app yet, to decide something they can change
in two taps afterwards - so it asked personal questions to buy almost
nothing, and stood between signing up and the first expense. The app now
hands over a sensible set immediately and lets the categories be edited,
renamed or deleted like any other.

The set is the same everywhere; only its wording follows the signup
language, because a Romanian account opening on "Groceries" reads like
someone else's app.

"Other" (Altele / Otros / Autres) is always last and always present: the
spreadsheet importer matches against these names case-insensitively, so
anything it cannot place has somewhere to land.
"""

from typing import List, Tuple

FALLBACK_ICON = "\U0001F4E6"

# One per language the frontend supports (see web/i18n.js LOCALE_MAP).
FALLBACK_NAMES_BY_LANG = {
    "en": "Other",
    "es": "Otros",
    "fr": "Autres",
    "ro": "Altele",
}

# Five everyday categories plus the fallback. Deliberately broad: a category
# that is too wide gets split in a moment, while one nobody recognises just
# sits there unused.
STARTER_CATEGORIES_BY_LANG = {
    "en": [
        ("Groceries", "\U0001F6D2"),
        ("Eating out", "\U0001F37D️"),
        ("Transport", "\U0001F697"),
        ("Home & bills", "\U0001F3E0"),
        ("Subscriptions", "\U0001F4FA"),
    ],
    "ro": [
        ("Alimente", "\U0001F6D2"),
        ("Mancare in oras", "\U0001F37D️"),
        ("Transport", "\U0001F697"),
        ("Casa si facturi", "\U0001F3E0"),
        ("Abonamente", "\U0001F4FA"),
    ],
    "es": [
        ("Supermercado", "\U0001F6D2"),
        ("Comer fuera", "\U0001F37D️"),
        ("Transporte", "\U0001F697"),
        ("Casa y facturas", "\U0001F3E0"),
        ("Suscripciones", "\U0001F4FA"),
    ],
    "fr": [
        ("Courses", "\U0001F6D2"),
        ("Restaurants", "\U0001F37D️"),
        ("Transport", "\U0001F697"),
        ("Maison et factures", "\U0001F3E0"),
        ("Abonnements", "\U0001F4FA"),
    ],
}


# Every spelling of the catch-all, lowercased. An account can already hold it
# under another language's name - it was created in that language, or topped
# up later in a different one - and a second catch-all beside the first is
# both confusing and ambiguous for the importer, which matches all of these.
FALLBACK_NAMES = {name.lower() for name in FALLBACK_NAMES_BY_LANG.values()}


def fallback_category(lang: str) -> Tuple[str, str]:
    """The catch-all category's name and icon for this language."""
    name = FALLBACK_NAMES_BY_LANG.get(lang, FALLBACK_NAMES_BY_LANG["en"])
    return (name, FALLBACK_ICON)


def starter_categories(lang: str) -> List[Tuple[str, str]]:
    """
    The six [(name, icon)] a new account is created with, in this language.

    An unknown language falls back to English rather than raising: a signup
    should never fail over a language tag.
    """
    everyday = STARTER_CATEGORIES_BY_LANG.get(lang, STARTER_CATEGORIES_BY_LANG["en"])
    return list(everyday) + [fallback_category(lang)]
