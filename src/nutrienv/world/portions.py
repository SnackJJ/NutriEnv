"""Turn a household-portion phrase into grams by table lookup.

Env does not parse natural language and no Action calls this. It exists so a
Generator or a harness can turn "half a cup of milk" into a number the same way
every time, instead of asking a model to do arithmetic over a units table.

Spoken serving and size words get a table lookup, because real users do not
weigh food:

* ``"a serving of X"`` (also bowl/plate/portion/order) reads as the food's
  default FNDDS portion: FNDDS QNS (modifier 90000), else ``piece``, else
  ``slice``, else ``cup``. Catalog does not write a ``serving`` key; no
  per-food entry is needed, and a food that defines none of those has no
  serving ("a serving of olive oil" stays ``None``).
* ``"a sandwich"`` / ``"two burritos"`` treat the dish noun itself as the
  unit, one default serving each, but only when the food's own name contains
  that noun, so the grammar cannot invent a unit out of thin air.
* A bare food noun with no unit (``"one apple"``, ``"a banana"``,
  ``"two eggs"``) is that many ``piece`` rows of the named food. A cut or
  body-part noun with no portion key (``"a chicken breast"``) stays
  ``None``; the grammar does not guess cup or QNS.
* ``"thick"`` / ``"thin"`` / ``"regular"`` pick a different default serving
  of the same food (``portions.thick`` etc.). They are not household
  measures: a modifier next to slice/cup/piece/… is refused.
* State words after a unit (``dry`` / ``raw`` / ``uncooked`` / ``dried``)
  refuse: ``"1 oz dry"`` is not an ounce of the cooked food.

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

#: Spoken unit -> the key a food's ``portions`` table uses. A missing
#: ``serving`` key falls back to the food's default FNDDS portion, so dishes
#: need no per-food entry to be ordered "a serving of ...". Catalog does
#: not write a ``serving`` key by construction; the lookup is a hatch.
UNIT_SYNONYMS: dict[str, str] = {
    "cup": "cup", "cups": "cup", "c": "cup",
    "tbsp": "tbsp", "tbsps": "tbsp", "tbs": "tbsp", "tb": "tbsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "tsps": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "piece": "piece", "pieces": "piece", "each": "piece",
    "unit": "piece", "units": "piece",
    "slice": "slice", "slices": "slice",
    "can": "can", "cans": "can",
    "serving": "serving", "servings": "serving",
    "portion": "serving", "portions": "serving",
    "bowl": "serving", "plate": "serving", "order": "serving",
    "fl_oz": "fl_oz",  # after UNIT_BIGRAMS collapse
    "floz": "fl_oz",
}

#: Multi-word spoken units, collapsed before the unit scan so "fl oz" cannot
#: be eaten by the bare-ounce branch.
UNIT_BIGRAMS: dict[tuple[str, str], str] = {
    ("fl", "oz"): "fl_oz", ("fl", "ozs"): "fl_oz",
    ("fluid", "ounce"): "fl_oz", ("fluid", "ounces"): "fl_oz",
}

#: Size words that pick a different FNDDS row of the *same* food-as-unit
#: reading. Never a household measure: "a thick slice" is refused, because
#: the catalog's thick/thin keys are not slice sizes (see design doc 2.1).
MODIFIER_KEYS: dict[str, str] = {"thick": "thick", "thin": "thin", "regular": "regular"}

#: Size words FNDDS has no separate key for. Recognised only so the grammar
#: refuses instead of silently reading them as "one".
REFUSED_MODIFIERS = frozenset(
    {"large", "big", "huge", "jumbo", "giant", "small", "little", "medium",
     "mini", "miniature", "tiny"}
)

#: State words after a unit. The catalog food is the cooked/as-eaten form;
#: "1 oz dry" is a different quantity (design §6 5a), so the grammar asks.
_REFUSED_AFTER_UNIT = frozenset({
    "dry", "dried", "drying",
    "raw",
    "uncooked", "uncook",
})

#: Dish nouns people use as the unit of the dish itself: "a sandwich", "two
#: burritos". A noun only counts when the food's own name contains it.
DISH_NOUNS = frozenset({
    "sandwich", "burger", "burrito", "taco", "pizza", "omelet", "omelette",
    "curry", "stew", "chili", "soup", "salad", "wrap", "sub", "lasagna",
    "steak",
})

#: Cuts and body-part nouns. Without a matching portion key they are not a
#: countable piece; "a chicken breast" must not fall through to cup/QNS.
_CUT_NOUNS = frozenset({
    "breast", "breasts", "thigh", "thighs", "wing", "wings", "drumstick",
    "drumsticks", "chop", "chops", "loin", "tenderloin", "rib", "ribs",
    "shank", "brisket", "fillet", "filet", "cutlet", "cutlets",
})

#: Name crumbs that are not the food's countable noun.
_NAME_STOP = frozenset({
    "raw", "cooked", "fresh", "whole", "only", "meat", "with", "without",
    "skin", "added", "fat", "and", "the", "for", "from", "broilers",
    "fryers", "grilled", "steamed", "ripe", "plain", "extra", "virgin",
    "ns", "nfs",
})

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

    tokens = _collapse_unit_bigrams(_tokenize(phrase))
    if _refuses_modifiers(tokens):
        return None
    for index, token in enumerate(tokens):
        span = tokens[:index]
        modifier = _span_modifier(span)
        if token in GRAM_UNITS:
            if modifier is not None:
                return None
            grams_per_unit: object = 1.0
        elif token in OUNCE_UNITS:
            if modifier is not None:
                return None
            grams_per_unit = OUNCE_GRAMS
        else:
            key = UNIT_SYNONYMS.get(token)
            if key is None:
                continue
            if modifier is not None:
                # Serving words bind the modifier; any explicit measure refuses.
                if key != "serving":
                    return None
                grams_per_unit = portions.get(modifier)
            elif key not in portions:
                # "a serving of X" is the spoken form of the food's default
                # portion; it needs no per-food table entry. Catalog does not
                # write a serving key by construction.
                if key != "serving":
                    continue
                grams_per_unit = _serving_default(portions)
                if grams_per_unit is None:
                    continue
            else:
                grams_per_unit = portions[key]

        if _refuses_after_unit(tokens[index + 1:]):
            return None

        if isinstance(grams_per_unit, bool) or not isinstance(grams_per_unit, (int, float)):
            return None
        if not math.isfinite(grams_per_unit) or grams_per_unit <= 0:
            return None

        quantity = _parse_quantity(_without_modifiers(span))
        if quantity is None or quantity <= 0:
            return None
        return round(quantity * float(grams_per_unit), 2)
    name = str(entry.get("name") or "").lower()
    if any(_noun_candidates(token) & _name_nouns(name) for token in tokens):
        # A matching dish noun already owns the phrase, including refusals
        # such as "a thick sandwich" when portions.thick is missing.
        return _dish_noun_grams(tokens, entry, portions)
    return _bare_food_noun_grams(tokens, food_id, entry, portions)


def _serving_default(portions: Mapping[str, object]) -> float | None:
    """The default portion of a food, in grams: FNDDS QNS, else piece/slice/cup."""
    for key in ("qns", "piece", "slice", "cup"):
        value = portions.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if math.isfinite(value) and value > 0:
            return float(value)
    return None


def _dish_noun_grams(
    tokens: list[str], entry: dict, portions: Mapping[str, object]
) -> float | None:
    """``"a sandwich"`` -> one default serving, when the noun fits the food.

    Only runs after every real unit has failed, and only for a noun the food's
    own name contains, so it cannot invent a unit for a food it does not name.
    The quantity is the leading amount words only: "a barbecue beef sandwich"
    reads 1, "two barbecue beef sandwiches" reads 2, "some sandwich" stays
    ``None``.
    """
    name = str(entry.get("name") or "").lower()
    for index, token in enumerate(tokens):
        if not _noun_candidates(token) & _name_nouns(name):
            continue
        span = tokens[:index]
        modifier = _span_modifier(span)
        if modifier is not None:
            grams_per_unit = portions.get(modifier)
        else:
            grams_per_unit = _serving_default(portions)
        if isinstance(grams_per_unit, bool) or not isinstance(grams_per_unit, (int, float)):
            return None
        if not math.isfinite(grams_per_unit) or grams_per_unit <= 0:
            return None
        quantity = _leading_quantity(_without_modifiers(span))
        if quantity is None or quantity <= 0:
            return None
        return round(quantity * float(grams_per_unit), 2)
    return None


def _bare_food_noun_grams(
    tokens: list[str], food_id: str, entry: dict, portions: Mapping[str, object]
) -> float | None:
    """``"one apple"`` -> ``portions.piece``; a cut without a key stays None.

    Countable bare nouns are pieces, not QNS/cup. QNS is "quantity not
    specified" (already ``"a serving"``); cup is a measure word. A breast /
    chop / fillet in the phrase with no matching portion key refuses so the
    grammar cannot invent grams for a cut.
    """
    if any(token in _CUT_NOUNS and token not in portions for token in tokens):
        return None
    identity = _food_identity_nouns(food_id, entry)
    if not identity:
        return None
    grams_per_unit = portions.get("piece")
    if isinstance(grams_per_unit, bool) or not isinstance(grams_per_unit, (int, float)):
        return None
    if not math.isfinite(grams_per_unit) or grams_per_unit <= 0:
        return None
    for index, token in enumerate(tokens):
        if not _noun_candidates(token) & identity:
            continue
        if (
            token in UNIT_SYNONYMS
            or token in GRAM_UNITS
            or token in OUNCE_UNITS
            or token in MODIFIER_KEYS
        ):
            continue
        quantity = _leading_quantity(_without_modifiers(tokens[:index]))
        if quantity is None or quantity <= 0:
            return None
        return round(quantity * float(grams_per_unit), 2)
    return None


def _food_identity_nouns(food_id: str, entry: dict) -> set[str]:
    """Countable name tokens for this food: head name, slug parts, aliases."""
    nouns: set[str] = set()
    head = str(entry.get("name") or "").split(",")[0]
    nouns.update(_SPLIT.split(head.lower()))
    nouns.update(_SPLIT.split(food_id.replace("_", " ").lower()))
    for alias in entry.get("aliases") or []:
        nouns.update(_SPLIT.split(str(alias).lower()))
    return {
        token
        for token in nouns
        if len(token) >= 3
        and token not in _FILLERS
        and token not in _NAME_STOP
        and token not in _CUT_NOUNS
        and token not in UNIT_SYNONYMS
        and token not in GRAM_UNITS
        and token not in OUNCE_UNITS
    }


def _noun_candidates(token: str) -> set[str]:
    """The dish nouns ``token`` could be: "sandwiches" -> {sandwiches, sandwich}."""
    out = {token}
    if token.endswith("ies") and len(token) > 4:
        out.add(token[:-3] + "y")
    if token.endswith("es") and len(token) > 4:
        out.add(token[:-2])
    if token.endswith("s") and len(token) > 3:
        out.add(token[:-1])
    return out


def _name_nouns(name: str) -> set[str]:
    """Dish nouns we recognise that appear in the food's name."""
    return DISH_NOUNS.intersection(_SPLIT.split(name.lower()))


