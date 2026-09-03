"""
A short signup quiz that picks 5 starting budget categories tailored to how
someone actually spends, instead of a generic Supermarket/Utilities/Transport
set that may not fit them at all. Each answer option carries "tags"; scoring
just sums tag matches against a fixed category pool and takes the top 4 -
"Altele" (Other) is always the 5th, guaranteed, since app/utils.py's
fuzzy-matching fallback (best_category_match) depends on a category with
that exact name existing for anything that doesn't match well.
"""

from collections import Counter
from typing import List, Tuple

FALLBACK_ICON = "\U0001F4E6"

# Display name for the guaranteed fallback category, one per language the
# frontend supports (see web/i18n.js LOCALE_MAP). app/utils.py's fuzzy-match
# fallback (best_category_match) and app/sheets.py match against ALL of
# these names, case-insensitively, so it still finds the category regardless
# of which one it was created with.
FALLBACK_NAMES_BY_LANG = {
    "en": "Other",
    "es": "Otros",
    "fr": "Autres",
    "ro": "Altele",
}

FALLBACK_CATEGORY = (FALLBACK_NAMES_BY_LANG["en"], FALLBACK_ICON)  # default for callers that don't know the user's language


def fallback_category(lang: str) -> Tuple[str, str]:
    name = FALLBACK_NAMES_BY_LANG.get(lang, FALLBACK_NAMES_BY_LANG["en"])
    return (name, FALLBACK_ICON)

CATEGORY_POOL = [
    {"name": "Groceries", "icon": "\U0001F6D2", "tags": {"home", "cooking", "budget"}},
    {"name": "Dining Out", "icon": "\U0001F37D️", "tags": {"foodie", "social", "convenience"}},
    {"name": "Coffee & Snacks", "icon": "☕", "tags": {"foodie", "daily", "social"}},
    {"name": "Transport", "icon": "\U0001F697", "tags": {"commute", "mobility"}},
    {"name": "Travel", "icon": "✈️", "tags": {"travel", "adventure"}},
    {"name": "Rent & Utilities", "icon": "\U0001F3E0", "tags": {"home", "stability"}},
    {"name": "Subscriptions", "icon": "\U0001F4FA", "tags": {"homebody", "entertainment", "digital"}},
    {"name": "Nightlife & Fun", "icon": "\U0001F389", "tags": {"social", "fun"}},
    {"name": "Fitness & Health", "icon": "\U0001FA7A", "tags": {"health", "active"}},
    {"name": "Shopping", "icon": "\U0001F6CD️", "tags": {"style", "shopping"}},
    {"name": "Gadgets & Tech", "icon": "\U0001F4BB", "tags": {"tech", "digital"}},
    {"name": "Family & Kids", "icon": "\U0001F476", "tags": {"family"}},
    {"name": "Pets", "icon": "\U0001F436", "tags": {"pets"}},
    {"name": "Education", "icon": "\U0001F4DA", "tags": {"learning", "student", "budget"}},
    {"name": "Savings & Investing", "icon": "\U0001F4B9", "tags": {"saver", "future"}},
    {"name": "Gifts & Donations", "icon": "\U0001F381", "tags": {"generous", "social"}},
]

QUESTIONS = [
    {
        "id": "weekend",
        "text": "How do you usually spend your weekends?",
        "options": [
            {"id": "food", "text": "Trying new restaurants or cafes", "tags": {"foodie", "social"}},
            {"id": "travel", "text": "Traveling or day trips", "tags": {"travel", "adventure"}},
            {"id": "home", "text": "Relaxing at home with shows or games", "tags": {"homebody", "entertainment", "digital"}},
            {"id": "active", "text": "Working out or outdoors", "tags": {"health", "active"}},
        ],
    },
    {
        "id": "living",
        "text": "What's your living situation?",
        "options": [
            {"id": "alone", "text": "Living alone or renting", "tags": {"home", "stability"}},
            {"id": "family", "text": "Living with family or kids", "tags": {"family", "home"}},
            {"id": "student", "text": "Student", "tags": {"learning", "student", "budget"}},
            {"id": "pets", "text": "Living with pets", "tags": {"pets", "home"}},
        ],
    },
    {
        "id": "fun_money",
        "text": "Where does most of your \"fun money\" go?",
        "options": [
            {"id": "style", "text": "Clothes and style", "tags": {"style", "shopping"}},
            {"id": "tech", "text": "Gadgets and tech", "tags": {"tech", "digital"}},
            {"id": "nightlife", "text": "Nightlife and events", "tags": {"social", "fun"}},
            {"id": "saving", "text": "Saving or investing it", "tags": {"saver", "future"}},
        ],
    },
    {
        "id": "commute",
        "text": "How do you get around day to day?",
        "options": [
            {"id": "car", "text": "Car", "tags": {"mobility", "commute"}},
            {"id": "transit", "text": "Public transit or rideshare", "tags": {"commute"}},
            {"id": "frequent_travel", "text": "I travel a lot for work or leisure", "tags": {"travel"}},
            {"id": "walk", "text": "Mostly walk or bike", "tags": {"active"}},
        ],
    },
]

_OPTION_TAGS = {(q["id"], o["id"]): o["tags"] for q in QUESTIONS for o in q["options"]}


def public_questions() -> List[dict]:
    """Question/option text only - no tags - for the quiz screen."""
    return [
        {"id": q["id"], "text": q["text"], "options": [{"id": o["id"], "text": o["text"]} for o in q["options"]]}
        for q in QUESTIONS
    ]


def compute_categories(answers: List[Tuple[str, str]], lang: str = "en") -> List[Tuple[str, str]]:
    """
    answers: [(question_id, option_id), ...]. Returns [(name, icon), ...] of
    length 5: the 4 best-scoring categories from the pool, plus the fallback
    category named for the given UI language.
    """
    tags = Counter()
    for question_id, option_id in answers:
        for tag in _OPTION_TAGS.get((question_id, option_id), set()):
            tags[tag] += 1

    scored = [(sum(tags[t] for t in c["tags"]), c) for c in CATEGORY_POOL]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    top = [(c["name"], c["icon"]) for _, c in scored[:4]]
    top.append(fallback_category(lang))
    return top
