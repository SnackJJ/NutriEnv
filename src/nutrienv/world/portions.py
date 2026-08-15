"""Turn a household-portion phrase into grams by table lookup.

Env does not parse natural language and no Action calls this. It exists so a
Generator or a harness can turn "half a cup of milk" into a number the same way
every time, instead of asking a model to do arithmetic over a units table.

The grammar is deliberately small and total: it never raises, and it returns
``None`` whenever it is not sure. ``None`` means "ask for grams", not "zero".
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

__all__ = ["resolve_portion", "UNIT_SYNONYMS", "GRAM_UNITS", "OUNCE_GRAMS", "OUNCE_UNITS"]

#: Unit words that already mean grams, so they need no per-food entry.
GRAM_UNITS = frozenset({"g", "gram", "grams", "gm"})

#: Avoirdupois ounce, published by Env so gold unit_convert is not a factory secret.
OUNCE_GRAMS = 28.35
OUNCE_UNITS = frozenset({"oz", "ounce", "ounces"})

#: Spoken unit -> the key a food's ``portions`` table uses.
UNIT_SYNONYMS: dict[str, str] = {
    "cup": "cup", "cups": "cup", "c": "cup",
    "tbsp": "tbsp", "tbsps": "tbsp", "tbs": "tbsp", "tb": "tbsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "tsps": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "piece": "piece", "pieces": "piece", "each": "piece",
    "unit": "piece", "units": "piece",
    "slice": "slice", "slices": "slice",
    "can": "can", "cans": "can",
}

_WORD_NUMBERS: dict[str, float] = {
    "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0, "six": 6.0,
    "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0, "eleven": 11.0,
    "twelve": 12.0,
}

_FRACTION_WORDS: dict[str, float] = {
    "half": 0.5, "halves": 0.5,
    "quarter": 0.25, "quarters": 0.25,
    "third": 1.0 / 3.0, "thirds": 1.0 / 3.0,
}

#: Words that carry no quantity. Anything else unrecognised means give up.
_FILLERS = frozenset(
    {"a", "an", "the", "of", "about", "approx", "approximately", "roughly", "around"}
)

_UNICODE_FRACTIONS = {"½": " 1/2 ", "¼": " 1/4 ", "¾": " 3/4 ", "⅓": " 1/3 ", "⅔": " 2/3 "}

_SPLIT = re.compile(r"[^a-z0-9./-]+")
_WORD_HYPHEN = re.compile(r"(?<=[a-z])-(?=[a-z])")
_DIGIT_LETTER = re.compile(r"(?<=\d)(?=[a-z])")


def resolve_portion(food_id: str, phrase: str, catalog: dict) -> float | None:
    """Grams meant by ``phrase`` for ``food_id``, or ``None`` if unresolvable.

    ``resolve_portion("milk_whole", "half a cup", catalog)`` is ``122.0``: the
    food's own ``portions["cup"]`` of 244 g, halved.

    Returns ``None`` for an unknown food, a measure the food does not define
    (a *slice* of milk), a quantity the grammar cannot parse, or a bare number
    with no unit. A phrase with no quantity at all reads as one: "a cup" and
    "cup" are both 1.
    """
    if not isinstance(food_id, str) or not isinstance(phrase, str):
        return None
    if not isinstance(catalog, Mapping):
        return None
    entry = catalog.get(food_id)
    if not isinstance(entry, dict):
        return None
    portions = entry.get("portions") or {}
    if not isinstance(portions, dict):
        return None

    tokens = _tokenize(phrase)
    for index, token in enumerate(tokens):
        if token in GRAM_UNITS:
            grams_per_unit: object = 1.0
        elif token in OUNCE_UNITS:
            grams_per_unit = OUNCE_GRAMS
        else:
            key = UNIT_SYNONYMS.get(token)
            if key is None or key not in portions:
                continue
            grams_per_unit = portions[key]

        if isinstance(grams_per_unit, bool) or not isinstance(grams_per_unit, (int, float)):
            return None
        if not math.isfinite(grams_per_unit) or grams_per_unit <= 0:
            return None

        quantity = _parse_quantity(tokens[:index])
        if quantity is None or quantity <= 0:
            return None
        return round(quantity * float(grams_per_unit), 2)
    return None


def _tokenize(phrase: str) -> list[str]:
    text = phrase.lower()
    for glyph, ascii_form in _UNICODE_FRACTIONS.items():
        text = text.replace(glyph, ascii_form)
    text = _WORD_HYPHEN.sub(" ", text)  # "one-half" -> "one half"
    text = _DIGIT_LETTER.sub(" ", text)  # "150g" -> "150 g"
    # A minus sign survives tokenizing so "-1 cups" parses as a negative
    # quantity and is rejected, rather than silently reading as "1 cups".
    return [token for token in (raw.strip(".") for raw in _SPLIT.split(text)) if token]


def _parse_quantity(tokens: list[str]) -> float | None:
    """Sum the quantity words before the unit. ``None`` if anything is unknown.

    A fraction word multiplies a number directly in front of it ("three
    quarters" is 0.75) unless an "and" separates them ("one and a half" is 1.5).
    """
    total: float | None = None
    pending: float | None = None
    joined = False

    for token in tokens:
        if token == "and":
            total, pending = _commit(total, pending)
            joined = True
            continue
        if token in _FILLERS:
            continue

        if token in _FRACTION_WORDS:
            value = _FRACTION_WORDS[token]
            if pending is not None and not joined:
                value *= pending
                pending = None
            total, pending = _commit(total, pending)
            total = value if total is None else total + value
            joined = False
            continue

        value = _parse_number(token)
        if value is None:
            return None
        total, pending = _commit(total, pending)
        pending = value
        joined = False

    total, _ = _commit(total, pending)
    return 1.0 if total is None else total


def _commit(total: float | None, pending: float | None) -> tuple[float | None, None]:
    if pending is None:
        return total, None
    return (pending if total is None else total + pending), None


def _parse_number(token: str) -> float | None:
    if token in _WORD_NUMBERS:
        return _WORD_NUMBERS[token]
    if "/" in token:
        numerator, _, denominator = token.partition("/")
        try:
            top, bottom = float(numerator), float(denominator)
        except ValueError:
            return None
        if bottom == 0 or not math.isfinite(top) or not math.isfinite(bottom):
            return None
        return top / bottom
    try:
        value = float(token)
    except ValueError:
        return None
    return value if math.isfinite(value) else None
