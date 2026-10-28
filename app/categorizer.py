"""
Turns a bank transaction into one of the user's budget categories.

Bank descriptions are noisy and inconsistent ("CARD PAYMENT TO LIDL 0412
BUCURESTI", "Lidl Sibiu", "LIDL*2311"), so matching happens on a normalised
merchant key rather than the raw text - that is what lets one learned rule
cover every future visit to the same shop.

Three sources of truth, in order of how much they are trusted:

1. A MerchantRule the user wrote by filing a transaction themselves. Always
   wins: it is the only source that knows this particular person's intent
   (the same supermarket can be "Groceries" for one user and "Work lunch"
   for another).
2. A keyword hint - a built-in table of merchants common in Romania mapped
   to a generic bucket, which is then fuzzy-matched against the names the
   user actually has.
3. The card network's MCC, when the bank sends one. Coarser than the
   keyword table but it covers merchants nobody has ever heard of.

If none of them resolves, this returns None rather than guessing. Nothing
silently lands in "Altele": an unresolved transaction waits in the confirm
inbox, and filing it there writes the rule that makes the next one
automatic.
"""

import hashlib
import re
import unicodedata
from typing import Optional

# Boilerplate banks wrap around the merchant name. Stripped before anything
# else, so "Card payment to Lidl" and "Lidl" produce the same key.
NOISE_PREFIXES = (
    "card payment to",
    "card payment at",
    "card payment",
    "payment to",
    "payment from",
    "plata card",
    "plata la",
    "cumparare pos",
    "cumparare",
    "tranzactie pos",
    "pos ",
    "to ",
    "la ",
)

# Trailing store/terminal noise: branch numbers, city codes, "*1234" suffixes.
TRAILING_NOISE = re.compile(r"[\*#]?\d{2,}\b")


def normalize_merchant(text: Optional[str]) -> str:
    """
    "CARD PAYMENT TO LIDL 0412 BUCURESTI" -> "lidl bucuresti".

    Diacritics are folded because the same merchant arrives both with and
    without them depending on the channel, and an unmatched rule is worse
    than a slightly lossy key.
    """
    if not text:
        return ""

    folded = unicodedata.normalize("NFKD", str(text))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    lowered = folded.lower().strip()

    changed = True
    while changed:
        changed = False
        for prefix in NOISE_PREFIXES:
            if lowered.startswith(prefix):
                lowered = lowered[len(prefix):].strip()
                changed = True

    lowered = TRAILING_NOISE.sub(" ", lowered)
    lowered = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def display_merchant(text: Optional[str]) -> Optional[str]:
    """A human-readable merchant name for the inbox, from the same cleanup."""
    key = normalize_merchant(text)
    if not key:
        return None
    return " ".join(word.capitalize() for word in key.split())


# Generic buckets. These are matched fuzzily against whatever the user named
# their categories, so the exact wording here only has to be close enough -
# both the Romanian and English spellings are listed for that reason.
GROCERIES = ("alimente", "mancare", "groceries", "food", "supermarket")
DINING = ("restaurant", "restaurante", "iesiri", "dining", "eating out", "cafe")
TRANSPORT = ("transport", "masina", "car", "fuel", "benzina", "travel")
UTILITIES = ("utilitati", "utilities", "facturi", "bills", "internet", "telefon")
SUBSCRIPTIONS = ("abonamente", "subscriptions", "entertainment", "divertisment")
HEALTH = ("sanatate", "health", "farmacie", "pharmacy", "medical")
CLOTHING = ("haine", "clothes", "clothing", "imbracaminte", "shopping")
HOME = ("casa", "home", "chirie", "rent", "household")
EDUCATION = ("educatie", "education", "cursuri", "school", "carti", "books")
BEAUTY = ("frumusete", "beauty", "ingrijire", "personal care")

