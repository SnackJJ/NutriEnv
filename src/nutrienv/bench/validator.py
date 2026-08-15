"""Reject leaky, unresolvable, or unachievable draft tasks.

This is a factory gate, not a Scorer. Admitted exam items still need a human
to check that the spoken query entails the scored end state.
"""

from __future__ import annotations

import itertools
import re

from nutrienv.world.portions import OUNCE_GRAMS, resolve_portion
from nutrienv.world.types import LedgerRow, ledger_totals, normalize_tags

from .generator import Task
from .realizations import EVALUATE_ROWS, UPDATE_ROWS

__all__ = ["validate_draft", "semantic_key", "fitting_plan"]

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
_KCAL_RATIO_CAP = {
    "protein_g": 0.25,
    "carb_g": 0.25,
    "fat_g": 1.0 / 9.0,
    "fiber_g": 0.5,
}


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
    profile = _judged_profile(task)
    if not _staple_plan_fits(task.s0.catalog, profile.windows, profile.allergies):
        issues.append("condition meal window has no safe staple plan")
    return issues


def _windows_unsatisfiable(
    windows: dict,
    catalog,
    allergies: tuple[str, ...] = (),
    floor_nutrient: str = "protein_g",
    ceiling_nutrient: str = "kcal",
) -> bool:
    banned = _tag_set(allergies)
    ceiling_value = float(windows.get(ceiling_nutrient, (0.0, 0.0))[1])
    floor_value = float(windows.get(floor_nutrient, (0.0, 0.0))[0])
    best = 0.0
    for entry in catalog.values():
        try:
            tags = _tag_set(entry.get("allergen_tags") or [])
        except ValueError:
            continue
        if tags & banned:
            continue
        nutrients = entry.get("nutrients") or {}
        ceiling = float(nutrients.get(ceiling_nutrient) or 0.0)
        floor = float(nutrients.get(floor_nutrient) or 0.0)
        if floor <= 0:
            continue
        if ceiling <= 0:
            # A zero-denominator food has an unbounded floor/ceiling ratio, so
            # on paper it satisfies any tight ceiling. The catalog holds 14
            # zero-kcal entries -- all decaf coffee at 0.1 g protein per 100 g
            # -- and reaching a 56 g protein floor from them means drinking
            # 56 kg. Anything at or above 1 g per 100 g is a real source of
            # the floor nutrient and does make the window satisfiable; below
            # that the "solution" is not food, so it does not count as one.
            if floor >= 1.0:
                return False
            continue
        ratio = floor / ceiling
        if ceiling_nutrient == "kcal":
            # Atwater factors: protein and carbohydrate yield 4 kcal/g, fat
            # yields 9 kcal/g. No food can exceed 0.25 g protein or carb, or
            # 1/9 g fat, per kcal. The fibre cap (0.5 g/kcal) is a pragmatic
            # bound rather than physics; catalog conflicts are already
            # infeasible under the observed maximum (~0.353 g/kcal). Sodium
            # carries no energy. Catalog rounding sometimes reports ratios
            # above the Atwater caps; trust physics, not the artifact.
            cap = _KCAL_RATIO_CAP.get(floor_nutrient)
            if cap is not None:
                ratio = min(ratio, cap)
        best = max(best, ratio)
    return best * ceiling_value < floor_value


def _any_pair_unsatisfiable(windows: dict, catalog, allergies: tuple[str, ...] = ()) -> bool:
    keys = list(windows)
    for floor_nutrient in keys:
        if float(windows[floor_nutrient][0]) <= 0:
            continue
        for ceiling_nutrient in keys:
            if ceiling_nutrient == floor_nutrient:
                continue
            if _windows_unsatisfiable(
                windows,
                catalog,
                allergies,
                floor_nutrient=floor_nutrient,
                ceiling_nutrient=ceiling_nutrient,
            ):
                return True
    return False


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
    if not _any_pair_unsatisfiable(
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
