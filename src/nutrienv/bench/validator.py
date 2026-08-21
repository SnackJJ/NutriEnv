"""Reject leaky, unresolvable, or unachievable draft tasks.

This is a factory gate, not a Scorer. Admitted exam items still need a human
to check that the spoken query entails the scored end state.
"""

from __future__ import annotations

import itertools
import re

from nutrienv.world.catalog import canonical_food_id, iter_catalog_entries
from nutrienv.world.daily_windows import derive_profile_windows
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, ledger_totals, normalize_tags

from .generator import Task
from .portion_table import matches_portion_table
from .realize import bind_evaluate_reasons
from .realizations import UPDATE_ROWS
from .windows import any_pair_unsatisfiable

__all__ = [
    "validate_draft",
    "validate_oracle_grams",
    "semantic_key",
    "fitting_plan",
]

_WINDOW_LEAK = re.compile(r"\b(?:kcal|protein_g|carb_g|fat_g)\s+\d")
_SLUG = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
_INSTEAD = re.compile(r"what\s+(should\s+i\s+have\s+)?instead")
_UP = re.compile(r"\b(up|raise|increase|add|more|higher)\b")
_DOWN = re.compile(r"\b(down|lower|reduce|less)\b|\bcut|take\s+\S*\s*off")
_KCAL_WORD = re.compile(r"calorie|kcal|caloric")
_PROTEIN_WORD = re.compile(r"protein")
_FLOOR_WORD = re.compile(r"\bfloor\b|lower\s+end|\bbottom\b")
_CEILING_WORD = re.compile(r"\bceiling\b|upper\s+end|\btop\b")
_SPELLED_MAGNITUDE = (
    ("four hundred", 400.0),
    ("three hundred", 300.0),
    ("two hundred", 200.0),
    ("one hundred", 100.0),
    ("fifty", 50.0),
    ("thirty", 30.0),
    ("twenty", 20.0),
)
_NUMBER = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)")
# v0.5 evaluate items speak raw gram phrases ("200g chicken"). Those
# amounts are query-traceable but not named PortionFact multiples.
_EXPLICIT_GRAMS = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*g(?:rams?)?\b")
# After a gram phrase, skip "of/in" plus an optional article to reach the NP.
_GRAM_NP_PREFIX = re.compile(r"^(?:(?:of|in)\s+)?(?:(?:a|an|the)\s+)?", re.IGNORECASE)
# An adjunct or coordinator ends the modified food NP.
# Match at the leftover start or after whitespace: after lstrip(),
# "with rice" must break immediately so "chicken 150 g with rice"
# falls back to the preceding chicken NP.
_GRAM_NP_BREAK = re.compile(
    r"(?:^|\s+)(?:with|without|and|plus|alongside|besides|after|before|"
    r"for|at|on|during|then|but|or|as)\b|[,;.:]",
    re.IGNORECASE,
)
# Command/frame words immediately before a gram are not a food NP.
_GRAM_FRAME = frozenset({
    "please", "log", "evaluate", "check", "submit",
    "ate", "eat", "eaten", "had", "have",
})
_GRAM_LIGHT = frozenset({
    "a", "an", "the", "of", "in", "that", "this", "i", "we", "me", "my",
    "just", "also", "today", "yesterday",
})
_GRAM_OF_IN = re.compile(r"^(?:of|in)\b", re.IGNORECASE)
# Split an update query into clauses so each window's delta and direction
# stay attached to the noun they were spoken with. A comma starts a clause
# only when the next words look like one (window noun or direction verb).
_CLAUSE_SPLIT = re.compile(
    r"\s+and\s+|;\s*|\.\s+"
    r"|,\s+(?=(?:my|the)\s+(?:calorie|kcal|caloric|protein)"
    r"|(?:up|raise|increase|lower|reduce|move|take|bring|bump)\b)"
)