# Merchants seen often enough on a Romanian card to be worth shipping
# pre-learned, so a fresh connection does not dump 90 days into the inbox at
# once. Matched as substrings of the normalised key.
KEYWORD_HINTS = {
    # groceries
    "lidl": GROCERIES, "kaufland": GROCERIES, "mega image": GROCERIES, "megaimage": GROCERIES,
    "profi": GROCERIES, "carrefour": GROCERIES, "auchan": GROCERIES, "penny": GROCERIES,
    "selgros": GROCERIES, "metro": GROCERIES, "la doi pasi": GROCERIES, "freshful": GROCERIES,
    "supeco": GROCERIES, "cora": GROCERIES,
    # dining / delivery
    "glovo": DINING, "tazz": DINING, "bolt food": DINING, "foodpanda": DINING,
    "mcdonald": DINING, "kfc": DINING, "starbucks": DINING, "5 to go": DINING,
    "taco bell": DINING, "subway": DINING, "burger": DINING, "pizza": DINING,
    "cafe": DINING, "coffee": DINING, "restaurant": DINING, "bistro": DINING,
    # transport
    "uber": TRANSPORT, "bolt": TRANSPORT, "blackcab": TRANSPORT, "clever": TRANSPORT,
    "omv": TRANSPORT, "petrom": TRANSPORT, "rompetrol": TRANSPORT, "mol": TRANSPORT,
    "lukoil": TRANSPORT, "socar": TRANSPORT, "stb": TRANSPORT, "metrorex": TRANSPORT,
    "cfr": TRANSPORT, "wizz": TRANSPORT, "ryanair": TRANSPORT, "tarom": TRANSPORT,
    "blue air": TRANSPORT, "bolt eu": TRANSPORT,
    # utilities / telecom
    "enel": UTILITIES, "e on": UTILITIES, "eon": UTILITIES, "engie": UTILITIES,
    "hidroelectrica": UTILITIES, "apa nova": UTILITIES, "digi": UTILITIES,
    "rcs rds": UTILITIES, "orange": UTILITIES, "vodafone": UTILITIES, "telekom": UTILITIES,
    "electrica": UTILITIES,
    # subscriptions / entertainment
    "netflix": SUBSCRIPTIONS, "spotify": SUBSCRIPTIONS, "youtube": SUBSCRIPTIONS,
    "hbo": SUBSCRIPTIONS, "disney": SUBSCRIPTIONS, "apple com": SUBSCRIPTIONS,
    "google": SUBSCRIPTIONS, "steam": SUBSCRIPTIONS, "playstation": SUBSCRIPTIONS,
    "xbox": SUBSCRIPTIONS, "openai": SUBSCRIPTIONS, "anthropic": SUBSCRIPTIONS,
    "github": SUBSCRIPTIONS, "icloud": SUBSCRIPTIONS, "cinema city": SUBSCRIPTIONS,
    # health
    "catena": HEALTH, "dona": HEALTH, "help net": HEALTH, "sensiblu": HEALTH,
    "farmacia": HEALTH, "farmacie": HEALTH, "regina maria": HEALTH, "medlife": HEALTH,
    "synevo": HEALTH, "sanador": HEALTH, "dr max": HEALTH,
    # clothing / general retail
    "decathlon": CLOTHING, "zara": CLOTHING, "h m": CLOTHING, "pepco": CLOTHING,
    "lc waikiki": CLOTHING, "about you": CLOTHING, "zalando": CLOTHING,
    "reserved": CLOTHING, "sinsay": CLOTHING, "cropp": CLOTHING, "answear": CLOTHING,
    "nike": CLOTHING, "adidas": CLOTHING,
    # home / big ticket
    "emag": HOME, "altex": HOME, "dedeman": HOME, "leroy merlin": HOME,
    "ikea": HOME, "jysk": HOME, "hornbach": HOME, "brico": HOME,
    # beauty
    "sephora": BEAUTY, "douglas": BEAUTY, "notino": BEAUTY, "yves rocher": BEAUTY,
    # education
    "udemy": EDUCATION, "coursera": EDUCATION, "carturesti": EDUCATION,
    "libris": EDUCATION, "elefant": EDUCATION,
}

