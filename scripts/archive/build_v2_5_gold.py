"""Build v2.5-gold (NutriEnv v1.0 Gold Release, 128 tasks) from v2.3-gold.

Appends:
- 6 Dietary Myths evaluation tasks (adr26-eval-1301..1306)
- 1 Ledger Amendment task (adr26-log-1307)
- 1 Multi-Meal Joint Budgeting composite task (adr26-comp-1308)

Run: ``uv run python scripts/build_v2_5_gold.py``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

from nutrienv.bench.pipeline.freezer import task_to_item
from nutrienv.bench.pipeline.roster import ROSTER, profile_for
from nutrienv.bench.realize import Oracle, Task, bind_evaluate_reasons, compose_oracles
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import validate_draft
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.daily_windows import derive_daily_windows, plan_windows_for_meal
from nutrienv.world.types import LedgerRow, WorldState, ledger_totals, normalize_tags

_ROOT = Path(__file__).resolve().parents[1]
_V23 = _ROOT / "data" / "splits" / "v2.3-gold.json"
_V23_MINI = _ROOT / "data" / "splits" / "v2.3-mini.json"
_V25 = _ROOT / "data" / "splits" / "v2.5-gold.json"
_V25_MINI = _ROOT / "data" / "splits" / "v2.5-mini.json"
_NUTRIENV_GOLD = _ROOT / "data" / "splits" / "nutrienv-gold.json"
_NUTRIENV_MINI = _ROOT / "data" / "splits" / "nutrienv-mini.json"


def _person(user_id: str):
    for person in ROSTER:
        if person.user_id == user_id:
            return person
    raise KeyError(user_id)


def _eval_task(
    task_id: str,
    user_id: str,
    meal_slot: str,
    meal: list[dict],
    query: str,
    catalog,
) -> dict:
    person = _person(user_id)
    profile = profile_for(person)
    s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
    allergens = tuple(normalize_tags(list(profile.allergies)))
    windows = plan_windows_for_meal(profile.windows, {}, meal_slot)
    assert windows is not None, f"empty windows for {user_id} {meal_slot}"
    auto_reasons = bind_evaluate_reasons(meal, windows, catalog, allergens)
    verdict = "reject" if auto_reasons else "accept"
    oracle = Oracle(
        profile=copy.deepcopy(profile),
        last_plan=[] if verdict == "reject" else copy.deepcopy(meal),
        last_verdict=verdict,
        last_reasons=tuple(auto_reasons),
        evaluated_plan=copy.deepcopy(meal),
        ledger=(),
        plan_windows=windows,
    )
    task = Task(task_id, "evaluate", query, s0, oracle, (), person.persona, "tier1")
    assert not [it for it in validate_draft(task) if "update oracle" not in it]
    item = task_to_item(task)
    item["id"] = task_id
    return item


def _new_v25_tasks(catalog) -> list[dict]:
    tasks = []

    # 1. Myth 1: Toast + Fresh Orange Juice Sugar Bomb (roster-cam, cut female, breakfast)
    # 2707710 (Bread, whole wheat, toasted: 44g = 2 slices) + 2709187 (Orange juice: 496g = 16 fl oz)
    tasks.append(
        _eval_task(
            "adr26-eval-1301",
            "roster-cam",
            "breakfast",
            [
                {"food_id": "2707710", "grams": 44.0},
                {"food_id": "2709187", "grams": 496.0},
            ],
            "I am on a strict cut. For breakfast, can I have 2 slices of whole wheat bread, toasted, with a 16 fl oz glass of orange juice?",
            catalog,
        )
    )

    # 2. Myth 2: Chicken Salad with 6 Tbsp Ranch Dressing (roster-cam, cut female, lunch)
    # 2705956 (Chicken breast: 120g) + 2710212 (Ranch dressing: 90g)
    tasks.append(
        _eval_task(
            "adr26-eval-1302",
            "roster-cam",
            "lunch",
            [
                {"food_id": "2705956", "grams": 120.0},
                {"food_id": "2710212", "grams": 90.0},
            ],
            "I am having a light lunch with 120g of cooked chicken breast, topped with 6 tablespoons of ranch dressing. Can you evaluate if this fits my lunch window?",
            catalog,
        )
    )

    # 3. Myth 3: Boiled Egg + Chewy Granola Bars (roster-sam, 75yo low energy female, breakfast)
    # 2707158 (Egg, whole, boiled: 55g) + 2708101 (Cereal or Granola bar, NFS: 86g = 2 bars)
    tasks.append(
        _eval_task(
            "adr26-eval-1303",
            "roster-sam",
            "breakfast",
            [
                {"food_id": "2707158", "grams": 55.0},
                {"food_id": "2708101", "grams": 86.0},
            ],
            "For my morning meal, I plan to have one hard-boiled egg and two cereal or granola bar snacks. Could you evaluate if this fits my breakfast plan?",
            catalog,
        )
    )

    # 4. Myth 4: Rice + Chicken + Fried Vegetable Chips (roster-cam, cut female, lunch)
    # 2708408 (Rice, white, cooked: 118g) + 2705956 (Chicken breast: 100g) + 2709447 (Vegetable chips: 60g)
    tasks.append(
        _eval_task(
            "adr26-eval-1304",
            "roster-cam",
            "lunch",
            [
                {"food_id": "2708408", "grams": 118.0},
                {"food_id": "2705956", "grams": 100.0},
                {"food_id": "2709447", "grams": 60.0},
            ],
            "For lunch, I want a cup of white rice, cooked, 100g of roasted chicken breast, and two cups of vegetable chips as a healthy side. Can you evaluate this?",
            catalog,
        )
    )

    # 5. Myth 5: Chicken + Soda Crackers (roster-sam, low energy female, lunch)
    # 2705956 (Chicken breast: 100g) + 2708132 (Crackers, NFS: 100g)
    tasks.append(
        _eval_task(
            "adr26-eval-1305",
            "roster-sam",
            "lunch",
            [
                {"food_id": "2705956", "grams": 100.0},
                {"food_id": "2708132", "grams": 100.0},
            ],
            "I want a plain, gentle lunch for my digestion: 100g of boiled chicken breast with two cups of crackers, nfs. Please evaluate if this is compliant with my targets.",
            catalog,
        )
    )

    # 6. Myth 6: Toast + Concentrated Dried Fruit (roster-cam, cut female, breakfast)
    # 2707710 (Bread, whole wheat, toasted: 22g = 1 slice) + 2709195 (Dried, fruit, NFS: 160g)
    tasks.append(
        _eval_task(
            "adr26-eval-1306",
            "roster-cam",
            "breakfast",
            [
                {"food_id": "2707710", "grams": 22.0},
                {"food_id": "2709195", "grams": 160.0},
            ],
            "I am having one slice of whole wheat bread, toasted, along with a cup of dried, fruit for breakfast. Can you evaluate if this fits my morning targets?",
            catalog,
        )
    )

    # 7. Type A: Ledger Amendment (adr26-log-1307)
    person_ben = _person("roster-ben")
    prof_ben = profile_for(person_ben)
    s0_ledger = [
        LedgerRow("2708408", 120.0, "today-lunch"),
        LedgerRow("2705956", 100.0, "today-lunch"),
    ]
    s0_ben = WorldState(profile=prof_ben, ledger=s0_ledger, catalog=catalog)
    exp_ledger = (
        LedgerRow("2708408", 60.0, "today-lunch"),
        LedgerRow("2705956", 100.0, "today-lunch"),
    )
    amend_oracle = Oracle(
        profile=copy.deepcopy(prof_ben),
        last_plan=None,
        ledger=exp_ledger,
    )
    amend_task = Task(
        "adr26-log-1307",
        "log",
        "In my lunch diary from earlier today, I accidentally logged 120g of white rice, cooked, but I only "
        "actually ate half a bowl (60 grams). Please amend my lunch record to correct the rice portion to 60g.",
        s0_ben,
        amend_oracle,
        (),
        person_ben.persona,
        "tier1",
    )
    assert not [it for it in validate_draft(amend_task) if "update oracle" not in it]
    item_amend = task_to_item(amend_task)
    item_amend["id"] = "adr26-log-1307"
    tasks.append(item_amend)

    # 8. Type C: Multi-Meal Joint Budgeting (adr26-comp-1308)
    person_ada = _person("roster-ada")
    prof_ada = profile_for(person_ada)
    history_ada = [
        LedgerRow("2707710", 44.0, "today-breakfast"),  # Toast
        LedgerRow("2707158", 55.0, "today-breakfast"),  # Egg
    ]
    s0_ada = WorldState(profile=prof_ada, ledger=history_ada, catalog=catalog)
    eaten_ada = ledger_totals(history_ada, catalog)
    dinner_win_ada = plan_windows_for_meal(prof_ada.windows, eaten_ada, "dinner")
    comp_oracle = Oracle(
        profile=copy.deepcopy(prof_ada),
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=dinner_win_ada,
        ledger=tuple(history_ada),
    )
    comp_task = Task(
        "adr26-rec-1308",
        "recommend",
        "I already logged my breakfast. Could you recommend a healthy dinner plan that meets my daily targets?",
        s0_ada,
        comp_oracle,
        (),
        person_ada.persona,
        "tier1",
    )
    assert not [it for it in validate_draft(comp_task) if "update oracle" not in it]
    item_comp = task_to_item(comp_task)
    item_comp["id"] = "adr26-rec-1308"
    tasks.append(item_comp)

    return tasks


def main() -> None:
    catalog = load_catalog(_ROOT / "data" / "fdc" / "catalog-v2.sqlite")
    payload = json.loads(_V23.read_text(encoding="utf-8"))
    items = copy.deepcopy(payload["items"])

    # 1. Upgrade adr25-eval-1201 to allow proactive profile update age_y=30
    person_cam = _person("roster-cam")
    prof_cam = profile_for(person_cam)
    win_30 = derive_daily_windows(
        sex=prof_cam.sex,
        age_y=30,
        height_cm=prof_cam.height_cm,
        weight_kg=prof_cam.weight_kg,
        activity=prof_cam.activity,
        phase=prof_cam.phase,
    )
    for item in items:
        if item["id"] == "adr25-eval-1201":
            item["family"] = "composite"
            eval_child = copy.deepcopy(item["oracle"])
            eval_child["profile"] = {
                "age_y": 30,
                "windows": {k: list(v) for k, v in win_30.items()},
            }
            item["oracle"] = {
                "sub_oracles": [
                    {
                        "profile": {
                            "age_y": 30,
                            "windows": {k: list(v) for k, v in win_30.items()},
                        }
                    },
                    eval_child,
                ]
            }

    # 2. Append 8 new ADR 0026 tasks
    new_tasks = _new_v25_tasks(catalog)
    seen = {item["id"] for item in items}
    for t in new_tasks:
        if t["id"] in seen:
            raise ValueError(f"duplicate id {t['id']}")
        items.append(t)
        seen.add(t["id"])

    payload["version"] = "v2.5-gold"
    payload["parent"] = "v2.3-gold"
    payload["items"] = items
    _V25.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Sync to official public release: data/splits/nutrienv-gold.json
    payload_pub = copy.deepcopy(payload)
    payload_pub["version"] = "nutrienv-v1.0-gold"
    _NUTRIENV_GOLD.write_text(json.dumps(payload_pub, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Mini set
    mini23 = json.loads(_V23_MINI.read_text(encoding="utf-8"))
    gold_by = {item["id"]: item for item in items}
    mini_items = [copy.deepcopy(gold_by[item["id"]]) for item in mini23["items"] if item["id"] in gold_by]
    mini_items.append(copy.deepcopy(gold_by["adr26-eval-1301"]))
    mini_items.append(copy.deepcopy(gold_by["adr26-log-1307"]))
    mini25 = {
        "version": "v2.5-mini",
        "parent": "v2.3-mini",
        "items": mini_items,
    }
    _V25_MINI.write_text(json.dumps(mini25, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mini_pub = copy.deepcopy(mini25)
    mini_pub["version"] = "nutrienv-v1.0-mini"
    _NUTRIENV_MINI.write_text(json.dumps(mini_pub, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    loaded = load_split(_V25, catalog=catalog)
    print(f"Successfully compiled {_V25}: {len(loaded)} tasks (Public NutriEnv v1.0 Gold: {len(loaded)})")
    print(f"Successfully compiled {_V25_MINI}: {len(mini_items)} tasks (Public NutriEnv v1.0 Mini: {len(mini_items)})")


if __name__ == "__main__":
    main()