def semantic_key(task: Task) -> tuple:
    if task.situations == ("fuzzy_portion",) and task.oracle.ledger_tail:
        row = task.oracle.ledger_tail[0]
        return (
            task.family,
            "fuzzy_portion",
            task.persona,
            row.food_id,
            row.grams,
            row.eaten_at,
        )
    if task.situations == ("multi_item_log",) and task.oracle.ledger_tail:
        items = tuple(
            (row.food_id, row.grams, row.eaten_at) for row in task.oracle.ledger_tail
        )
        return (task.family, "multi_item_log", task.persona, items)
    if task.situations == ("unit_convert",) and task.oracle.ledger_tail:
        row = task.oracle.ledger_tail[0]
        return (
            task.family,
            "unit_convert",
            task.persona,
            row.food_id,
            row.grams,
            row.eaten_at,
        )
    if task.situations == ("near_synonym",) and task.oracle.ledger_tail:
        row = task.oracle.ledger_tail[0]
        return (
            task.family,
            "near_synonym",
            task.persona,
            row.food_id,
            row.grams,
            row.eaten_at,
        )
    if task.situations == ("ledger_gap",) and task.oracle.ledger_tail:
        missing = tuple((row.food_id, row.eaten_at) for row in task.oracle.ledger_tail)
        surround = tuple(sorted(row.eaten_at for row in task.s0.ledger))
        return (task.family, "ledger_gap", task.persona, missing, surround)
    if task.persona == "leftover":
        foods = tuple((row.food_id, row.eaten_at) for row in task.s0.ledger)
        windows = tuple(sorted(task.s0.profile.windows))
        return ("recommend", None, "leftover", foods, windows)
    if task.family == "recommend":
        windows = tuple(
            sorted((key, tuple(bounds)) for key, bounds in task.s0.profile.windows.items())
        )
        preset = task.s0.profile.plan_preset
        preset_key = tuple(sorted(preset.items())) if isinstance(preset, dict) else None
        return (
            task.family,
            task.persona,
            tuple(task.s0.profile.allergies),
            windows,
            preset_key,
        )
    if task.family == "update" and task.oracle.profile is not None:
        added = tuple(
            sorted(set(task.oracle.profile.allergies) - set(task.s0.profile.allergies))
        )
        removed = tuple(
            sorted(set(task.s0.profile.allergies) - set(task.oracle.profile.allergies))
        )
        shifted = tuple(
            sorted(
                (
                    key,
                    round(
                        task.oracle.profile.windows[key][0]
                        - task.s0.profile.windows[key][0],
                        2,
                    ),
                    round(
                        task.oracle.profile.windows[key][1]
                        - task.s0.profile.windows[key][1],
                        2,
                    ),
                )
                for key, bounds in task.oracle.profile.windows.items()
                if task.s0.profile.windows.get(key) != bounds
            )
        )
        goal_before = None
        goal_after = None
        if isinstance(task.s0.profile.plan_preset, dict):
            goal_before = task.s0.profile.plan_preset.get("goal")
        if isinstance(task.oracle.profile.plan_preset, dict):
            goal_after = task.oracle.profile.plan_preset.get("goal")
        return (task.family, added, removed, shifted, goal_before, goal_after)
    if task.family == "constrain":
        kind = "condition" if "condition_suitability" in task.situations else "conflict"
        allergies = tuple(task.s0.profile.allergies)
        windows = tuple(
            sorted((key, tuple(bounds)) for key, bounds in task.s0.profile.windows.items())
        )
        return (task.family, kind, allergies, windows)
    if task.family == "evaluate" and task.oracle.last_plan:
        items = tuple(
            (item["food_id"], float(item["grams"])) for item in task.oracle.last_plan
        )
        return (task.family, items)
    return (task.family, task.situations, task.persona, task.query)


def validate_oracle_grams(task: Task) -> list[str]:
    """Return issues for Oracle grams that lack a deterministic portion anchor.

    An amount is legal when it is a portion-table multiple, or when the query
    names that food with a spoken gram phrase that ``resolve_portion`` maps
    to the same grams. The check still reads the Oracle rather than a
    realization row, so independently authored drafts are covered.
    """
    issues: list[str] = []
    items = []
    if task.oracle.ledger_tail:
        items.extend(
            (f"ledger_tail[{index}]", row.food_id, row.grams)
            for index, row in enumerate(task.oracle.ledger_tail)
        )
    if task.oracle.last_plan:
        items.extend(
            (f"last_plan[{index}]", str(item["food_id"]), item["grams"])
            for index, item in enumerate(task.oracle.last_plan)
        )
    if task.oracle.evaluated_plan:
        items.extend(
            (f"evaluated_plan[{index}]", str(item["food_id"]), item["grams"])
            for index, item in enumerate(task.oracle.evaluated_plan)
        )

    for location, food_id, grams in items:
        if matches_portion_table(food_id, grams, task.s0.catalog):
            continue
        if _query_traceable_grams(task.query, food_id, grams, task.s0.catalog):
            continue
        issues.append(
            f"oracle {location} grams {grams} for {food_id} do not match portion table"
        )
    return issues