# Merchant category codes, as the card networks define them. Ranges rather
# than every code: this is the fallback for merchants the table above has
# never seen, so breadth matters more than precision.
MCC_HINTS = {
    GROCERIES: {"5411", "5422", "5441", "5451", "5462", "5499"},
    DINING: {"5812", "5813", "5814"},
    TRANSPORT: {"4111", "4121", "4131", "4511", "4582", "4789", "5541", "5542", "7512", "7523"},
    UTILITIES: {"4812", "4814", "4816", "4899", "4900"},
    SUBSCRIPTIONS: {"5815", "5816", "5817", "5818", "7832", "7841", "7994", "7996"},
    HEALTH: {"5912", "5975", "8011", "8021", "8031", "8042", "8049", "8062", "8071", "8099"},
    CLOTHING: {"5611", "5621", "5631", "5641", "5651", "5661", "5691", "5699", "5940", "5941"},
    HOME: {"5200", "5211", "5231", "5251", "5261", "5712", "5713", "5719", "5722", "5732"},
    EDUCATION: {"5942", "5943", "8211", "8220", "8241", "8249", "8299"},
    BEAUTY: {"5977", "7230", "7297", "7298"},
}

# Tells a transfer or an incoming payment apart from a purchase. These never
# become expenses - filing a salary as spending would wreck every total.
TRANSFER_WORDS = (
    "transfer", "top up", "topup", "topping up", "incasare", "alimentare",
    "exchange", "schimb valutar", "to savings", "vault", "salary", "salariu",
    "refund", "rambursare", "cashback", "retragere", "withdrawal", "atm",
)

# How close a bucket word has to be to one of the user's category names.
# Same cutoff as the chat parser uses, for the same reason: a near-miss is
# a typo, a far miss is a different thing entirely.
MATCH_CUTOFF = 0.72


def _match_bucket(bucket, category_names: list) -> Optional[str]:
    """
    The user's category name closest to any word in `bucket`, or None.

    Substring hits are taken first ("Alimente & casa" contains "alimente"),
    with difflib only as the backstop, because a containment match is
    unambiguous where a ratio in the 0.7s sometimes is not.
    """
    import difflib

    lowered = [name.lower() for name in category_names]

    for word in bucket:
        for index, name in enumerate(lowered):
            if word in name or name in word:
                return category_names[index]

    for word in bucket:
        match = difflib.get_close_matches(word, lowered, n=1, cutoff=MATCH_CUTOFF)
        if match:
            return category_names[lowered.index(match[0])]

    return None


def looks_like_transfer(text: Optional[str]) -> bool:
    key = normalize_merchant(text)
    return any(word in key for word in TRANSFER_WORDS)


def suggest_category(
    *,
    merchant_key: str,
    mcc: Optional[str],
    category_names: list,
    rules: dict,
) -> Optional[str]:
    """
    The category name to file this merchant under, or None to ask the user.

    `rules` maps a learned merchant key to a category name; it is checked
    before anything built in, and an exact key hit short-circuits the rest.
    """
    if not category_names:
        return None

    if merchant_key:
        if merchant_key in rules:
            return rules[merchant_key]
        # A learned rule also covers longer variants of itself, so "lidl"
        # keeps matching once the bank starts appending a new branch name.
        for pattern, category_name in rules.items():
            if pattern and (pattern in merchant_key or merchant_key in pattern):
                return category_name

    for keyword, bucket in KEYWORD_HINTS.items():
        if keyword in merchant_key:
            matched = _match_bucket(bucket, category_names)
            if matched:
                return matched

    if mcc:
        code = str(mcc).strip()
        for bucket, codes in MCC_HINTS.items():
            if code in codes:
                matched = _match_bucket(bucket, category_names)
                if matched:
                    return matched

    return None


def transaction_fingerprint(transaction: dict) -> str:
    """
    A stable id for a transaction the bank did not give one.

    Built from the fields that identify the purchase itself rather than the
    response it arrived in, so the same transaction hashes the same way on
    every sync and the dedupe holds.
    """
    amount = ((transaction.get("transactionAmount") or {}).get("amount")) or ""
    parts = [
        str(transaction.get("bookingDate") or transaction.get("valueDate") or ""),
        str(amount),
        str((transaction.get("transactionAmount") or {}).get("currency") or ""),
        normalize_merchant(
            transaction.get("remittanceInformationUnstructured")
            or transaction.get("creditorName")
            or transaction.get("debtorName")
            or ""
        ),
    ]
    return "fp_" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
