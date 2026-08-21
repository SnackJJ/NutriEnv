"""Oracle reachability is a Bench capability over any loaded split.

Seams: ``check_achievable(tasks)`` (loaded Tasks in, report out — no path,
no assert); ``AchievabilityReport.unreachable``; later coverage and the
``scripts/check_achievable.py --split`` CLI. Pass is still end state == Oracle.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from nutrienv.bench import check_achievable
from nutrienv.bench.split import load_exam, load_split
from nutrienv.bench.realize import Oracle, Task, compose_oracles
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.daily_windows import derive_daily_windows
from nutrienv.world.types import LedgerRow, Profile, ledger_totals, normalize_tags


def _log_task(*, task_id: str = "log-001", food_id: str = "oats") -> Task:
    s0 = demo_state()
    tail = [LedgerRow(food_id, 60.0, "today-breakfast")]
    return Task(
        task_id,
        "log",
        "I had oats for breakfast.",
        s0,
        Oracle(
            profile=s0.profile,
            ledger_tail=tail,
            ledger=(*s0.ledger, *tail),
        ),
    )


def test_reachable_log_oracle_is_not_listed() -> None:
    report = check_achievable([_log_task()])
    assert report.unreachable == ()


def test_unminted_log_food_is_listed_not_raised() -> None:
    report = check_achievable([_log_task(task_id="log-bad", food_id="not_a_food")])
    assert report.unreachable == ("log-bad",)


def test_exact_last_plan_evaluate_is_reachable() -> None:
    s0 = demo_state()
    plan = [{"food_id": "chicken_breast", "grams": 150.0}]
    task = Task(
        "eval-001",
        "evaluate",
        "Evaluate 150 g chicken.",
        s0,
        Oracle(profile=s0.profile, last_plan=plan, ledger=tuple(s0.ledger)),
    )
    assert check_achievable([task]).unreachable == ()


def test_any_fitting_plan_recommend_is_reachable() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (200.0, 500.0), "protein_g": (20.0, 50.0)},
    )
    task = Task(
        "rec-001",
        "recommend",
        "What's for dinner?",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_allow_empty_plan_is_reachable_when_no_fitting_plan_exists() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (1.0, 2.0), "protein_g": (1000.0, 2000.0)},
    )
    task = Task(
        "conf-001",
        "constrain",
        "Those numbers cannot work together.",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            allow_empty_plan=True,
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_unsatisfiable_recommend_is_unreachable() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (1.0, 2.0), "protein_g": (1000.0, 2000.0)},
    )
    task = Task(
        "rec-impossible",
        "recommend",
        "What's for dinner?",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
        ),
    )
    assert check_achievable([task]).unreachable == ("rec-impossible",)


def test_fitting_plan_uses_oracle_plan_windows() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (1.0, 2.0), "protein_g": (1000.0, 2000.0)},
    )
    task = Task(
        "rec-leftover",
        "recommend",
        "What's for dinner?",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
            plan_windows={"kcal": (200.0, 500.0), "protein_g": (20.0, 50.0)},
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_exact_profile_update_is_reachable() -> None:
    s0 = demo_state()
    oracle_profile = replace(
        s0.profile,
        allergies=normalize_tags(["peanut", "milk"]),
        windows={"kcal": (1600.0, 2000.0), "protein_g": (90.0, 140.0)},
    )
    task = Task(
        "upd-001",
        "update",
        "Add a milk allergy and drop calories by 200.",
        s0,
        Oracle(profile=oracle_profile, ledger=tuple(s0.ledger)),
    )
    assert check_achievable([task]).unreachable == ()


def _ada_state():
    s0 = demo_state()
    windows = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    s0.profile = Profile(
        user_id="roster-ada",
        allergies=("peanut",),
        windows=windows,
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    return s0


def test_update_band_cut_is_reachable() -> None:
    s0 = _ada_state()
    task = Task(
        "upd-cut",
        "update",
        "I'm cutting now.",
        s0,
        Oracle(
            profile=s0.profile,
            ledger=tuple(s0.ledger),
            update_band="cut",
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_update_band_fatigue_is_reachable() -> None:
    s0 = _ada_state()
    cut_windows = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="cut",
    )
    s0.profile = replace(s0.profile, phase="cut", windows=cut_windows)
    task = Task(
        "upd-fatigue",
        "update",
        "This deficit is leaving me exhausted.",
        s0,
        Oracle(
            profile=s0.profile,
            ledger=tuple(s0.ledger),
            update_band="fatigue",
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_update_band_muscle_is_reachable() -> None:
    s0 = _ada_state()
    task = Task(
        "upd-muscle",
        "update",
        "I want to build muscle.",
        s0,
        Oracle(
            profile=s0.profile,
            ledger=tuple(s0.ledger),
            update_band="muscle",
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_body_fact_weight_update_is_reachable() -> None:
    s0 = _ada_state()
    s0.profile = replace(s0.profile, phase="cut")
    oracle_profile = replace(
        s0.profile,
        weight_kg=80.0,
        windows=derive_daily_windows(
            sex="female",
            age_y=34,
            height_cm=165.0,
            weight_kg=80.0,
            activity="light",
            phase="cut",
        ),
    )
    task = Task(
        "upd-weight",
        "update",
        "I now weigh 80 kilograms.",
        s0,
        Oracle(profile=oracle_profile, ledger=tuple(s0.ledger)),
    )
    assert check_achievable([task]).unreachable == ()


def test_reject_evaluate_is_reachable() -> None:
    s0 = demo_state()
    named = [{"food_id": "peanut_butter", "grams": 20.0}]
    task = Task(
        "eval-unfit",
        "evaluate",
        "Evaluate peanut butter as dinner.",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            last_verdict="reject",
            last_reasons=("allergy",),
            evaluated_plan=named,
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_composite_log_then_recommend_is_reachable() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (200.0, 400.0), "protein_g": (20.0, 80.0)},
    )
    lunch = LedgerRow("oats", 60.0, "today-lunch")
    eaten = ledger_totals([*s0.ledger, lunch], s0.catalog)
    remain = {
        key: (round(max(0.0, lo - eaten.get(key, 0.0)), 2), round(max(0.0, hi - eaten.get(key, 0.0)), 2))
        for key, (lo, hi) in s0.profile.windows.items()
    }
    log_oracle = Oracle(
        profile=s0.profile,
        ledger_tail=[lunch],
        ledger=(*s0.ledger, lunch),
    )
    rec_oracle = Oracle(
        profile=s0.profile,
        last_plan=[],
        ledger_tail=[lunch],
        ledger=(*s0.ledger, lunch),
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=remain,
    )
    task = Task(
        "comp-001",
        "log",
        "Log oats for lunch, then recommend dinner.",
        s0,
        compose_oracles(log_oracle, rec_oracle),
    )
    assert check_achievable([task]).unreachable == ()


def test_coverage_counts_families_and_keeps_zero_features_visible() -> None:
    report = check_achievable([_log_task()])
    assert report.by_family == {"log": 1}
    assert report.by_feature["ledger_tail"] == 1
    assert report.by_feature["update_band"] == 0
    assert report.by_feature["body_facts"] == 0


def test_coverage_counts_update_band_and_body_facts() -> None:
    cut = Task(
        "upd-cut",
        "update",
        "I'm cutting now.",
        _ada_state(),
        Oracle(
            profile=_ada_state().profile,
            ledger=(),
            update_band="cut",
        ),
    )
    report = check_achievable([cut, _log_task()])
    assert report.by_family == {"update": 1, "log": 1}
    assert report.by_feature["update_band"] == 1
    assert report.by_feature["body_facts"] == 1
    assert report.by_feature["ledger_tail"] == 1
    assert report.unreachable == ()


def _cli():
    root = Path(__file__).resolve().parents[1]
    scripts = str(root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import check_achievable as cli

    return cli


def _draft_payload(item: dict) -> dict:
    return {
        "version": "pipeline-draft",
        "catalog": "data/fdc/archive/catalog.sqlite",
        "items": [item],
    }


def test_cli_checks_a_frozen_split_without_a_test_file(tmp_path: Path, capsys) -> None:
    path = tmp_path / "pipeline-draft.json"
    path.write_text(
        json.dumps(
            _draft_payload(
                {
                    "id": "cli-log-001",
                    "family": "log",
                    "query": "I had oats for breakfast.",
                    "s0": {
                        "profile": {
                            "allergies": ["peanut"],
                            "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        },
                        "ledger": [],
                    },
                    "oracle": {
                        "profile": "s0",
                        "ledger_tail": [
                            {
                                "food_id": "oats",
                                "grams": 60.0,
                                "eaten_at": "today-breakfast",
                            }
                        ],
                        "ledger": "s0_plus_tail",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    code = _cli().main(["--split", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "unreachable: 0" in out
    assert "update_band: 0" in out
    assert "family log: 1" in out


def test_cli_exits_nonzero_when_an_item_is_unreachable(tmp_path: Path, capsys) -> None:
    path = tmp_path / "pipeline-draft.json"
    path.write_text(
        json.dumps(
            _draft_payload(
                {
                    "id": "cli-bad",
                    "family": "log",
                    "query": "I ate a made-up food.",
                    "s0": {
                        "profile": {
                            "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        },
                        "ledger": [],
                    },
                    "oracle": {
                        "profile": "s0",
                        "ledger_tail": [
                            {
                                "food_id": "not_a_food",
                                "grams": 60.0,
                                "eaten_at": "today-breakfast",
                            }
                        ],
                        "ledger": "s0_plus_tail",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    code = _cli().main(["--split", str(path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "cli-bad" in out


V05 = Path("data/splits/archive/v0.5-gold.json")


def test_archived_v05_load_split_reports_240_reachable() -> None:
    """Fixture check, not a published-exam zero-drift gate."""
    tasks = load_split(V05)
    assert len(tasks) == 240
    report = check_achievable(tasks)
    assert report.unreachable == ()
    assert sum(report.by_family.values()) == 240
    assert report.by_feature["update_band"] == 0
    assert report.by_feature["body_facts"] == 0


def test_load_exam_stays_fail_closed_on_archived_v05() -> None:
    with pytest.raises(ValueError, match="version"):
        load_exam(V05)