def validate_draft(task: Task) -> list[str]:
    """Return issue strings. Empty means the draft is mechanically admissible."""
    issues: list[str] = []
    query = task.query.lower()
    if "catalog id" in query or "food_id" in query:
        issues.append("query leaks food_id")
    if task.family == "recommend" and _WINDOW_LEAK.search(task.query):
        issues.append("recommend query leaks window numbers")
    if task.family != "evaluate":
        leaked = [
            token for token in _SLUG.findall(query) if token in task.s0.catalog
        ]
        if leaked:
            issues.append(f"query leaks catalog slugs {leaked}")

    if task.situations == ("fuzzy_portion",) and task.oracle.ledger_tail:
        row = task.oracle.ledger_tail[0]
        if not matches_portion_table(row.food_id, row.grams, task.s0.catalog):
            issues.append(f"fuzzy grams {row.grams} do not match portion table")

    if task.persona == "leftover" and task.oracle.plan_windows:
        eaten = ledger_totals(task.s0.ledger, task.s0.catalog)
        for key, (lo, hi) in task.s0.profile.windows.items():
            used = eaten.get(key, 0.0)
            expected = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
            if task.oracle.plan_windows.get(key) != expected:
                issues.append(f"plan_windows {key} != remainder {expected}")
        kcal = task.oracle.plan_windows.get("kcal")
        if kcal is not None and kcal[1] <= 0:
            issues.append("leftover kcal ceiling is not positive")

    if task.family == "update":
        issues.extend(_validate_update(task, query))
    if task.family == "constrain" and "condition_suitability" in task.situations:
        issues.extend(_validate_condition(task, query))
    if task.family == "constrain" and "conflict_windows" in task.situations:
        issues.extend(_validate_conflict(task))
    if task.oracle.sub_oracles:
        issues.extend(_validate_composite(task))
    elif task.family == "evaluate":
        issues.extend(_validate_evaluate(task, query))
    if task.oracle.last_verdict == "reject":
        if task.oracle.plan_must_fit_windows:
            issues.append("reject oracle must not set plan_must_fit_windows")
        if task.oracle.allow_empty_plan:
            issues.append("reject oracle must not set allow_empty_plan")
    if task.oracle.last_plan == [] and task.oracle.plan_must_fit_windows:
        # Scorer judges the plan against oracle.profile (else S0). Search
        # that profile so a draft the gate admits is one the Scorer can pass.
        # plan_windows, when pinned (leftover remainder), stays the judged
        # window.
        profile = _judged_profile(task)
        windows = task.oracle.plan_windows or profile.windows
        if fitting_plan(task.s0.catalog, windows, profile.allergies) is None:
            issues.append(
                "item is unpassable: no allergen-safe plan fits the judged windows"
            )
    return issues


def _judged_profile(task: Task):
    if task.oracle.profile is not None:
        return task.oracle.profile
    return task.s0.profile


def _tag_set(values) -> set[str]:
    return set(normalize_tags(list(values or [])))


def _catalog_tags(catalog) -> set[str]:
    tags: set[str] = set()
    for _, entry in iter_catalog_entries(catalog):
        for tag in entry.get("allergen_tags") or []:
            tags.add(str(tag))
    return tags


def _token_in_query(token: str, query: str) -> bool:
    token = token.strip().lower()
    if len(token) < 3:
        return False
    return re.search(rf"(?<![\w]){re.escape(token)}(?![\w])", query) is not None


def _index_spoken_name(index: dict[str, set[str]], name: str, identity: str) -> None:
    key = name.strip().lower()
    if len(key) < 3 or "," in key:
        return
    index.setdefault(key, set()).add(identity)


def _food_identity_index(catalog) -> dict[str, set[str]]:
    cached = getattr(catalog, "_identity_index", None)
    if cached is not None:
        return cached
    index: dict[str, set[str]] = {}
    for food_id, entry in iter_catalog_entries(catalog):
        identity = canonical_food_id(catalog, str(food_id))
        _index_spoken_name(index, str(food_id), identity)
        _index_spoken_name(index, str(food_id).replace("_", " "), identity)
        for alias in entry.get("aliases") or []:
            _index_spoken_name(index, str(alias), identity)
            _index_spoken_name(index, str(alias).replace("_", " "), identity)
    aliases = getattr(catalog, "_aliases", None)
    if isinstance(aliases, dict):
        for slug, fdc_id in aliases.items():
            identity = canonical_food_id(catalog, str(fdc_id))
            _index_spoken_name(index, str(slug), identity)
            _index_spoken_name(index, str(slug).replace("_", " "), identity)
    try:
        # Hang it on the catalog, not a global id() table: an id is reused once
        # the object it named is collected, and that served a stale index.
        catalog._identity_index = index
    except (AttributeError, TypeError):
        pass
    return index


