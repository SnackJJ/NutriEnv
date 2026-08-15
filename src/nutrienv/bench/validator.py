"""Reject leaky, unresolvable, or unachievable draft tasks.

This is a factory gate, not a Scorer. Admitted exam items still need a human
to check that the spoken query entails the scored end state.
"""

from __future__ import annotations

import re

from nutrienv.world.portions import OUNCE_GRAMS, resolve_portion
from nutrienv.world.types import LedgerRow, ledger_totals

from .generator import Task
from .realizations import EVALUATE_ROWS, UPDATE_ROWS

__all__ = ["validate_draft", "semantic_key"]

_WINDOW_LEAK = re.compile(r"\b(?:kcal|protein_g|carb_g|fat_g)\s+\d")
_SLUG = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
_INSTEAD = re.compile(r"what\s+(should\s+i\s+have\s+)?instead")
_UP = re.compile(r"\b(up|raise|increase|add|more|higher)\b")
_DOWN = re.compile(r"\b(down|lower|reduce|less)\b|\bcut|take\s+\S*\s*off")
_KCAL_WORD = re.compile(r"calorie|kcal|caloric")
_PROTEIN_WORD = re.compile(r"protein")
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
    if task.persona == "leftover":
        foods = tuple((row.food_id, row.eaten_at) for row in task.s0.ledger)
        windows = tuple(sorted(task.s0.profile.windows))
        return ("recommend", None, "leftover", foods, windows)
    if task.family == "update" and task.oracle.profile is not None:
        added = tuple(
            sorted(set(task.oracle.profile.allergies) - set(task.s0.profile.allergies))
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
                )
                for key, bounds in task.oracle.profile.windows.items()
                if task.s0.profile.windows.get(key) != bounds
            )
        )
        goal = None
        preset = task.s0.profile.plan_preset
        if isinstance(preset, dict):
            goal = preset.get("goal")
        return (task.family, added, shifted, goal)
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


def _matches_portion_table(food_id: str, grams: float, catalog) -> bool:
    entry = catalog.get(food_id)
    if not isinstance(entry, dict):
        return False
    portions = entry.get("portions") or {}
    candidates = {round(2.0 * OUNCE_GRAMS, 2)}
    for one in portions.values():
        if isinstance(one, (int, float)) and not isinstance(one, bool):
            for quantity in (0.5, 1.0, 1.5, 2.0):
                candidates.add(round(quantity * float(one), 2))
    return round(float(grams), 2) in candidates


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
        if not _matches_portion_table(row.food_id, row.grams, task.s0.catalog):
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
    if task.family == "evaluate":
        issues.extend(_validate_evaluate(task, query))
    return issues


def _catalog_tags(catalog) -> set[str]:
    tags: set[str] = set()
    for entry in catalog.values():
        for tag in entry.get("allergen_tags") or []:
            tags.add(str(tag))
    return tags


def _token_in_query(token: str, query: str) -> bool:
    token = token.strip().lower()
    if len(token) < 3:
        return False
    return re.search(rf"(?<![\w]){re.escape(token)}(?![\w])", query) is not None


def _food_mentions_tag(query: str, tag: str, catalog) -> bool:
    phrases = {tag, tag.replace("_", " ")}
    if any(_token_in_query(phrase, query) for phrase in phrases):
        return True
    for entry in catalog.values():
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
    if oracle == s0:
        issues.append("update oracle profile is unchanged from S0")
        return issues
    tags = _catalog_tags(task.s0.catalog)
    for allergy in oracle.allergies:
        if allergy not in tags or allergy == "shrimp":
            issues.append(f"update allergy {allergy!r} is not a catalog tag")
    if oracle.user_id != s0.user_id or oracle.version != s0.version:
        issues.append("update changed an identity field")
    if oracle.medications != s0.medications:
        issues.append("update changed unmentioned medications")
    if oracle.plan_preset != s0.plan_preset:
        issues.append("update changed unmentioned plan_preset")
    mentions_kcal = _KCAL_WORD.search(query) is not None
    mentions_protein = _PROTEIN_WORD.search(query) is not None
    magnitudes = _query_magnitudes(query)
    for key, bounds in oracle.windows.items():
        s0_bounds = s0.windows.get(key)
        if s0_bounds == bounds:
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
            issues.append(f"update window {key} shift is asymmetric")
            continue
        delta = dlo
        if magnitudes != {abs(delta)}:
            issues.append(f"update window delta {abs(delta):g} is not the query magnitude")
        if delta > 0 and _UP.search(query) is None:
            issues.append("update window rose but query has no up-direction word")
        if delta < 0 and _DOWN.search(query) is None:
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
    for tag in added:
        if not _food_mentions_tag(query, tag, task.s0.catalog):
            issues.append(f"update allergy {tag} is not evidenced in the query")
    issues.extend(_validate_update_matches_row(task, added))
    return issues


