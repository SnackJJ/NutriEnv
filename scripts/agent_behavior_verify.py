#!/usr/bin/env python3
"""Live ReAct v1 exam path on catalog-v2 (ticket 08 rework).

Runs the real agent through the runner loop: search_foods → get_food →
observation → log_meal/finish. Records trajectories; does not invent a
resolver stand-in. Gray-zone results are for Opus ruling, not self-declared
GATE_SAFE.

  .venv/bin/python scripts/agent_behavior_verify.py
  .venv/bin/python scripts/agent_behavior_verify.py --model qwen3.7-flash-2026-07-15
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nutrienv.bench import Oracle, Scorer, Task  # noqa: E402
from nutrienv.bench.realize import GOLD_WINDOWS  # noqa: E402
from nutrienv.env import NutriEnv  # noqa: E402
from nutrienv.harness.react import ReActHarness  # noqa: E402
from nutrienv.harness.runner import (  # noqa: E402
    DEFAULT_MAX_STEPS,
    FINISH_OPS,
    IDLE_READS_AFTER_WRITE,
    READ_OPS,
    WRITE_OPS,
)
from nutrienv.io.dotenv import load_dotenv_keys  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402
from nutrienv.world.types import LedgerRow, Profile, WorldState  # noqa: E402

CATALOG_V2 = ROOT / "data" / "fdc" / "catalog-v2.sqlite"
RESULTS_JSON = ROOT / "reports" / "agent-behavior-verify.json"
REPORT_MD = ROOT / "reports" / "agent-behavior-verify.md"
DEFAULT_MODEL = "deepseek-v4-flash-0731"


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    query: str
    food_id: str | None
    grams: float | None
    note: str


CASES: tuple[Case, ...] = (
    Case(
        "oral-piece-chicken",
        "oral",
        "Please log a piece of chicken.",
        "chicken_breast",
        105.0,
        "first-wins piece; agent must find 2705956 via search, not injected slug",
    ),
    Case(
        "oral-150g-chicken",
        "oral",
        "Please log that I ate 150 g of chicken.",
        "chicken_breast",
        150.0,
        "spoken grams",
    ),
    Case(
        "oral-one-apple",
        "oral",
        "Please log one apple.",
        "apple",
        165.0,
        "bare noun → piece",
    ),
    Case(
        "oral-half-cup-milk",
        "oral",
        "Please log half a cup of milk.",
        "milk_whole",
        122.0,
        "cup=qns=244 / 2",
    ),
    Case(
        "oral-chicken-breast",
        "oral",
        "Please log a chicken breast.",
        None,
        None,
        "ticket 02: cut noun stays None; empty ledger is the oracle",
    ),
    Case(
        "gray-sandwich-piece",
        "gray",
        "Please log a piece of sandwich.",
        "2706880",
        175.0,
        "sandwich 1.5× pair, piece",
    ),
    Case(
        "gray-sandwich-qns",
        "gray",
        "Please log a sandwich.",
        "2706880",
        115.0,
        "sandwich 1.5× pair, qns via dish noun",
    ),
    Case(
        "gray-lasagna-piece",
        "gray",
        "Please log a piece of lasagna.",
        "2708750",
        206.0,
        "lasagna 1.2× pair, piece",
    ),
    Case(
        "gray-lasagna-qns",
        "gray",
        "Please log a serving of lasagna.",
        "2708750",
        250.0,
        "lasagna 1.2× pair, serving/qns",
    ),
    Case(
        "gray-omelet-piece",
        "gray",
        "Please log a piece of omelet.",
        "2707198",
        55.0,
        "omelet 2.0× pair, piece",
    ),
    Case(
        "gray-omelet-qns",
        "gray",
        "Please log an omelet.",
        "2707198",
        110.0,
        "omelet 2.0× pair, dish noun/qns",
    ),
)


def _task(catalog, case: Case) -> Task:
    s0 = WorldState(
        profile=Profile(user_id="verify", windows=dict(GOLD_WINDOWS)),
        ledger=[],
        catalog=catalog,
    )
    if case.grams is None or case.food_id is None:
        oracle = Oracle(ledger=())
    else:
        oracle = Oracle(
            ledger_tail=[
                LedgerRow(catalog.canonical_id(case.food_id), case.grams, "now")
            ]
        )
    return Task(case.id, "log", case.query, s0, oracle, situations=("fuzzy_portion",))


def _summarize_event(event: dict) -> dict:
    action = event.get("action") or {}
    result = event.get("result") or {}
    obs = result.get("observation") if isinstance(result, dict) else None
    row: dict = {"op": action.get("op"), "action": action}
    if not isinstance(obs, dict):
        if isinstance(result, dict) and result.get("error"):
            row["error"] = result["error"]
        return row
    if obs.get("op") == "search_foods":
        hits = obs.get("results") or []
        row["search_q"] = action.get("q")
        row["hit_ids"] = [h.get("food_id") for h in hits[:8]]
        row["n_hits"] = len(hits)
    elif obs.get("op") == "get_food":
        food = obs.get("food") or {}
        row["food_id"] = food.get("food_id")
        row["name"] = food.get("name")
        row["portions"] = food.get("portions")
    elif obs.get("op") == "log_meal":
        logged = obs.get("row") or {}
        row["logged"] = logged
    return row


def run_recorded(task: Task, harness: ReActHarness, max_steps: int) -> dict:
    """Same stop rules as runner._run_episode, but keep the trajectory."""
    env = NutriEnv()
    observation = env.reset(task.s0)
    history: list[dict] = []
    wrote = False
    idle_reads = 0
    for _ in range(max_steps):
        action = harness.act(observation, task.query, history)
        op = action.get("op") if isinstance(action, dict) else None
        if op in FINISH_OPS:
            history.append(
                {
                    "action": action,
                    "result": {
                        "ok": True,
                        "observation": {"op": "finish"},
                        "done": True,
                    },
                }
            )
            break
        result = env.step(action)
        history.append({"action": action, "result": result})
        if result.get("ok") and isinstance(result.get("observation"), dict):
            observation = result["observation"]
        else:
            observation = {"error": result.get("error")}
            idle_reads = 0
            continue
        if op in WRITE_OPS:
            wrote = True
            idle_reads = 0
            if op == "submit_plan":
                break
        elif op in READ_OPS:
            if wrote:
                idle_reads += 1
                if idle_reads >= IDLE_READS_AFTER_WRITE:
                    break
        else:
            idle_reads = 0
    score = Scorer().score(env.state(), task.oracle)
    ledger = [
        {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
        for row in env.state().ledger
    ]
    ops = [
        str(event["action"].get("op"))
        for event in history
        if isinstance(event.get("action"), dict)
    ]
    return {
        "passed": bool(score["passed"]),
        "tag": str(score["tag"]),
        "ops": ops,
        "ledger": ledger,
        "actions": [_summarize_event(event) for event in history],
    }


def _write_report(payload: dict) -> None:
    lines = [
        "# 08 — agent 考试行为验证（catalog-v2 + 手册对称）",
        "",
        f"日期：{payload['date']}",
        "范围：catalog-v2 工具缝 + **live ReAct v1** 考试轨迹。灰区结果送 Opus 终裁，本文件不自称 GATE_SAFE。",
        "",
        "复跑：",
        "",
        "```",
        f".venv/bin/python scripts/agent_behavior_verify.py --model {payload['model']}",
        ".venv/bin/python -m pytest -q tests/test_agent_behavior_verify.py",
        "```",
        "",
        "## 1. 本轮相对 e58e023 改了什么",
        "",
        "| 发现 | 改动 |",
        "|---|---|",
        "| 1 灰区未跑真 agent | 删除 `_HandbookLogHarness` 的 oracle-pass 测试。灰区 6 题走 live ReAct，轨迹如下。 |",
        "| 2 未验证真实 ReAct | `ReActHarness` 用 `lookup_chat_model` 路由 `deepseek-v4-flash-0731` / `qwen3.7-flash-2026-07-15` 到 DashScope；本脚本跑 v1 手册。 |",
        "| 3 search chicken 丢 staple | `_search_fts` 把 **精确 alias**（`aliases` 分词集 == query）插到 BM25 前。`q=\"chicken\"` → 2705956。不是 get_food 注入。 |",
        "",
        "## 2. search 决策",
        "",
        "BM25 `q=\"chicken\"` 原先 top 25 不含 2705956。`_promote_alias_hits` 只重排已返回的行。",
        "这是可修的排序缺口：staple 已有精确 alias `chicken`。",
        "修复后 `search_foods \"chicken\"` 第一名是 2705956，`get_food` 观察 `piece=105`。",
        "精确匹配避免把 egg 的 alias `chicken egg` 提上来。",
        "",
        "## 3. 手册 / 表值（确定性，非 live 断言）",
        "",
        "| 短语 | resolve_portion |",
        "|---|---|",
        "| a piece of chicken | 105 |",
        "| 150 g of chicken | 150 |",
        "| one apple | 165 |",
        "| half a cup of milk | 122（cup=qns=244 / 2） |",
        "| a chicken breast | None |",
        "| sandwich piece / a sandwich | 175 / 115 |",
        "| lasagna piece / a serving | 206 / 250 |",
        "| omelet piece / an omelet | 55 / 110 |",
        "",
        "QNS vs first-wins：chicken 120 vs 105；tuna 85 vs 75；beef 85 vs 65。",
        "",
        "## 4. Live ReAct 轨迹",
        "",
        f"- 模型：`{payload['model']}`",
        f"- harness：`{payload['harness']}`",
        f"- catalog：`{payload['catalog']}`",
        f"- max_steps：{payload['max_steps']}",
        "",
        "| id | group | query | oracle | passed | tag | ops | ledger |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in payload["cases"]:
        oracle = (
            "empty ledger"
            if row["oracle_grams"] is None
            else f"{row['oracle_food']} {row['oracle_grams']}g"
        )
        ledger = (
            "; ".join(f"{x['food_id']} {x['grams']}g" for x in row["ledger"])
            or "(empty)"
        )
        mark = "PASS" if row["passed"] else "FAIL"
        lines.append(
            f"| `{row['id']}` | {row['group']} | {row['query']} | {oracle} | "
            f"**{mark}** | {row['tag']} | `{','.join(row['ops'])}` | {ledger} |"
        )
    lines.extend(["", "### 逐步动作", ""])
    for row in payload["cases"]:
        lines.append(f"#### `{row['id']}` — {row['query']}")
        lines.append("")
        lines.append(row["note"])
        lines.append("")
        for step in row["actions"]:
            op = step.get("op")
            extra = ""
            if step.get("search_q") is not None:
                extra = f" q={step['search_q']!r} hits={step.get('hit_ids')}"
            elif step.get("food_id") is not None:
                extra = f" id={step['food_id']} portions={step.get('portions')}"
            elif step.get("logged") is not None:
                extra = f" {step['logged']}"
            elif step.get("error") is not None:
                extra = f" error={step['error']}"
            lines.append(f"- `{op}`{extra}")
        lines.append("")
    gray = [row for row in payload["cases"] if row["group"] == "gray"]
    gray_pass = sum(1 for row in gray if row["passed"])
    lines.extend(
        [
            "## 5. 灰区（送 Opus）",
            "",
            f"6 题 live ReAct，{gray_pass}/6 的 end state 命中表值 oracle。",
            "本文件不封 gate。Opus 看上表轨迹后裁决。",
            "",
            "## 6. 机器可读结果",
            "",
            "`reports/agent-behavior-verify.json`",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args(argv)

    load_dotenv_keys(ROOT / ".env.local")
    if not CATALOG_V2.is_file():
        print("catalog-v2.sqlite missing", file=sys.stderr)
        return 2
    catalog = load_catalog(CATALOG_V2)
    harness_proto = ReActHarness(
        model=args.model,
        timeout=args.timeout,
        max_steps=args.max_steps,
        version="v1",
    )

    from datetime import date

    cases_out: list[dict] = []
    for case in CASES:
        print(f"RUN {case.id} {case.query}", file=sys.stderr, flush=True)
        harness = harness_proto.clone()
        harness.reset()
        task = _task(catalog, case)
        try:
            result = run_recorded(task, harness, args.max_steps)
            error = None
        except Exception as exc:  # noqa: BLE001 — record live failure, do not invent pass
            result = {
                "passed": False,
                "tag": "error",
                "ops": [],
                "ledger": [],
                "actions": [],
            }
            error = str(exc)
            print(f"ERR {case.id} {exc}", file=sys.stderr, flush=True)
        row = {
            "id": case.id,
            "group": case.group,
            "query": case.query,
            "note": case.note,
            "oracle_food": (
                None
                if case.food_id is None
                else catalog.canonical_id(case.food_id)
            ),
            "oracle_grams": case.grams,
            **result,
        }
        if error:
            row["error"] = error
        cases_out.append(row)
        mark = "PASS" if row["passed"] else "FAIL"
        print(
            f"{mark} {case.id} tag={row['tag']} ops={row['ops']} ledger={row['ledger']}",
            file=sys.stderr,
            flush=True,
        )

    payload = {
        "date": date.today().isoformat(),
        "model": args.model,
        "harness": "react-v1",
        "catalog": str(CATALOG_V2.relative_to(ROOT)),
        "max_steps": args.max_steps,
        "cases": cases_out,
    }
    RESULTS_JSON.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    _write_report(payload)
    print(f"wrote {RESULTS_JSON}", file=sys.stderr)
    print(f"wrote {REPORT_MD}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
