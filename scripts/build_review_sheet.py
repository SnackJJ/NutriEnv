#!/usr/bin/env python3
"""Export a frozen split as a human-review sheet (query vs scored end state)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench.split import load_split  # noqa: E402
from nutrienv.world.catalog import FoodCatalog  # noqa: E402
from nutrienv.world.portions import (  # noqa: E402
    GRAM_UNITS,
    OUNCE_GRAMS,
    OUNCE_UNITS,
    UNIT_SYNONYMS,
    resolve_portion,
)
from nutrienv.world.types import Profile  # noqa: E402

NICE = {}
for _i in range(1, 33):
    _n = _i / 4
    NICE[_n] = str(_i // 4) if _i % 4 == 0 else str(_n)
NICE.update({1 / 3: "1/3", 2 / 3: "2/3", 4 / 3: "4/3", 5 / 3: "5/3"})
SHOWN = ("allergies", "windows", "plan_preset")
PROFILE_FIELDS = ("user_id", "allergies", "medications", "windows", "plan_preset", "version")
MEASURE = re.compile(
    r"(?:(?:about|approx(?:imately)?|roughly|~)\s*)?"
    r"(?:\d+(?:\.\d+)?|\d+\s+\d+/\d+|\d+/\d+|half|quarter|third|"
    r"a|an|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(?:cups?|slices?|cans?|bowls?|handfuls?|pieces?|"
    r"oz|ounces?|tbsp|tbsps?|tablespoons?|tsp|tsps?|teaspoons?)\b",
    re.I,
)
HALF_A = re.compile(r"\bhalf\s+a\b", re.I)
GRAM_ML = re.compile(r"\d[\d./]*\s*(?:g|grams?|ml)\b", re.I)
STATED_G = re.compile(
    r"(?:(?:about|approx(?:imately)?|roughly)\s+|~)?(\d+(?:\.\d+)?)\s*(?:g|grams?)\b",
    re.I,
)
COOKED_Q = re.compile(r"\b(?:cooked|steamed|boiled|roasted|grilled|baked)\b", re.I)
RAW_Q = re.compile(r"\b(?:raw|uncooked|fresh|dry)\b", re.I)
COOKED_NAME = re.compile(r"\bcooked\b", re.I)
RAW_NAME = re.compile(r"\b(?:raw|uncooked|dried|dry)\b", re.I)
FAMILIES = ("log", "recommend", "evaluate", "update", "constrain")
RISKS = (
    "spoken_portion", "multi_candidate_food", "unexplained_grams",
    "state_unpinned", "multi_window", "endpoint_move", "allergen_removal",
)


def _num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _canonical(catalog: FoodCatalog, food_id: str) -> str:
    resolver = getattr(catalog, "canonical_id", None)
    if callable(resolver) and food_id in catalog:
        return str(resolver(food_id))
    return food_id


# Explicit whitelist. New grammar units (fl_oz, …) stay out of the gloss
# unless they are closer to how the user spoke than cup/tbsp/slice/….
# Do not derive this from UNIT_SYNONYMS: adding fl_oz would turn
# milk_whole 122 g into "4 x fl_oz" instead of "0.5 x cup".
_EXPLAIN_UNITS = frozenset(
    {"cup", "tbsp", "tsp", "slice", "piece", "can", "serving", "g", "oz"}
)


def explain_grams(food_id: str, grams: float, catalog: object) -> str | None:
    """Household-measure gloss, or None if nothing clean divides."""
    entry = catalog[food_id] if food_id in catalog else None  # type: ignore[operator]
    if not isinstance(entry, dict):
        return None
    grams_f = float(grams)
    found = []
    for unit, gpu in {**(entry.get("portions") or {}), "oz": OUNCE_GRAMS, "g": 1.0}.items():
        if unit not in _EXPLAIN_UNITS or not _num(gpu) or gpu <= 0:
            continue
        ratio = grams_f / float(gpu)
        for nice, label in NICE.items():
            if abs(ratio - nice) <= 0.005:
                found.append((abs(ratio - round(ratio)), -float(gpu), unit, label, float(gpu)))
                break
    if not found:
        return None
    _, _, unit, label, gpu = min(found)
    if resolve_portion(food_id, f"{label} {unit}", catalog) != grams_f:
        return None
    return f"{label} x {unit} ({gpu} g) = {grams_f} g"


def _unit_in_query(query: str, unit: str) -> bool:
    words = {unit.lower()}
    for spoken, key in UNIT_SYNONYMS.items():
        if key == unit:
            words.add(spoken)
    if unit == "g":
        words.update(GRAM_UNITS)
    if unit == "oz":
        words.update(OUNCE_UNITS)
    return any(re.search(rf"\b{re.escape(word)}\b", query, re.I) for word in words)


def _aliases(entry: dict, food_id: str) -> list[str]:
    return [str(a) for a in (entry.get("aliases") or []) if str(a).strip()] or [
        str(entry.get("name") or food_id).split(",")[0].strip()
    ]


def _candidate_term(query: str, entry: dict, food_id: str) -> str:
    """Prefer a food phrase actually spoken in the query; else shortest alias."""
    phrases: list[str] = []
    name = str(entry.get("name") or "").strip()
    if name:
        phrases.append(name.split(",")[0].strip())
        phrases.append(name.split()[0].strip(",;:"))
    phrases.extend(str(a).strip() for a in (entry.get("aliases") or []) if str(a).strip())
    phrases.append(food_id.replace("_", " "))
    spoken = []
    for phrase in phrases:
        if len(phrase) >= 2 and re.search(rf"\b{re.escape(phrase)}\b", query, re.I):
            spoken.append(phrase)
    if spoken:
        return max(spoken, key=len)
    aliases = _aliases(entry, food_id)
    return min(aliases, key=len) if aliases else food_id


def _name_head(name: str) -> str:
    return (name or "").split(",")[0].strip().lower()


def _candidates(catalog: FoodCatalog, food_id: str, entry: dict, term: str) -> list[dict]:
    skip = {food_id, _canonical(catalog, food_id)}
    heads = {_name_head(str(entry.get("name") or "")), term.split(",")[0].strip().lower()}
    heads.discard("")
    sibs, rest = [], []
    for hit in catalog.search(term, limit=60):
        hid = hit["food_id"]
        if hid in skip:
            continue
        rec = {"food_id": hid, "name": hit.get("name") or ""}
        if _name_head(rec["name"]) in heads:
            sibs.append(rec)
        else:
            rest.append(rec)
    sibs.sort(key=lambda rec: rec["name"].count(","))
    out, seen = [], set()
    for rec in sibs + rest:
        if rec["food_id"] in seen:
            continue
        seen.add(rec["food_id"])
        out.append(rec)
        if len(out) == 5:
            break
    return out


def food_row(row: dict, catalog: FoodCatalog, *, query: str, kind: str) -> dict:
    food_id, grams = str(row["food_id"]), row["grams"]
    entry = catalog[food_id]
    gloss = explain_grams(food_id, float(grams), catalog)
    unit = gloss.split(" x ", 1)[1].split(" (", 1)[0] if gloss else ""
    nutrients = {
        str(k): round(float(v) * float(grams) / 100.0, 2)
        for k, v in (entry.get("nutrients") or {}).items()
        if _num(v)
    }
    out = {
        "food_id": food_id,
        "scored_food_id": _canonical(catalog, food_id),
        "name": entry.get("name") or "",
        "fdc_id": entry.get("fdc_id"),
        "data_type": entry.get("data_type"),
        "grams": grams,
        "portions": entry.get("portions") or {},
        "grams_explained": gloss,
        "grams_explained_is_derived": bool(gloss) and not _unit_in_query(query, unit),
        "aliases": list(entry.get("aliases") or []),
        "allergen_tags": list(entry.get("allergen_tags") or []),
        "nutrients_at_grams": nutrients,
        "other_candidates": _candidates(
            catalog, food_id, entry, _candidate_term(query, entry, food_id)
        ),
    }
    if kind == "ledger":
        out["eaten_at"] = row.get("eaten_at")
    return out


def _plan_scoring(oracle: dict) -> bool:
    return (
        "last_plan" in oracle
        or bool(oracle.get("plan_must_be_safe"))
        or bool(oracle.get("plan_must_fit_windows"))
    )


def contract_sentence(family: str, oracle: dict, allergens: bool) -> str:
    safety = " Allergen tags on any submitted plan are enforced." if allergens else ""
    if oracle.get("ledger_tail") is not None:
        return (
            "The scorer compares the ledger tail to the expected food rows "
            "(canonical scored_food_id, grams, eaten_at)."
        )
    if "last_plan" in oracle:
        if oracle.get("last_plan"):
            return (
                "The scorer compares last_plan to the expected food rows exactly "
                "(canonical scored_food_id, grams)." + safety
            )
        return (
            "The scorer requires a non-empty plan that fits the judged nutrient windows."
            + safety
        )
    if family == "update" or isinstance(oracle.get("profile"), dict):
        return (
            "The scorer compares the entire materialized profile; the ledger must remain at s0."
        )
    if oracle.get("allow_empty_plan"):
        return (
            "The scorer allows an empty plan; leaving the starting last_plan in place "
            "is scored against the windows." + safety
        )
    return "The scorer compares the end state to this item's oracle."


def _profile_dict(profile: Profile) -> dict:
    return {
        "user_id": profile.user_id,
        "allergies": list(profile.allergies),
        "medications": list(profile.medications),
        "windows": {key: [bounds[0], bounds[1]] for key, bounds in profile.windows.items()},
        "plan_preset": dict(profile.plan_preset) if isinstance(profile.plan_preset, dict) else profile.plan_preset,
        "version": profile.version,
    }


def s0_view(raw_s0: dict, catalog: FoodCatalog, query: str, profile: Profile) -> dict:
    material = _profile_dict(profile)
    return {
        "allergies": material["allergies"],
        "windows": material["windows"],
        "plan_preset": material["plan_preset"],
        "other_profile_fields": {key: material[key] for key in ("user_id", "medications", "version")},
        "ledger": [
            food_row(row, catalog, query=query, kind="ledger")
            for row in raw_s0.get("ledger") or []
        ],
        "last_plan": [
            food_row(row, catalog, query=query, kind="plan")
            for row in raw_s0.get("last_plan") or []
        ],
    }


def _field(name: str, frm: object, to: object) -> dict:
    entry = {"field": name, "from": frm, "to": to, "changed": frm != to}
    if _num(frm) and _num(to):
        entry["delta"] = to - frm
    if isinstance(frm, list) or isinstance(to, list):
        added, removed = sorted(set(to or []) - set(frm or [])), sorted(set(frm or []) - set(to or []))
        entry.update(added=added, removed=removed, changed=bool(added or removed) or frm != to)
    return entry


def profile_diff(family: str, s0_profile: Profile, oracle_profile: Profile | None) -> list[dict]:
    if family != "update" or oracle_profile is None:
        return []
    before, after = _profile_dict(s0_profile), _profile_dict(oracle_profile)
    out = []
    for key in PROFILE_FIELDS:
        if key != "windows":
            out.append(_field(key, before[key], after[key]))
            continue
        s0w, orw = before.get("windows") or {}, after.get("windows") or {}
        for nut in dict.fromkeys([*s0w, *orw]):
            frm_b, to_b = s0w.get(nut) or [None, None], orw.get(nut) or [None, None]
            out.append(_field(f"windows.{nut}.floor", frm_b[0], to_b[0]))
            out.append(_field(f"windows.{nut}.ceiling", frm_b[1], to_b[1]))
    return out


def _windows_of(oracle: dict, s0_profile: dict) -> tuple[dict, str]:
    if oracle.get("plan_windows") is not None:
        return oracle["plan_windows"], "plan_windows"
    return s0_profile.get("windows") or {}, "profile"


def _unrounded_totals(rows: list[dict], catalog: FoodCatalog) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        entry = catalog[row["food_id"]]
        grams = float(row["grams"])
        for key, amount in (entry.get("nutrients") or {}).items():
            if _num(amount):
                totals[str(key)] = totals.get(str(key), 0.0) + float(amount) * grams / 100.0
    return totals


def window_check(oracle: dict, s0_profile: dict, rows: list[dict], catalog: FoodCatalog) -> list[dict]:
    if not oracle.get("plan_must_fit_windows"):
        return []
    windows, source = _windows_of(oracle, s0_profile)
    if not rows:
        return [
            {"nutrient": nut, "total": None, "window": [bounds[0], bounds[1]],
             "source": source, "inside": None}
            for nut, bounds in windows.items()
        ]
    totals = _unrounded_totals(rows, catalog)
    out = []
    for nut, bounds in windows.items():
        total = round(totals.get(nut, 0.0), 2)
        lo, hi = bounds[0], bounds[1]
        out.append({"nutrient": nut, "total": total, "window": [lo, hi],
                    "source": source, "inside": lo <= total <= hi})
    for nut, total in totals.items():
        if nut not in windows:
            out.append({"nutrient": nut, "total": round(total, 2), "window": None,
                        "source": source, "inside": None})
    return out


def _spoken(query: str, rows: list[dict]) -> bool:
    if MEASURE.search(query) or HALF_A.search(query):
        return True
    aliases = []
    for row in rows:
        aliases.extend(a for a in (row.get("aliases") or []) if len(str(a)) >= 3)
        head = str(row.get("name") or "").split(",")[0].strip()
        if len(head) >= 3:
            aliases.append(head)
    if any(re.search(rf"\b(?:a|an)\s+{re.escape(str(a))}\b", query, re.I) for a in aliases):
        return True
    return bool(aliases) and not GRAM_ML.search(query) and any(
        re.search(rf"\b{re.escape(str(a))}\b", query, re.I) for a in aliases
    )


def _stated_masses(query: str) -> set[float]:
    return {float(m.group(1)) for m in STATED_G.finditer(query)}


def _grams_in_query(query: str, grams: object) -> bool:
    return any(value == float(grams) for value in _stated_masses(query))


def _name_states(name: str) -> tuple[bool, bool]:
    text = re.sub(r"\bdry heat\b", " ", name, flags=re.I)
    return bool(RAW_NAME.search(text)), bool(COOKED_NAME.search(text))


def _genuine_opposite(catalog: FoodCatalog, term: str, row: dict, want_raw: bool) -> bool:
    if not term:
        return False
    state = RAW_NAME if want_raw else COOKED_NAME
    skip = {row["food_id"], row.get("scored_food_id")}
    head = str(row.get("name") or "").split(",")[0].split()[0]
    needles = {tok for tok in (term.lower(), head.lower()) if tok}
    hits = list(catalog.search(term, limit=40))
    hits.extend(catalog.search(f"{term} {'raw' if want_raw else 'cooked'}", limit=6))
    seen: set[str] = set()
    for hit in hits:
        hid = hit["food_id"]
        if hid in skip or hid in seen:
            continue
        seen.add(hid)
        hname = hit.get("name") or ""
        if not state.search(re.sub(r"\bdry heat\b", " ", hname, flags=re.I)):
            continue
        for field in hname.split(",")[:2]:
            if needles & set(re.findall(r"[a-z0-9]+", field.lower())):
                return True
    return False


def _state_unpinned(query: str, row: dict, catalog: FoodCatalog) -> bool:
    name = str(row.get("name") or "")
    raw, cooked = _name_states(name)
    if not raw and not cooked:
        return False
    if cooked and not raw and COOKED_Q.search(query):
        return False
    if raw and not cooked and RAW_Q.search(query):
        return False
    entry = {"name": name, "aliases": row.get("aliases") or []}
    terms = list(dict.fromkeys(t for t in (
        _candidate_term(query, entry, row["food_id"]),
        min(_aliases(entry, row["food_id"]), key=len),
        name.split(",")[0].split()[0] if name else "",
    ) if t))

    def opposite(want_raw: bool) -> bool:
        return any(_genuine_opposite(catalog, term, row, want_raw=want_raw) for term in terms)

    if cooked and not raw:
        return opposite(True)
    if raw and not cooked:
        return opposite(False)
    fire = False
    if cooked and not COOKED_Q.search(query):
        fire = fire or opposite(True)
    if raw and not RAW_Q.search(query):
        fire = fire or opposite(False)
    return fire


def risk_tags(query, family, s0_profile, oracle, rows, diffs, catalog) -> list[str]:
    flags = set()
    if _spoken(query, rows):
        flags.add("spoken_portion")
    if any(r.get("other_candidates") for r in rows):
        flags.add("multi_candidate_food")
    if any(r.get("grams_explained") is None and not _grams_in_query(query, r["grams"]) for r in rows):
        flags.add("unexplained_grams")
    if any(_state_unpinned(query, r, catalog) for r in rows):
        flags.add("state_unpinned")
    changed_nuts = {
        str(e["field"]).split(".")[1]
        for e in diffs
        if str(e["field"]).startswith("windows.") and e.get("changed")
    }
    if family == "update" and len(changed_nuts) >= 2:
        flags.add("multi_window")
    ends: dict[str, set] = {}
    for entry in diffs:
        parts = str(entry["field"]).split(".")
        if len(parts) == 3 and parts[0] == "windows" and entry.get("changed"):
            ends.setdefault(parts[1], set()).add(parts[2])
    if family == "update" and any(len(v) == 1 for v in ends.values()):
        flags.add("endpoint_move")
    if family == "update" and any(e["field"] == "allergies" and e.get("removed") for e in diffs):
        flags.add("allergen_removal")
    return [name for name in RISKS if name in flags]


def build_item(item: dict, catalog: FoodCatalog, task) -> dict:
    family, oracle, s0 = item["family"], item.get("oracle") or {}, item.get("s0") or {}
    query = item["query"]
    material = _profile_dict(task.s0.profile)
    if oracle.get("ledger_tail") is not None:
        kind, raw = "ledger_tail", oracle["ledger_tail"]
        row_kind = "ledger"
    elif "last_plan" in oracle:
        kind, raw = "last_plan", oracle.get("last_plan") or []
        row_kind = "plan"
    else:
        kind, raw = ("profile_only" if family == "update" else "no_plan_required"), []
        row_kind = "plan"
    rows = [food_row(r, catalog, query=query, kind=row_kind) for r in raw]
    diffs = profile_diff(family, task.s0.profile, task.oracle.profile)
    allergens = _plan_scoring(oracle)
    return {
        "id": item["id"], "family": family,
        "situations": list(item.get("situations") or []),
        "persona": item.get("persona") or "", "query": query,
        "contract": contract_sentence(family, oracle, allergens),
        "risk": risk_tags(query, family, material, oracle, rows, diffs, catalog),
        "s0": s0_view(s0, catalog, query, task.s0.profile),
        "expected": {
            "kind": kind, "rows": rows,
            "profile": oracle["profile"] if "profile" in oracle else "s0",
            "ledger": oracle["ledger"] if "ledger" in oracle else "s0",
        },
        "scored_plan_is_fixed": bool(rows),
        "allergens_are_enforced": allergens,
        "flags": {
            "plan_must_fit_windows": bool(oracle.get("plan_must_fit_windows", False)),
            "plan_must_be_safe": bool(oracle.get("plan_must_be_safe", False)),
            "allow_empty_plan": bool(oracle.get("allow_empty_plan", False)),
            "plan_windows": oracle.get("plan_windows") if "plan_windows" in oracle else None,
        },
        "window_check": window_check(oracle, material, rows, catalog),
        "profile_diff": diffs,
    }


def build(split_path: Path, *, allow_catalog_sha_mismatch: bool = False) -> dict:
    payload = json.loads(split_path.read_text(encoding="utf-8"))
    catalog_path = Path(payload["catalog"])
    if not catalog_path.is_absolute():
        catalog_path = _ROOT / catalog_path
    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    if digest != payload["catalog_sha256"]:
        message = (
            f"catalog sha256 mismatch: {catalog_path} is {digest}, "
            f"split wants {payload['catalog_sha256']}"
        )
        if not allow_catalog_sha_mismatch:
            raise SystemExit(message)
        print(f"warning: {message} (live catalog used anyway)", file=sys.stderr)
    catalog = FoodCatalog.from_sqlite(catalog_path)
    tasks = {task.id: task for task in load_split(split_path)}
    items = [build_item(item, catalog, tasks[item["id"]]) for item in payload["items"]]
    counts = Counter(i["family"] for i in items)
    return {
        "split": payload.get("version") or split_path.stem,
        "catalog": payload["catalog"],
        "catalog_sha256": payload["catalog_sha256"],
        "counts": {
            "total": len(items),
            "by_family": {n: counts[n] for n in FAMILIES if n in counts} or dict(counts),
        },
        "items": items,
    }


def _resolve(path: str) -> Path:
    target = Path(path)
    return target if target.is_absolute() else _ROOT / target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="data/splits/v0.5-gold.json")
    parser.add_argument("--out", default="reports/review-sheet.json")
    parser.add_argument(
        "--allow-catalog-sha-mismatch",
        action="store_true",
        help=(
            "Continue when the live catalog SHA differs from the split freeze "
            "hash. Default is to fail so unreviewed catalog drift cannot ship."
        ),
    )
    args = parser.parse_args(argv)
    out = _resolve(args.out)
    text = json.dumps(
        build(
            _resolve(args.split),
            allow_catalog_sha_mismatch=args.allow_catalog_sha_mismatch,
        ),
        indent=2,
        ensure_ascii=False,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    template = _ROOT / "reports" / "review_sheet_template.html"
    if template.is_file():
        out.with_suffix(".html").write_text(
            template.read_text(encoding="utf-8").replace("/*__REVIEW_DATA__*/", text),
            encoding="utf-8",
        )
    else:
        print("reports/review_sheet_template.html not found; skipping HTML assembly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