def _validate_update_matches_row(task: Task, added: set[str]) -> list[str]:
    issues: list[str] = []
    row = next((item for item in UPDATE_ROWS if item.query == task.query), None)
    if row is None or task.oracle.profile is None:
        return issues
    declared = set(row.add_allergens)
    if added != declared:
        issues.append("update oracle allergens do not match the row")
    removed = set(task.s0.profile.allergies) - set(task.oracle.profile.allergies)
    if removed:
        issues.append("update oracle removed allergies the row did not declare")
    declared_shifts = dict(row.window_shifts or {})
    actual = _oracle_window_shifts(task.s0.profile.windows, task.oracle.profile.windows)
    for key, delta in declared_shifts.items():
        if float(delta) == 0.0:
            if key not in actual:
                issues.append(f"update zero-magnitude {key} shift was skipped")
            continue
        if key not in actual:
            issues.append(f"update row declared {key} shift missing from oracle")
        elif actual[key] != float(delta):
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
    for food_id, entry in task.s0.catalog.items():
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
    return issues


def _windows_unsatisfiable(windows: dict, catalog, allergies: tuple[str, ...] = ()) -> bool:
    banned = set(allergies)
    kcal_hi = float(windows.get("kcal", (0.0, 0.0))[1])
    prot_lo = float(windows.get("protein_g", (0.0, 0.0))[0])
    best = 0.0
    for entry in catalog.values():
        tags = set(entry.get("allergen_tags") or [])
        if tags & banned:
            continue
        nutrients = entry.get("nutrients") or {}
        kcal = float(nutrients.get("kcal") or 0.0)
        protein = float(nutrients.get("protein_g") or 0.0)
        if protein <= 0:
            continue
        if kcal <= 0:
            # A zero-kcal food has an unbounded protein-per-kcal ratio, so on
            # paper it satisfies any low-kcal window. The catalog holds 14 such
            # entries -- all decaf coffee at 0.1 g protein per 100 g -- and
            # reaching a 56 g protein floor from them means drinking 56 kg.
            # Anything at or above 1 g per 100 g is a real protein source and
            # does make the window satisfiable; below that the "solution" is
            # not food, so it does not count as one.
            if protein >= 1.0:
                return False
            continue
        best = max(best, protein / kcal)
    return best * kcal_hi < prot_lo


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
    if not _windows_unsatisfiable(
        task.s0.profile.windows, task.s0.catalog, task.s0.profile.allergies
    ):
        issues.append("conflict windows are satisfiable")
    return issues


def _validate_evaluate(task: Task, query: str) -> list[str]:
    issues: list[str] = []
    if task.oracle.profile is None:
        issues.append("evaluate oracle profile is missing")
    if task.oracle.ledger is None:
        issues.append("evaluate oracle ledger is missing")
    if _INSTEAD.search(query):
        issues.append("evaluate query asks what instead")
    plan = task.oracle.last_plan
    if not plan:
        issues.append("evaluate last_plan is empty")
        return issues
    row = next((item for item in EVALUATE_ROWS if item.query == task.query), None)
    if row is not None:
        if len(row.items) != len(plan):
            issues.append("evaluate last_plan does not match the row")
        else:
            for (food_id, phrase), item in zip(row.items, plan):
                grams = resolve_portion(food_id, phrase, task.s0.catalog)
                if grams is None or float(item["grams"]) != float(grams):
                    issues.append(
                        f"evaluate grams {item.get('grams')} != resolve_portion {grams}"
                    )
    for item in plan:
        food_id = str(item["food_id"])
        entry = task.s0.catalog.get(food_id) or {}
        names = [food_id.replace("_", " "), str(entry.get("name") or "")]
        names.extend(str(alias) for alias in (entry.get("aliases") or []))
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
    return issues