def _span_food_identities(span: str, catalog) -> set[str]:
    """Canonical food identities named in ``span``.

    Spoken n-grams (``chicken``, ``greek yogurt``) map through aliases and
    slugs to one canonical id, so ``chicken_breast`` and ``171477`` do not
    count as two foods. Two distinct identities in one span is fail-closed.
    """
    tokens = re.findall(r"[a-z0-9]+", span.lower())
    index = _food_identity_index(catalog)
    hits: set[str] = set()
    for width in range(1, min(4, len(tokens)) + 1):
        for start in range(len(tokens) - width + 1):
            phrase = " ".join(tokens[start: start + width])
            hits.update(index.get(phrase, ()))
            hits.update(index.get(phrase.replace(" ", "_"), ()))
    return hits


def _is_frame_span(text: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return not tokens or all(token in _GRAM_FRAME or token in _GRAM_LIGHT for token in tokens)


def _after_food_np(text: str) -> str:
    after = _GRAM_NP_PREFIX.sub("", text.lstrip(), count=1)
    broken = _GRAM_NP_BREAK.search(after)
    if broken:
        after = after[: broken.start()]
    return after.strip()


def _before_food_np(text: str) -> str:
    starts = [hit.end() for hit in _GRAM_NP_BREAK.finditer(text)]
    if starts:
        text = text[starts[-1]:]
    return text.strip()


def _modified_food_span(
    query: str, match: re.Match[str], *, since: int, until: int
) -> str | None:
    """Unique food NP that a spoken gram phrase modifies, or None.

    The search is clipped to the adjacent ``_EXPLICIT_GRAMS`` hits, so one
    amount cannot swallow the next (``150 g of chicken 200 g of rice``
    binds 150 to chicken only). After that clip: skip ``of``/``in`` and
    an article, then stop at a coordinator or adjunct (``and``, ``with``,
    comma, …), including a breaker at the leftover start. If both a
    preceding NP and a following NP remain and the gram is not an
    ``of``/``in`` complement, the pairing is not unique and this returns
    None (fail-closed). Frame words such as ``log`` are not a food NP.
    """
    raw_after = query[match.end(): until]
    after = _after_food_np(raw_after)
    before = _before_food_np(query[since: match.start()])
    attached = _GRAM_OF_IN.search(raw_after.lstrip()) is not None
    if attached and after:
        return after
    if after and before and not _is_frame_span(before):
        return None
    if after:
        return after
    if before and not _is_frame_span(before):
        return before
    return None


def _query_traceable_grams(query: str, food_id: str, grams: float, catalog) -> bool:
    """True when a spoken gram phrase that modifies this food resolves to grams.

    Binding is the unique local NP of that phrase, never a later gram span
    and never an ambiguous FOOD-GRAM-FOOD sandwich. The span must name
    exactly one catalog food identity (canonicalized), and that identity
    must be this food. ``150 g of chicken rice`` authorizes neither food.
    """
    target = round(float(grams), 2)
    wanted = canonical_food_id(catalog, food_id)
    matches = list(_EXPLICIT_GRAMS.finditer(query))
    for index, match in enumerate(matches):
        since = matches[index - 1].end() if index else 0
        until = matches[index + 1].start() if index + 1 < len(matches) else len(query)
        span = _modified_food_span(query, match, since=since, until=until)
        if not span:
            continue
        if _span_food_identities(span, catalog) != {wanted}:
            continue
        resolved = resolve_portion(food_id, match.group(0), catalog)
        if resolved is not None and round(resolved, 2) == target:
            return True
    return False


def _food_mentions_tag(query: str, tag: str, catalog) -> bool:
    phrases = {tag, tag.replace("_", " ")}
    if any(_token_in_query(phrase, query) for phrase in phrases):
        return True
    for _, entry in iter_catalog_entries(catalog):
        tags = entry.get("allergen_tags") or []
        if tag not in tags:
            continue
        names = [str(entry.get("name") or "")]
        names.extend(str(alias) for alias in (entry.get("aliases") or []))
        if any(_token_in_query(name, query) for name in names if name):
            return True
    return False


def _query_magnitudes(query: str) -> set[float]:
    found = {float(match.group(1)) for match in _NUMBER.finditer(query)}
    for phrase, value in _SPELLED_MAGNITUDE:
        if re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", query):
            found.add(value)
    return found


def _split_update_clauses(query: str) -> list[str]:
    parts = [part.strip() for part in _CLAUSE_SPLIT.split(query) if part and part.strip()]
    return parts or [query]


def _update_clause_bindings(
    query: str,
) -> dict[str, tuple[set[float], bool, bool]] | None:
    """Pair each window noun with the magnitudes and direction in its clause.

    Returns None when a clause names a window but cannot be paired reliably
    (several numbers, or two windows with several numbers). A false rejection
    costs a row; a false acceptance costs a broken exam item.
    """
    bindings: dict[str, tuple[set[float], bool, bool]] = {}
    inherit_up = False
    inherit_down = False
    for clause in _split_update_clauses(query):
        has_up = _UP.search(clause) is not None
        has_down = _DOWN.search(clause) is not None
        if has_up or has_down:
            inherit_up = has_up
            inherit_down = has_down
        mentioned: list[str] = []
        if _KCAL_WORD.search(clause):
            mentioned.append("kcal")
        if _PROTEIN_WORD.search(clause):
            mentioned.append("protein_g")
        magnitudes = _query_magnitudes(clause)
        if not mentioned or not magnitudes:
            continue
        if len(magnitudes) != 1:
            return None
        bound = (magnitudes, has_up or inherit_up, has_down or inherit_down)
        for key in mentioned:
            prior = bindings.get(key)
            if prior is not None and prior[0] != magnitudes:
                return None
            bindings[key] = bound
    return bindings


def _oracle_window_shifts(
    s0_windows: dict, oracle_windows: dict
) -> dict[str, float | tuple[float, float]]:
    actual: dict[str, float | tuple[float, float]] = {}
    for key, bounds in oracle_windows.items():
        start = s0_windows.get(key)
        if start is None or start == bounds:
            continue
        dlo = float(bounds[0]) - float(start[0])
        dhi = float(bounds[1]) - float(start[1])
        actual[key] = dlo if dlo == dhi else (dlo, dhi)
    return actual


def _normalize_shift(delta) -> float | tuple[float, float]:
    if isinstance(delta, (tuple, list)):
        dlo, dhi = float(delta[0]), float(delta[1])
        return dlo if dlo == dhi else (dlo, dhi)
    return float(delta)


def _shift_magnitudes(shift: float | tuple[float, float]) -> set[float]:
    if isinstance(shift, tuple):
        return {abs(part) for part in shift if part != 0.0}
    if float(shift) == 0.0:
        return set()
    return {abs(float(shift))}


def _declared_asymmetric(row, key: str) -> bool:
    if row is None:
        return False
    delta = (row.window_shifts or {}).get(key)
    if not isinstance(delta, (tuple, list)):
        return False
    return float(delta[0]) != float(delta[1])


def _preset_evidenced(query: str, preset: dict) -> bool:
    for value in preset.values():
        if isinstance(value, str) and value and _token_in_query(value, query):
            return True
        if value is True and _token_in_query("flex", query):
            return True
    return False


def _validate_update(task: Task, query: str) -> list[str]:
    issues: list[str] = []
    oracle = task.oracle.profile
    s0 = task.s0.profile
    if oracle is None:
        issues.append("update oracle profile is missing")
    if task.oracle.ledger is None:
        issues.append("update oracle ledger is missing")
    if oracle is None:
        return issues
    if oracle == s0 and not task.oracle.update_band:
        issues.append("update oracle profile is unchanged from S0")
        return issues
    # Body-fact/phase oracles re-derive windows through the world table
    # (ADR 0014); the deltas are derivation output, not query shifts.
    body_derived = derive_profile_windows(oracle) == oracle.windows
    tags = _catalog_tags(task.s0.catalog)
    for allergy in oracle.allergies:
        if allergy not in tags or allergy == "shrimp":
            issues.append(f"update allergy {allergy!r} is not a catalog tag")
    if oracle.user_id != s0.user_id or oracle.version != s0.version:
        issues.append("update changed an identity field")
    if oracle.medications != s0.medications:
        issues.append("update changed unmentioned medications")
    row = next((item for item in UPDATE_ROWS if item.query == task.query), None)
    declared_preset = getattr(row, "set_plan_preset", None) if row else None
    if oracle.plan_preset != s0.plan_preset:
        if declared_preset is None:
            issues.append("update changed unmentioned plan_preset")
        elif oracle.plan_preset != declared_preset:
            issues.append("update plan_preset does not match the row")
        elif not _preset_evidenced(query, declared_preset):
            issues.append("update plan_preset is not evidenced in the query")
    elif declared_preset is not None and oracle.plan_preset != declared_preset:
        issues.append("update row declared plan_preset change missing from oracle")
    mentions_kcal = _KCAL_WORD.search(query) is not None
    mentions_protein = _PROTEIN_WORD.search(query) is not None
    bindings = _update_clause_bindings(query)
    for key, bounds in oracle.windows.items():
        s0_bounds = s0.windows.get(key)
        if s0_bounds == bounds or body_derived:
            continue
        mentioned = (key == "kcal" and mentions_kcal) or (
            key == "protein_g" and mentions_protein
        )
        if not mentioned:
            issues.append(f"update shifted unmentioned window {key}")
            continue
        if s0_bounds is None:
            continue
        dlo = float(bounds[0]) - float(s0_bounds[0])
        dhi = float(bounds[1]) - float(s0_bounds[1])
        if dlo != dhi:
            if not _declared_asymmetric(row, key):
                issues.append(f"update window {key} shift is asymmetric")
                continue
            if dlo != 0.0 and _FLOOR_WORD.search(query) is None:
                issues.append(f"update window {key} moved the floor but query names no bound")
            if dhi != 0.0 and _CEILING_WORD.search(query) is None:
                issues.append(f"update window {key} moved the ceiling but query names no bound")
        actual = _shift_magnitudes((dlo, dhi) if dlo != dhi else dlo)
        if bindings is None:
            issues.append("update window deltas are not the query magnitudes")
        else:
            bound = bindings.get(key)
            if bound is None or bound[0] != actual:
                issues.append("update window deltas are not the query magnitudes")
            else:
                _, clause_up, clause_down = bound
                if (dlo > 0 or dhi > 0) and not clause_up:
                    issues.append("update window rose but query has no up-direction word")
                if (dlo < 0 or dhi < 0) and not clause_down:
                    issues.append("update window fell but query has no down-direction word")
    for key, bounds in s0.windows.items():
        if key in oracle.windows:
            continue
        mentioned = (key == "kcal" and mentions_kcal) or (
            key == "protein_g" and mentions_protein
        )
        if not mentioned:
            issues.append(f"update dropped unmentioned window {key}")
    added = set(oracle.allergies) - set(s0.allergies)
    removed = set(s0.allergies) - set(oracle.allergies)
    for tag in added:
        if not _food_mentions_tag(query, tag, task.s0.catalog):
            issues.append(f"update allergy {tag} is not evidenced in the query")
    for tag in removed:
        if not _food_mentions_tag(query, tag, task.s0.catalog):
            issues.append(f"update allergy removal {tag} is not evidenced in the query")
    issues.extend(_validate_update_matches_row(task, added, removed))
    return issues


def _validate_update_matches_row(
    task: Task, added: set[str], removed: set[str]
) -> list[str]:
    issues: list[str] = []
    row = next((item for item in UPDATE_ROWS if item.query == task.query), None)
    if row is None or task.oracle.profile is None:
        return issues
    if added != set(row.add_allergens):
        issues.append("update oracle allergens do not match the row")
    declared_removed = set(row.remove_allergens)
    extra = removed - declared_removed
    missing = declared_removed - removed
    if extra:
        issues.append("update oracle removed allergies the row did not declare")
    if missing:
        issues.append("update row declared allergen removal missing from oracle")
    declared_shifts = dict(row.window_shifts or {})
    actual = _oracle_window_shifts(task.s0.profile.windows, task.oracle.profile.windows)
    for key, delta in declared_shifts.items():
        normalized = _normalize_shift(delta)
        zero = normalized == 0.0 or normalized == (0.0, 0.0)
        if zero:
            if key not in actual:
                issues.append(f"update zero-magnitude {key} shift was skipped")
            continue
        if key not in actual:
            issues.append(f"update row declared {key} shift missing from oracle")
        elif actual[key] != normalized:
            issues.append(f"update oracle {key} shift {actual[key]} != declared {delta}")
    for key in actual:
        if key not in declared_shifts:
            issues.append(f"update oracle shifted undeclared window {key}")
    return issues


def _validate_condition(task: Task, query: str) -> list[str]:
    issues: list[str] = []
    if task.oracle.profile is None:
        issues.append("condition oracle profile is missing")
    if task.oracle.ledger is None:
        issues.append("condition oracle ledger is missing")
    if task.oracle.last_plan != []:
        issues.append("condition last_plan must be an empty list")
    if task.oracle.allow_empty_plan is not False:
        issues.append("condition allow_empty_plan must be False")
    if not task.oracle.plan_must_be_safe:
        issues.append("condition plan_must_be_safe is required")
    if not task.oracle.plan_must_fit_windows:
        issues.append("condition plan_must_fit_windows is required")
    kcal = task.s0.profile.windows.get("kcal")
    if kcal is None or kcal[1] > 800:
        issues.append("condition meal kcal ceiling must be <= 800")
    allergies = set(task.s0.profile.allergies)
    carries = False
    for food_id, entry in iter_catalog_entries(task.s0.catalog):
        tags = set(entry.get("allergen_tags") or [])
        if not allergies.intersection(tags):
            continue
        names = [food_id.replace("_", " "), str(entry.get("name") or "")]
        names.extend(str(alias) for alias in (entry.get("aliases") or []))
        if any(_token_in_query(name, query) for name in names if name):
            carries = True
            break
    if not carries:
        issues.append("condition query food does not carry a profile allergy tag")
    profile = _judged_profile(task)
    if not _staple_plan_fits(task.s0.catalog, profile.windows, profile.allergies):
        issues.append("condition meal window has no safe staple plan")
    return issues


def _validate_conflict(task: Task) -> list[str]:
    issues: list[str] = []
    if task.oracle.profile is None:
        issues.append("conflict oracle profile is missing")
    if task.oracle.ledger is None:
        issues.append("conflict oracle ledger is missing")
    if not task.s0.last_plan:
        issues.append("conflict S0 last_plan must be non-empty")
    if task.oracle.allow_empty_plan is not True:
        issues.append("conflict allow_empty_plan must be True")
    if task.oracle.plan_must_fit_windows is not True:
        issues.append("conflict plan_must_fit_windows must be True")
    if task.oracle.last_plan is not None:
        issues.append("conflict oracle last_plan must be None")
    if not any_pair_unsatisfiable(
        task.s0.profile.windows, task.s0.catalog, task.s0.profile.allergies
    ):
        issues.append("conflict windows are satisfiable")
    return issues


def _validate_composite(task: Task) -> list[str]:
    issues: list[str] = []
    children = task.oracle.sub_oracles or ()
    has_unfit = any(child.last_verdict == "reject" for child in children)
    has_substitute = any(
        child.last_plan == [] and child.last_verdict is None for child in children
    )
    if has_unfit and has_substitute:
        issues.append("composite Evaluate-unfit paired with Recommend-substitute")
    return issues


def _evaluate_food_names(food_id: str, catalog) -> list[str]:
    entry = catalog.get(food_id) or {}
    names = [food_id.replace("_", " "), str(entry.get("name") or "")]
    name = str(entry.get("name") or "")
    if "," in name:
        names.append(name.split(",", 1)[0])
    names.extend(str(alias) for alias in (entry.get("aliases") or []))
    return names


def _validate_evaluate(task: Task, query: str) -> list[str]:
    issues: list[str] = []
    if task.oracle.profile is None:
        issues.append("evaluate oracle profile is missing")
    if task.oracle.ledger is None:
        issues.append("evaluate oracle ledger is missing")
    if _INSTEAD.search(query):
        issues.append("evaluate query asks what instead")
    named = task.oracle.evaluated_plan
    if task.oracle.last_verdict in {"accept", "reject"} or named:
        issues.extend(_validate_evaluate_verdict(task, query, named))
        return issues
    plan = task.oracle.last_plan
    if not plan:
        if task.oracle.last_verdict == "reject":
            return issues
        issues.append("evaluate last_plan is empty")
        return issues
    for item in plan:
        food_id = str(item["food_id"])
        grams = item["grams"]
        if matches_portion_table(food_id, grams, task.s0.catalog):
            continue
        if _query_traceable_grams(query, food_id, grams, task.s0.catalog):
            continue
        issues.append(
            f"evaluate grams {grams} for {food_id} do not match portion table"
        )
    for item in plan:
        food_id = str(item["food_id"])
        names = _evaluate_food_names(food_id, task.s0.catalog)
        if not any(_token_in_query(name, query) for name in names if name):
            issues.append(f"evaluate food {food_id} is not mentioned in the query")
    totals = ledger_totals(
        [LedgerRow(str(item["food_id"]), float(item["grams"]), "plan") for item in plan],
        task.s0.catalog,
    )
    for key, (lo, hi) in task.s0.profile.windows.items():
        amount = totals.get(key, 0.0)
        if amount < lo or amount > hi:
            issues.append(f"evaluate plan {key} {amount} is outside windows {(lo, hi)}")
    allergies = set(task.s0.profile.allergies)
    for item in plan:
        entry = task.s0.catalog.get(str(item["food_id"])) or {}
        tags = set(entry.get("allergen_tags") or [])
        hit = tags & allergies
        if hit:
            issues.append(
                f"evaluate last_plan is unpassable: {item['food_id']} carries {sorted(hit)}"
            )
    return issues


def _validate_evaluate_verdict(task: Task, query: str, named) -> list[str]:
    issues: list[str] = []
    if not named:
        issues.append("evaluate evaluated_plan is missing")
        return issues
    verdict = task.oracle.last_verdict
    if verdict == "reject":
        if task.oracle.last_plan:
            issues.append("evaluate last_plan must be empty when reject")
    elif verdict == "accept":
        if not task.oracle.last_plan:
            issues.append("evaluate last_plan is empty")
        elif task.oracle.last_plan != named:
            issues.append("evaluate last_plan != evaluated_plan")
    windows = task.oracle.plan_windows
    if not windows:
        issues.append("evaluate plan_windows is missing")
    else:
        if any(lo > hi for lo, hi in windows.values()):
            issues.append("evaluate plan_windows intersection is empty")
        expected = bind_evaluate_reasons(
            named, windows, task.s0.catalog, task.s0.profile.allergies
        )
        if verdict == "reject" and set(task.oracle.last_reasons) != set(expected):
            issues.append("evaluate last_reasons != bind of evaluated_plan")
        if verdict == "accept" and expected:
            issues.append("evaluate accept gold still binds unfit reasons")
    for item in named:
        food_id = str(item["food_id"])
        names = _evaluate_food_names(food_id, task.s0.catalog)
        if not any(_token_in_query(name, query) for name in names if name):
            issues.append(f"evaluate food {food_id} is not mentioned in the query")
    return issues


_STAPLE_PLANS = (
    (
        {"food_id": "chicken_breast", "grams": 150.0},
        {"food_id": "white_rice", "grams": 150.0},
    ),
    (
        {"food_id": "chicken_breast", "grams": 120.0},
        {"food_id": "white_rice", "grams": 180.0},
    ),
    (
        {"food_id": "chicken_breast", "grams": 100.0},
        {"food_id": "white_rice", "grams": 200.0},
        {"food_id": "olive_oil", "grams": 10.0},
    ),
    (
        {"food_id": "chicken_breast", "grams": 80.0},
        {"food_id": "white_rice", "grams": 200.0},
        {"food_id": "broccoli", "grams": 100.0},
        {"food_id": "olive_oil", "grams": 15.0},
    ),
    (
        {"food_id": "chicken_breast", "grams": 130.0},
        {"food_id": "white_rice", "grams": 120.0},
        {"food_id": "broccoli", "grams": 90.0},
    ),
    (
        {"food_id": "pasta", "grams": 140.0},
        {"food_id": "chicken_breast", "grams": 120.0},
    ),
)


def _staple_plan_fits(catalog, windows: dict, allergies) -> bool:
    banned = _tag_set(allergies)
    for items in _STAPLE_PLANS:
        tags: set[str] = set()
        totals: dict[str, float] = {}
        missing = False
        for item in items:
            food = catalog.get(item["food_id"])
            if not isinstance(food, dict):
                missing = True
                break
            try:
                tags.update(_tag_set(food.get("allergen_tags") or []))
            except ValueError:
                missing = True
                break
            grams = float(item["grams"])
            for key, amount in (food.get("nutrients") or {}).items():
                totals[str(key)] = totals.get(str(key), 0.0) + float(amount) * grams / 100.0
        if missing or tags & banned:
            continue
        if all(
            lo <= totals.get(nutrient, 0.0) <= hi
            for nutrient, (lo, hi) in windows.items()
        ):
            return True
    return False


# Staple basket and coarse gram grid for the achievability search. Singles
# and pairs are enough for every admitted meal window; triples would be
# C(n,3)*20^3 evaluations and make validate_draft too slow over a split.
_FIT_STAPLES = (
    "chicken_breast", "white_rice", "broccoli", "olive_oil", "greek_yogurt",
    "banana", "oats", "potato", "spinach", "apple", "egg", "tofu",
    "black_beans", "pasta", "salmon", "tuna", "cheddar", "peanut_butter",
    "almond",
)
_FIT_GRID = tuple(float(grams) for grams in range(20, 401, 20))


def fitting_plan(catalog, windows: dict, allergies) -> list[dict] | None:
    """Search staples for any allergen-safe plan inside every judged window."""
    banned = _tag_set(allergies)
    keys = list(windows)
    per_gram: dict[str, dict[str, float]] = {}
    for food_id in _FIT_STAPLES:
        entry = catalog.get(food_id)
        if not isinstance(entry, dict):
            continue
        try:
            tags = _tag_set(entry.get("allergen_tags") or [])
        except ValueError:
            continue
        if tags & banned:
            continue
        nutrients = entry.get("nutrients") or {}
        per_gram[food_id] = {
            key: float(nutrients.get(key) or 0.0) / 100.0 for key in keys
        }

    def _fits(totals: dict[str, float]) -> bool:
        return all(
            lo <= totals.get(key, 0.0) <= hi for key, (lo, hi) in windows.items()
        )

    for food_id, vec in per_gram.items():
        for grams in _FIT_GRID:
            totals = {key: vec.get(key, 0.0) * grams for key in keys}
            if _fits(totals):
                return [{"food_id": food_id, "grams": grams}]
    for first, second in itertools.combinations(per_gram, 2):
        v1 = per_gram[first]
        v2 = per_gram[second]
        for g1 in _FIT_GRID:
            t1 = {key: v1.get(key, 0.0) * g1 for key in keys}
            for g2 in _FIT_GRID:
                totals = {key: t1[key] + v2.get(key, 0.0) * g2 for key in keys}
                if _fits(totals):
                    return [
                        {"food_id": first, "grams": g1},
                        {"food_id": second, "grams": g2},
                    ]
    return None
