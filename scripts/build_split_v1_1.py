#!/usr/bin/env python3
"""Build nutrienv-v1.1.json from nutrienv-v1.0.json (ADR 0014, 2026-09-28).

v1.1 is v1.0 re-derived under the AMDR daily windows, plus the content fixes the v1.0 backlog
held for a new version. Every window the split stores is rewritten from the current formula:

* ``s0.profile.windows`` and every oracle profile that carries windows (a body-fact update).
* every pinned ``plan_windows``. Its occasion and ledger basis are first *recovered* by
  reproducing the v1.0 pin from the v1.0 windows the file stores (the old formula needs no
  code: its output is in the file). An item whose pin no basis reproduces is refused, except
  the three amend items whose v1.0 pins are known stale (authored before the amend).
* the gold reasons of every evaluate child, re-bound on its new windows. A gold verdict that
  would flip is refused: that is an authoring decision, not a derivation.

The free recommendations take the Scorer's basis (the child's own ledger), which is what
repairs ``adr29-amend-01/03/04``. Content fixes are listed in ``CONTENT_FIXES``.

The documented reductions (``nutrienv-mini``, ``mini-fast``, ``mini-harness``) are rebuilt from
v1.1 with the same task ids.

    .venv/bin/python scripts/build_split_v1_1.py            # writes v1.1 and the reductions
    .venv/bin/python scripts/build_split_v1_1.py --check    # rebuild in memory, diff against the files
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench.realize import bind_evaluate_reasons  # noqa: E402
from nutrienv.bench.split import load_split  # noqa: E402
from nutrienv.world.daily_windows import (  # noqa: E402
    MEAL_ENERGY_SHARE,
    derive_profile_windows,
    plan_windows_for_meal,
)
from nutrienv.world.portion_evidence import portion_grams
from nutrienv.world.types import ledger_totals  # noqa: E402

SOURCE = _ROOT / "data" / "splits" / "nutrienv-v1.0.json"
TARGET = _ROOT / "data" / "splits" / "nutrienv-v1.1.json"
REVISIONS = TARGET.with_name("v1.1-content-revisions.json")
VERSION = "nutrienv-v1.1-mass-envelopes-20261005"
# The documented reductions (data/splits/README.md) keep their task ids and take v1.1's items;
# header fields that named v1.0 move with it.
REDUCTIONS = {
    "nutrienv-mini.json": {"version": "nutrienv-v1.1-mini-mass-envelopes-20261005", "parent": VERSION},
    "mini-fast.json": {"parent": VERSION},
    "mini-harness.json": {"parent": VERSION},
}
# Each file keeps its own layout (indent, trailing newline) so a diff shows only what changed.
_LAYOUT = {
    "nutrienv-v1.1.json": (2, ""),
    "nutrienv-mini.json": (2, "\n"),
    "mini-fast.json": (1, ""),
    "mini-harness.json": (2, "\n"),
}

# v1.0 pins authored on the ledger before the correction the query asks for (the v1.0 backlog).
STALE_PINS = frozenset({"adr29-amend-01", "adr29-amend-03", "adr29-amend-04"})
_ROUNDING = 0.005  # plan_windows are stored at 2 dp

# The adr29-conv baskets named three foods the catalog holds several entries for ("sushi",
# "ramen", "egg salad"), and models that resolved one to a sibling entry failed inventory_miss.
# Each is now named as the one entry the basket holds, so search_foods narrows to it. The sushi
# and ramen entries carry the same nutrients as the NFS rows they replace; the tuna roll that
# v1.0 let conv-05 alone use (13 ids for "12 items") is not in the basket and goes.
_BASKET_SWAPS = {"2708959": "2708961", "2709153": "2709158"}  # Sushi/Ramen NFS -> named entry
_BASKET_DROPS = frozenset({"2708965"})  # Sushi roll tuna
_BASKET_PHRASES = (
    ("sushi,", "California sushi roll,"),
    ("egg salad", "egg salad made with mayonnaise"),
    ("a ramen bowl,", "a ramen bowl with meat and egg,"),
    (", ramen,", ", ramen with meat and egg,"),
)
# "a serving" is the catalog's default portion (FNDDS qns, 18 g, the unchanged gold). v1.0's
# "a small single-serving snack pack" read as a retail pack (39-40 g) to 3 of 5 models.
_CRACKER_QUERY_OLD = "a small single-serving snack pack of sandwich crackers"
_CRACKER_QUERY_NEW = "a serving of sandwich crackers"

CONTENT_FIXES = {
    "adr24-comp-8256": (
        "query: 'a small single-serving snack pack' -> 'a serving' (the default portion, "
        "gold 18 g unchanged)"
    ),
    **{
        f"adr29-conv-0{i}": (
            "basket names California sushi roll / egg salad made with mayonnaise / ramen with "
            "meat and egg; 28 reviewed catalog ids represent the 12 named foods"
        )
        for i in range(1, 6)
    },
}


def _profile_windows_json(windows: dict) -> dict:
    return {key: [float(lo), float(hi)] for key, (lo, hi) in windows.items()}


def _close(a: dict, b: dict) -> bool:
    return set(a) == set(b) and all(
        abs(x - y) <= _ROUNDING for key in a for x, y in zip(a[key], b[key])
    )


def _raw_windows(raw: dict) -> dict:
    return {key: tuple(bounds) for key, bounds in raw.items()}


def _recover_basis(pinned: dict, daily_old: dict, bases: dict, catalog) -> list[tuple[str, str, bool]]:
    """Every (occasion, ledger basis, last_meal) whose v1.0 windows reproduce ``pinned``."""
    hits = []
    for name, rows in bases.items():
        eaten = ledger_totals(list(rows), catalog)
        for occasion in MEAL_ENERGY_SHARE:
            for last_meal in (False, True):
                got = plan_windows_for_meal(daily_old, eaten, occasion, last_meal=last_meal)
                if got is not None and _close(got, pinned):
                    hits.append((occasion, name, last_meal))
    return hits


def _apply_content_fixes(item: dict) -> None:
    if item["id"] == "adr24-comp-8256":
        assert item["query"].count(_CRACKER_QUERY_OLD) == 1, item["query"]
        item["query"] = item["query"].replace(_CRACKER_QUERY_OLD, _CRACKER_QUERY_NEW)
    if item["id"].startswith("adr29-conv-0"):
        query = item["query"]
        for old, new in _BASKET_PHRASES:
            if old in query:
                assert query.count(old) == 1, (item["id"], old)
                query = query.replace(old, new)
        for needle in ("California sushi roll", "made with mayonnaise", "with meat and egg"):
            assert needle in query, (item["id"], needle)
        item["query"] = query
        allowed = set(item["s0"]["allowed_food_ids"]) - _BASKET_DROPS
        assert set(_BASKET_SWAPS) <= allowed, item["id"]
        item["s0"]["allowed_food_ids"] = sorted(_BASKET_SWAPS.get(f, f) for f in allowed)


def _reviewed_food(option: dict, catalog) -> str:
    food_id = option["food_id"]
    if catalog[food_id]["name"] != option["catalog_name"]:
        raise ValueError(f"{food_id}: catalog name differs from the reviewed interpretation")
    return food_id


def _apply_gold_fixes(item: dict, revision: dict) -> None:
    children = item["oracle"].get("sub_oracles") or [item["oracle"]]
    for old, new in revision.get("ledger_food_swaps", {}).items():
        changed = False
        for child in children:
            for key in ("ledger", "ledger_tail"):
                if isinstance(child.get(key), list):
                    for row in child[key]:
                        if row["food_id"] == old:
                            row["food_id"] = new
                            changed = True
        if not changed:
            raise ValueError(f"{item['id']}: ledger food repair matched no gold row")
    if revision.get("high_protein"):
        recommendations = [child for child in children
                           if child.get("last_plan") == [] and not child.get("last_verdict")]
        if not recommendations:
            raise ValueError(f"{item['id']}: high-protein requirement has no recommendation")
        for child in recommendations:
            child["plan_high_protein"] = True
    for fix in revision.get("ledger_portion_fixes", []):
        changed = False
        for child in children:
            for key in ("ledger", "ledger_tail"):
                if not isinstance(child.get(key), list):
                    continue
                for row in child[key]:
                    if row["food_id"] == fix["food_id"]:
                        row["grams"] = fix["grams"]
                        changed = True
        if not changed:
            raise ValueError(f"{item['id']}: portion repair matched no gold row")
    for old, new in revision.get("evaluated_food_swaps", {}).items():
        changed = False
        for child in children:
            for row in child.get("evaluated_plan") or []:
                if row["food_id"] == old:
                    row["food_id"] = new
                    changed = True
        if not changed:
            raise ValueError(f"{item['id']}: evaluated food repair matched no candidate")


def _author_ledger_variants(item: dict, task, revision: dict) -> None:
    choices = revision.get("ledger_food_options", {})
    if not choices:
        return
    raw_children = item["oracle"].get("sub_oracles") or [item["oracle"]]
    children = task.oracle.sub_oracles or (task.oracle,)
    for raw_child, child in zip(raw_children, children):
        if child.ledger is None:
            continue
        candidates = []
        for row in child.ledger:
            base = {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
            options = [base]
            if row.food_id in choices:
                specification = choices[row.food_id]
                for option in specification["options"]:
                    food_id = _reviewed_food(option, task.s0.catalog)
                    grams = portion_grams(food_id, specification["portion"], task.s0.catalog)
                    options.append({**base, "food_id": food_id, "grams": grams})
            candidates.append(options)
        canonical = [options[0] for options in candidates]
        variants = [list(rows) for rows in itertools.product(*candidates)
                    if list(rows) != canonical]
        if variants:
            raw_child["ledger_variants"] = variants


def build(source: Path = SOURCE) -> tuple[dict, list[str]]:
    raw = json.loads(source.read_text(encoding="utf-8"))
    out = copy.deepcopy(raw)
    out["version"] = VERSION
    out["plan_mass_policy"] = "adult-meal-envelope-v1"
    out["parent"] = raw["version"]
    catalog_path = _ROOT / "data" / "fdc" / "catalog-v3.sqlite"
    out["catalog"] = str(catalog_path.relative_to(_ROOT))
    out["catalog_sha256"] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    notes: list[str] = []
    by_id = {item["id"]: item for item in out["items"]}
    for item in out["items"]:
        _apply_content_fixes(item)
        item["s0"]["plan_scope"] = "day"
    # Reviewed wording, default-portion repairs and explicit food interpretations remain data.
    # Refuse an independently revised source rather than silently overwriting it.
    revisions = json.loads(REVISIONS.read_text(encoding="utf-8"))["changes"]
    seen: set[str] = set()
    for revision in revisions:
        task_id = revision["task_id"]
        if task_id in seen:
            raise ValueError(f"duplicate content revision: {task_id}")
        seen.add(task_id)
        item = by_id[task_id]
        if item["query"] != revision["old_query"]:
            raise ValueError(f"{task_id}: query differs from the reviewed source")
        item["query"] = revision["new_query"]
        _apply_gold_fixes(item, revision)
        notes.append(f"{task_id}: {revision['reason']}")
    # Load the content-fixed items with the current code: ledgers, catalog and the evaluate
    # plans resolved exactly as the Scorer will see them.
    fixed_path = TARGET.with_suffix(".tmp.json")
    fixed_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    try:
        tasks = {task.id: task for task in load_split(fixed_path)}
    finally:
        fixed_path.unlink()

    # The v1.0 pins are reproduced on the v1.0 ledgers, before the content fixes moved any.
    originals = {task.id: task for task in load_split(source)}

    for revision in revisions:
        task = tasks[revision["task_id"]]
        item = by_id[task.id]
        if revision.get("inventory_options"):
            allowed = set(item["s0"]["allowed_food_ids"])
            for base, options in revision["inventory_options"].items():
                if base not in allowed:
                    raise ValueError(f"{task.id}: reviewed inventory food {base} is absent")
                allowed.update(_reviewed_food(option, task.s0.catalog) for option in options)
            item["s0"]["allowed_food_ids"] = sorted(allowed)
        for fix in revision.get("ledger_portion_fixes", []):
            if portion_grams(fix["food_id"], fix["portion"], task.s0.catalog) != fix["grams"]:
                raise ValueError(f"{task.id}: repaired gold disagrees with the portion manual")

    for task_id, item in by_id.items():
        task = tasks[task_id]
        original = originals[task_id]
        catalog = task.s0.catalog
        s0_old = _raw_windows(item["s0"]["profile"]["windows"])
        s0_new = derive_profile_windows(task.s0.profile)
        if s0_new is None:
            raise SystemExit(f"{task_id}: s0 profile has no body facts to derive from")
        item["s0"]["profile"]["windows"] = _profile_windows_json(s0_new)

        raw_children = item["oracle"].get("sub_oracles") or [item["oracle"]]
        children = task.oracle.sub_oracles or (task.oracle,)
        original_children = original.oracle.sub_oracles or (original.oracle,)
        tail = [row for child in children for row in (child.ledger_tail or ())]
        original_tail = [row for child in original_children for row in (child.ledger_tail or ())]
        for raw_child, child, original_child in zip(raw_children, children, original_children):
            raw_profile = raw_child.get("profile")
            daily_old, daily_new = s0_old, s0_new
            if isinstance(raw_profile, dict) and "windows" in raw_profile:
                # Stored as the keys that differ from S0; the loader merges them over S0's.
                daily_old = {**s0_old, **_raw_windows(raw_profile["windows"])}
                daily_new = child.profile.windows  # load_split re-derived it from the body patch
                raw_profile["windows"] = _profile_windows_json(
                    {k: v for k, v in daily_new.items() if tuple(v) != tuple(s0_new[k])}
                )
            pinned = raw_child.get("plan_windows")
            if pinned is None:
                continue
            bases = {"s0": tuple(task.s0.ledger), "s0+tail": (*task.s0.ledger, *tail)}
            if child.ledger is not None:
                bases["child"] = tuple(child.ledger)
            original_bases = {
                "s0": tuple(original.s0.ledger),
                "s0+tail": (*original.s0.ledger, *original_tail),
            }
            if original_child.ledger is not None:
                original_bases["child"] = tuple(original_child.ledger)
            hits = _recover_basis(_raw_windows(pinned), daily_old, original_bases, catalog)
            free = child.last_plan == [] and child.last_verdict is None
            if not hits and task_id in STALE_PINS:
                # The kcal floor is the day's floor times the occasion's share: no ledger moves
                # it, so it still names the occasion of a stale pin.
                hits = [
                    (occasion, "child", False)
                    for occasion, (share_lo, _) in MEAL_ENERGY_SHARE.items()
                    if abs(daily_old["kcal"][0] * share_lo - pinned["kcal"][0]) <= _ROUNDING
                ]
                notes.append(f"{task_id}: stale v1.0 pin (no basis reproduces it), occasion from kcal")
            if not hits:
                raise SystemExit(f"{task_id}: no occasion/ledger reproduces the v1.0 plan_windows")
            occasions = {occasion for occasion, _, _ in hits}
            if len({MEAL_ENERGY_SHARE[o] for o in occasions}) != 1 or any(lm for _, _, lm in hits):
                raise SystemExit(f"{task_id}: ambiguous v1.0 plan_windows basis {hits}")
            occasion = sorted(occasions)[0]
            scope = "snack" if occasion == "snack" else "meal"
            if item["s0"]["plan_scope"] not in {"day", scope}:
                raise ValueError(f"{task_id}: child plans have incompatible mass scopes")
            item["s0"]["plan_scope"] = scope
            recovered = {name for _, name, _ in hits}
            if free:
                # The Scorer's basis: the child's own ledger (ADR 0023, s4/s6).
                basis = "child" if "child" in bases else "s0+tail"
                if basis not in recovered and task_id not in STALE_PINS:
                    raise SystemExit(f"{task_id}: v1.0 pin was not on the Scorer's ledger {hits}")
                if basis not in recovered:
                    notes.append(f"{task_id}: stale v1.0 pin re-derived on the child's ledger")
            else:
                # Evaluate windows were bound on the day before the named meal.
                basis = "s0" if "s0" in recovered else sorted(recovered)[0]
            eaten = ledger_totals(list(bases[basis]), catalog)
            new = plan_windows_for_meal(daily_new, eaten, occasion)
            if new is None:
                raise SystemExit(f"{task_id}: empty v1.1 window intersection")
            raw_child["plan_windows"] = _profile_windows_json(new)

            if child.last_verdict is not None:
                named = child.evaluated_plan or child.last_plan or []
                profile = child.profile or task.s0.profile
                reasons = bind_evaluate_reasons(named, new, catalog, profile.allergies,
                                                plan_scope=item["s0"]["plan_scope"])
                old = tuple(child.last_reasons)
                if child.last_verdict == "accept" and reasons:
                    raise SystemExit(f"{task_id}: gold accept now binds {reasons}")
                if child.last_verdict == "reject":
                    if not reasons:
                        raise SystemExit(f"{task_id}: gold reject binds nothing on v1.1 windows")
                    if set(reasons) != set(old):
                        raw_child["last_reasons"] = list(reasons)
                        notes.append(f"{task_id}: reject reasons {list(old)} -> {list(reasons)}")
    for task_id, why in CONTENT_FIXES.items():
        notes.append(f"{task_id}: {why}")
    for revision in revisions:
        task_id = revision["task_id"]
        _author_ledger_variants(by_id[task_id], tasks[task_id], revision)
    return out, notes


def _in_order_of(template, value):
    """``value``, with every dict's keys in ``template``'s order where the two share them."""
    if isinstance(template, dict) and isinstance(value, dict):
        keys = [k for k in template if k in value] + [k for k in value if k not in template]
        return {k: _in_order_of(template.get(k), value[k]) for k in keys}
    if isinstance(template, list) and isinstance(value, list) and len(template) == len(value):
        return [_in_order_of(t, v) for t, v in zip(template, value)]
    return value


def reductions(exam: dict) -> dict[Path, dict]:
    """Each documented reduction rebuilt from ``exam``'s items, in its own task order."""
    by_id = {item["id"]: item for item in exam["items"]}
    out = {}
    for name, header in REDUCTIONS.items():
        path = TARGET.with_name(name)
        current = json.loads(path.read_text(encoding="utf-8"))
        rebuilt = {**current, **header, "catalog": exam["catalog"],
                   "catalog_sha256": exam["catalog_sha256"],
                   "plan_mass_policy": exam["plan_mass_policy"]}
        rebuilt["items"] = [_in_order_of(item, by_id[item["id"]]) for item in current["items"]]
        out[path] = rebuilt
    return out


def dump(path: Path, payload: dict) -> str:
    indent, tail = _LAYOUT[path.name]
    return json.dumps(payload, indent=indent, ensure_ascii=False) + tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare with the files, write nothing")
    args = parser.parse_args(argv)
    out, notes = build()
    files = {TARGET: dump(TARGET, out), **{p: dump(p, r) for p, r in reductions(out).items()}}
    for line in notes:
        print(line)
    if args.check:
        stale = [p.name for p, text in files.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != text]
        print("up to date" if not stale else f"differ from a rebuild: {', '.join(stale)}")
        return 1 if stale else 0
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
