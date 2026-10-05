"""Agent-authored questions and interpretations with independent semantic review.

Code checks structured evidence and computes nutrition. It never parses the query
or asks a limited grammar to decide food identity, cooking state or spoken units.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from nutrienv.bench.achievable import check_achievable
from nutrienv.env import NutriEnv
from nutrienv.bench.pipeline.types import SUPPORTED_FAMILIES, Rejected, catalog_digest
from nutrienv.bench.realize import Task, bind_evaluate_reasons, scored_oracles
from nutrienv.bench.split import _item
from nutrienv.bench.scorer import SCORER_VERSION, Scorer
from nutrienv.harness.prompt_freeze import prompt_fingerprint
from nutrienv.world.daily_windows import ACTIVITY_PAL, derive_profile_windows, plan_windows_for_meal
from nutrienv.world.plan_limits import plan_limits_view, plan_mass_limit
from nutrienv.world.portion_evidence import portion_grams
from nutrienv.world.profile_targets import validate_profile_targets
from nutrienv.world.types import PHASES, food_view, ledger_totals

AUTHOR_CONTRACT = """Write a natural question and its complete structured interpretation together.
Use observed catalog food IDs and portions. Clarify preparation, food identity, sizes and
meal occasion in conversational language, not catalog labels or hidden gold grams.
Return {author_id, item}. item uses the frozen task schema, but every food row uses
portion:{key,count} or portion:{grams} instead of grams. A measured grams claim must be
supported by the question; unnamed units use QNS. No guessed replacement for a missing key.
S0 must include complete body facts and plan_scope (meal/snack/day); code derives windows.
For each judged plan child declare plan_occasion and budget_basis (s0 or ledger), not
plan_windows. Expected profile window patches are allowed only for explicitly requested
numeric changes in the question; the reviewer must verify those numbers. Explicit
high-protein requests set plan_high_protein on recommend children.
Declare complete ledger_variants only for interpretations the question genuinely permits.
For any judged plan, provide witnesses:[{actions:[...]}], one successful legal action trace
for each complete ledger interpretation. Food writes/items use portion evidence rather
than grams. Witness meals prove feasibility; they do not constrain a free recommendation.
"""

REVIEW_CONTRACT = """Independently check the question against every declared interpretation and
catalog fact. Check food identity (including chicken cuts), raw/cooked/frozen state, sizes,
units, meal occasion, inventory, allergies, updates, hypothetical vs eaten food and every
extra scored requirement. Verify each portion key's grams match the spoken unit, not just that the
key exists. No hidden gold distinction or unscored promise may pass review.
Verify numeric window changes are explicit user requests, not caps altered to fit a plan.
Do not rewrite the author's evidence or silently repair a draft. Return
{reviewer_id, draft_sha256, verdict:approve|revise|reject, findings:[strings]}.
Approve only when every interpretation is justified and the wording is natural.
"""


@dataclass(frozen=True)
class GenerateOneResult:
    accepted: Task | None
    rejected: Rejected | None
    review: dict
    draft_sha256: str


def _rows(rows: object, catalog: Mapping) -> list[dict]:
    if not isinstance(rows, list):
        raise TypeError("authored food rows must be a list")
    result = []
    for row in rows:
        if not isinstance(row, dict) or "grams" in row:
            raise ValueError("authored rows require portion evidence, not precomputed grams")
        food_id = row["food_id"]
        if not isinstance(food_id, str):
            raise TypeError("authored food_id must be a string")
        grams = portion_grams(food_id, row["portion"], catalog)
        item = {key: value for key, value in row.items() if key != "portion"}
        item["grams"] = grams
        result.append(item)
    return result


def _oracle_rows(raw: dict, catalog: Mapping) -> None:
    if "sub_oracles" in raw:
        for child in raw["sub_oracles"]:
            _oracle_rows(child, catalog)
        return
    for key in ("ledger_tail", "ledger", "last_plan", "evaluated_plan"):
        if key in raw and isinstance(raw[key], list):
            raw[key] = _rows(raw[key], catalog)
    if "ledger_variants" in raw:
        raw["ledger_variants"] = [_rows(rows, catalog) for rows in raw["ledger_variants"]]


def _materialize(packet: Mapping, catalog: Mapping) -> tuple[Task, dict]:
    author_id = packet["author_id"]
    if not isinstance(author_id, str) or not author_id.strip():
        raise ValueError("author_id is required")
    raw = copy.deepcopy(packet["item"])
    if raw["family"] not in SUPPORTED_FAMILIES:
        raise ValueError(f"unsupported agent-authored family: {raw['family']!r}")
    s0 = raw["s0"]
    facts = s0["profile"]
    if not isinstance(facts["activity"], str) or facts["activity"] not in ACTIVITY_PAL:
        raise ValueError("authored activity must be a declared activity level")
    if not isinstance(facts["phase"], str) or facts["phase"] not in PHASES:
        raise ValueError("authored phase must be maintain, cut or muscle")
    if facts["sex"] not in {"male", "female"}:
        raise ValueError("authored sex must be male or female")
    age = facts["age_y"]
    if isinstance(age, bool) or not isinstance(age, int) or age <= 0:
        raise ValueError("authored age_y must be a positive integer")
    for key in ("height_cm", "weight_kg"):
        value = facts[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"authored {key} must be a positive finite number")
    plan_mass_limit(s0["plan_scope"])
    if "windows" in s0["profile"]:
        raise ValueError("agent supplies body facts, not S0 nutrient windows")
    if "ledger" in s0:
        s0["ledger"] = _rows(s0["ledger"], catalog)
    _oracle_rows(raw["oracle"], catalog)
    children = raw["oracle"].get("sub_oracles", [raw["oracle"]])
    budgets = []
    for child in children:
        if "plan_windows" in child:
            raise ValueError("agent declares occasion and budget basis, not plan_windows")
        occasion = child.pop("plan_occasion", None)
        basis = child.pop("budget_basis", None)
        if "profile" not in child:
            raise ValueError("each scored child requires its expected profile")
        judges_plan = (child.get("last_plan") is not None or child.get("last_verdict") is not None
                       or child.get("plan_must_fit_windows") or child.get("plan_must_be_safe"))
        if judges_plan:
            if occasion is None or basis not in {"s0", "ledger"}:
                raise ValueError("judged plans require plan_occasion and budget_basis")
            expected_scope = "day" if occasion == "day" else ("snack" if occasion == "snack" else "meal")
            if s0["plan_scope"] != expected_scope:
                raise ValueError("plan_scope does not match the declared meal occasion")
        elif occasion is not None or basis is not None:
            raise ValueError("budget hints require a judged plan")
        budgets.append((occasion, basis))
    preliminary = _item(raw, catalog)
    daily = derive_profile_windows(preliminary.s0.profile)
    if daily is None:
        raise ValueError("agent draft requires complete sex/age/height/weight/activity facts")
    validate_profile_targets(replace(preliminary.s0.profile, windows=daily))
    raw["s0"]["profile"]["windows"] = {key: list(bounds) for key, bounds in daily.items()}
    loaded = _item(raw, catalog)
    parsed_children = loaded.oracle.sub_oracles or (loaded.oracle,)
    for child, parsed, (occasion, basis) in zip(children, parsed_children, budgets, strict=True):
        if occasion is None:
            continue
        profile = parsed.profile or loaded.s0.profile
        validate_profile_targets(profile)
        ledger = loaded.s0.ledger if basis == "s0" else parsed.ledger
        if ledger is None:
            raise ValueError("ledger budget basis requires a complete oracle ledger")
        eaten = ledger_totals(list(ledger), catalog)
        if occasion == "day":
            windows = {key: (round(max(0, lo - eaten.get(key, 0)), 2),
                             round(max(0, hi - eaten.get(key, 0)), 2))
                       for key, (lo, hi) in profile.windows.items()}
        else:
            windows = plan_windows_for_meal(profile.windows, eaten, occasion)
        if windows is None:
            raise ValueError("authored interpretation has no feasible meal energy budget")
        child["plan_windows"] = {key: list(bounds) for key, bounds in windows.items()}
        if parsed.last_verdict is not None:
            named = parsed.evaluated_plan or parsed.last_plan
            if not named:
                raise ValueError("evaluation requires an explicit named candidate")
            reasons = bind_evaluate_reasons(named, windows, catalog, profile.allergies,
                                            plan_scope=loaded.s0.plan_scope)
            if (parsed.last_verdict == "accept") != (not reasons):
                raise ValueError("authored evaluation verdict contradicts the computed constraints")
            if reasons:
                child["last_reasons"] = list(reasons)
    task = _item(raw, catalog)
    _validate_witnesses(task, packet, catalog)
    return task, raw


def _validate_witnesses(task: Task, packet: Mapping, catalog: Mapping) -> None:
    children = tuple(scored_oracles(task.oracle))
    if not any(child.last_plan is not None or child.last_verdict is not None for child in children):
        if check_achievable([task]).unreachable:
            raise ValueError("authored log/update goal is unreachable")
        return
    witnesses = packet["witnesses"]
    if not isinstance(witnesses, list) or not witnesses:
        raise ValueError("judged plans require non-empty legal witnesses")
    required = {(index, ledger) for index, child in enumerate(children)
                for ledger in (() if child.ledger is None else (child.ledger, *child.ledger_variants))}
    covered = set()
    scorer = Scorer()
    for witness in witnesses:
        env = NutriEnv()
        env.reset(task.s0)
        actions = witness["actions"]
        if not isinstance(actions, list) or not actions:
            raise ValueError("witness actions must be a non-empty list")
        wrote = False
        handed_in = False
        for raw in actions:
            action = copy.deepcopy(raw)
            if handed_in:
                raise ValueError("witness must stop after hand-in")
            op = action["op"]
            if op in {"log_meal", "amend_meal"}:
                if "grams" in action:
                    raise ValueError("witness food writes require portion evidence")
                food_id = action.get("food_id")
                if food_id is None and op == "amend_meal":
                    food_id = env.state().ledger[action["index"]].food_id
                if not isinstance(food_id, str):
                    raise ValueError("witness food_id must be a string")
                action["grams"] = portion_grams(food_id, action.pop("portion"), catalog)
            if op == "submit_plan":
                action["items"] = _rows(action["items"], catalog)
            result = env.step(action)
            if not result["ok"]:
                raise ValueError(f"illegal witness action: {result['error']}")
            wrote |= op in {"log_meal", "amend_meal", "update_profile", "submit_plan", "update_plan"}
            handed_in = op in {"submit_plan", "finish"}
        if not wrote or not scorer.score(env.state(), task.oracle)["passed"]:
            raise ValueError("witness does not satisfy the complete task")
        for index, child in enumerate(children):
            ledger = scorer._matched_ledger(env.state(), child)
            if ledger is not None:
                covered.add((index, ledger))
    if required - covered:
        raise ValueError("witnesses do not cover every complete ledger interpretation")


def review_packet(packet: Mapping, catalog: Mapping) -> tuple[Task, dict]:
    """Prepare exact grounded evidence for a separate reviewer; no semantic auto-approval."""
    task, raw = _materialize(packet, catalog)
    payload = {"author_packet": packet, "item": raw,
               "catalog_sha256": catalog_digest(catalog), "scorer_version": SCORER_VERSION,
               "prompt_fingerprint": prompt_fingerprint(),
               "plan_limits": plan_limits_view(task.s0.plan_scope),
               "review_contract": REVIEW_CONTRACT}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    digest = hashlib.sha256(blob).hexdigest()
    foods = set()

    def collect(value):
        if isinstance(value, dict):
            if "food_id" in value:
                foods.add(value["food_id"])
            if "allowed_food_ids" in value:
                foods.update(value["allowed_food_ids"])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(raw)
    return task, {**copy.deepcopy(payload), "draft_sha256": digest,
                  "catalog_foods": {food: food_view(catalog, food) for food in sorted(foods)}}


def generate_one(*, catalog: Mapping, author: Callable[[], Mapping],
                 reviewer: Callable[[dict], Mapping]) -> GenerateOneResult:
    """Author -> grounded candidate -> independent review -> admitted task.

    Provider exceptions propagate. Missing evidence, mismatched review identity/hash,
    schema errors and infeasible budgets raise; a deliberate revise/reject is returned.
    """
    packet = author()
    task, request = review_packet(packet, catalog)
    response = dict(reviewer(copy.deepcopy(request)))
    reviewer_id = response["reviewer_id"]
    if not isinstance(reviewer_id, str) or not reviewer_id.strip() or reviewer_id == packet["author_id"]:
        raise ValueError("reviewer_id must identify a separate reviewer")
    if response["draft_sha256"] != request["draft_sha256"]:
        raise ValueError("review does not match this exact draft and catalog")
    findings = response["findings"]
    if not isinstance(findings, list) or not all(isinstance(f, str) and f.strip() for f in findings):
        raise ValueError("review findings must be a list of non-empty strings")
    verdict = response["verdict"]
    if verdict not in {"approve", "revise", "reject"}:
        raise ValueError("unknown review verdict")
    if verdict == "approve" and findings:
        raise ValueError("approval cannot carry unresolved findings")
    if verdict != "approve":
        return GenerateOneResult(None, Rejected(task.query, "semantic_review", task.family),
                                 response, request["draft_sha256"])
    return GenerateOneResult(task, None, response, request["draft_sha256"])