def _leading_quantity(tokens: list[str]) -> float | None:
    """Quantity from the leading run of amount words, ignoring later content."""
    run: list[str] = []
    for token in tokens:
        if (
            token in _FILLERS
            or token in _FRACTION_WORDS
            or token == "and"
            or _parse_number(token) is not None
        ):
            run.append(token)
        else:
            break
    if not run:
        return None
    return _parse_quantity(run)


def _tokenize(phrase: str) -> list[str]:
    text = phrase.lower()
    for glyph, ascii_form in _UNICODE_FRACTIONS.items():
        text = text.replace(glyph, ascii_form)
    text = _WORD_HYPHEN.sub(" ", text)  # "one-half" -> "one half"
    text = _DIGIT_LETTER.sub(" ", text)  # "150g" -> "150 g"
    # A minus sign survives tokenizing so "-1 cups" parses as a negative
    # quantity and is rejected, rather than silently reading as "1 cups".
    return [token for token in (raw.strip(".") for raw in _SPLIT.split(text)) if token]


def _collapse_unit_bigrams(tokens: list[str]) -> list[str]:
    """Collapse spoken multi-word units before the unit scan."""
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        pair = (tokens[index], tokens[index + 1]) if index + 1 < len(tokens) else None
        if pair in UNIT_BIGRAMS:
            collapsed.append(UNIT_BIGRAMS[pair])
            index += 2
            continue
        collapsed.append(tokens[index])
        index += 1
    return collapsed


def _refuses_modifiers(tokens: list[str]) -> bool:
    if any(token in REFUSED_MODIFIERS for token in tokens):
        return True
    return len({MODIFIER_KEYS[token] for token in tokens if token in MODIFIER_KEYS}) > 1


def _refuses_after_unit(tokens: list[str]) -> bool:
    return any(token in _REFUSED_AFTER_UNIT for token in tokens)


def _span_modifier(tokens: list[str]) -> str | None:
    found = {MODIFIER_KEYS[token] for token in tokens if token in MODIFIER_KEYS}
    if len(found) != 1:
        return None
    return next(iter(found))


def _without_modifiers(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in MODIFIER_KEYS]


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