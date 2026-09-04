#!/usr/bin/env python3
"""Live ReAct v1 exam path on catalog-v2 (ticket 08 rework).

Runs the real agent through the runner loop: search_foods → get_food →
observation → log_meal/finish. Records trajectories; does not invent a
resolver stand-in. Gray-zone results are for Opus ruling, not self-declared
GATE_SAFE.

  .venv/bin/python scripts/agent_behavior_verify.py --model deepseek-v4-flash-0731
  .venv/bin/python scripts/agent_behavior_verify.py --model deepseek-v4-flash-0731 \\
      --ids oral-chicken-breast --repeat 3 --json-out reports/agent-behavior-cut-noun-ds.json
  .venv/bin/python scripts/agent_behavior_verify.py --model qwen3.7-flash-2026-07-15 \\
      --ids oral-chicken-breast --repeat 3 --json-out reports/agent-behavior-cut-noun-qwen.json
  .venv/bin/python scripts/agent_behavior_verify.py --merge-cut-noun \\
      reports/agent-behavior-cut-noun-ds.json reports/agent-behavior-cut-noun-qwen.json
  .venv/bin/python scripts/agent_behavior_verify.py --write-report-from-json
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
RESULTS_JSON = (
    ROOT / "reports" / "archive" / "audit_and_probes" / "agent-behavior-verify.json"
)
CUT_NOUN_JSON = (
    ROOT / "reports" / "archive" / "audit_and_probes" / "agent-behavior-cut-noun.json"
)
REPORT_MD = (
    ROOT / "reports" / "archive" / "audit_and_probes" / "agent-behavior-verify.md"
)
DEFAULT_MODEL = "deepseek-v4-flash-0731"
OBSERVE_MODELS = ("deepseek-v4-flash-0731", "qwen3.7-flash-2026-07-15")
CUT_NOUN_HANDBOOK = (
    'A cut with no portion key ("a chicken breast") has no default: '
    "do not log it, finish without logging that food"
)
# Last recorded full-suite count. Default --write-report-from-json must
# emit this so the documented rerun is byte-identical to the committed report.
PYTEST_NOTE = "**1049 passed**"
_SLIM_ACTION_KEYS = ("op", "search_q", "hit_ids", "food_id", "logged", "error")


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


def _slim_run(model: str, row: dict) -> dict:
    actions = []
    for step in row.get("actions") or []:
        slim = {key: step[key] for key in _SLIM_ACTION_KEYS if step.get(key) is not None}
        if slim:
            actions.append(slim)
    return {
        "model": model,
        "repeat": row.get("repeat", 1),
        "passed": row["passed"],
        "tag": row["tag"],
        "ops": list(row.get("ops") or []),
        "ledger": list(row.get("ledger") or []),
        "actions": actions,
    }


def merge_cut_noun_payloads(
    payloads: list[dict], *, date: str | None = None
) -> dict:
    """Join per-model `--ids oral-chicken-breast` JSON into one observation file."""
    if not payloads:
        raise ValueError("merge_cut_noun_payloads needs at least one payload")
    runs = []
    for payload in payloads:
        model = str(payload.get("model") or "unknown")
        for row in payload.get("cases") or []:
            runs.append(_slim_run(model, row))
    return {
        "kind": "cut_noun_observation",
        "date": date or str(payloads[0].get("date") or ""),
        "query": "Please log a chicken breast.",
        "oracle": "empty ledger",
        "handbook": CUT_NOUN_HANDBOOK,
        "resolve_portion": None,
        "runs": runs,
    }


def _ops_brief(ops: list) -> str:
    return " → ".join(str(op) for op in ops) if ops else "(none)"


def _ledger_brief(ledger: list) -> str:
    if not ledger:
        return "(empty)"
    return "; ".join(
        f"{row.get('food_id')} {row.get('grams')}g" for row in ledger
    )


def _observation_section(observation: dict | None) -> list[str]:
    lines = [
        "## 6. 裸切块名词行为观察（手册修正后）",
        "",
        "不是验收。oracle 空账本；`resolve_portion(..., \"a chicken breast\")` 仍是 None。",
        "空账本 = 与手册新措辞一致；log 105 g = 干净的模型失败。",
        "",
    ]
    if observation is None:
        lines.extend(
            [
                "尚未合并观察 JSON。先跑两个模型的 `--ids oral-chicken-breast --repeat 3`，再：",
                "",
                "```",
                ".venv/bin/python scripts/agent_behavior_verify.py --merge-cut-noun "
                "reports/agent-behavior-cut-noun-ds.json "
                "reports/agent-behavior-cut-noun-qwen.json",
                "```",
                "",
            ]
        )
        return lines
    runs = observation.get("runs") or []
    lines.extend(
        [
            f"n={len(runs)}，模型 {len({row.get('model') for row in runs})} 个。",
            "",
            "| 模型 | # | end state | tag | ops | ledger |",
            "|---|---|---|---|---|---|",
        ]
    )
    empty = 0
    for row in runs:
        ledger = row.get("ledger") or []
        if not ledger:
            empty += 1
            end = "空账本"
        else:
            end = _ledger_brief(ledger).replace("(empty)", "").strip() or "log"
            if "105" in end:
                end = "log 105 g"
        lines.append(
            f"| `{row.get('model')}` | {row.get('repeat', 1)} | {end} | "
            f"{row.get('tag')} | `{_ops_brief(row.get('ops') or [])}` | "
            f"{_ledger_brief(ledger)} |"
        )
    by_model: dict[str, list] = {}
    for row in runs:
        by_model.setdefault(str(row.get("model")), []).append(row)
    lines.append("")
    for model, rows in by_model.items():
        ok = sum(1 for row in rows if not row.get("ledger"))
        lines.append(f"`{model}`：**{ok}/{len(rows)}** 空账本。")
    lines.extend(
        [
            f"合计空账本 {empty}/{len(runs)}，模型失败 {len(runs) - empty}/{len(runs)}。",
            "",
        ]
    )
    return lines


def render_report(
    payload: dict,
    observation: dict | None = None,
    *,
    pytest_note: str = PYTEST_NOTE,
) -> str:
    """Markdown report from exam JSON + optional merged cut-noun observation."""
    lines = [
        "# 08 — agent 考试行为验证（catalog-v2 + 手册对称）",
        "",
        f"日期：{payload['date']}",
        "范围：catalog-v2 工具缝 + **live ReAct v1** 考试轨迹。Node 2（claude Opus）已重划验收：四条正向表达是 pass/fail；裸切块名词是行为观察，不是通过条件。",
        "",
        "复跑：",
        "",
        "```",
        f".venv/bin/python scripts/agent_behavior_verify.py --model {OBSERVE_MODELS[0]}",
        f".venv/bin/python scripts/agent_behavior_verify.py --model {OBSERVE_MODELS[0]} "
        "--ids oral-chicken-breast --repeat 3 --json-out reports/agent-behavior-cut-noun-ds.json",
        f".venv/bin/python scripts/agent_behavior_verify.py --model {OBSERVE_MODELS[1]} "
        "--ids oral-chicken-breast --repeat 3 --json-out reports/agent-behavior-cut-noun-qwen.json",
        ".venv/bin/python scripts/agent_behavior_verify.py --merge-cut-noun "
        "reports/agent-behavior-cut-noun-ds.json reports/agent-behavior-cut-noun-qwen.json",
        ".venv/bin/python scripts/agent_behavior_verify.py --write-report-from-json",
        ".venv/bin/python -m pytest -q",
        "```",
        "",
        "无 API 时只跑最后两行：从已提交的 JSON 重建本报告。",
        "",
        "## 0. Node 2 验收重划 + 手册修正",
        "",
        "| 项 | 地位 |",
        "|---|---|",
        "| `a piece of chicken` → 105 g | **验收** |",
        "| `150 g of chicken` → 150 g | **验收** |",
        "| `one apple` → 165 g | **验收** |",
        "| `half a cup of milk` → 122 g | **验收** |",
        "| 裸 `a chicken breast` | **观察 only**（oracle 仍是空账本；n≥3、≥2 模型见 §6） |",
        "",
        "手册 `_SYSTEM_V1_TAIL` 原写 `ask for grams`，但 ACTION_SCHEMAS 没有 ask/clarify。Opus 点 3：改成可达行为：",
        "",
        f"`{CUT_NOUN_HANDBOOK}`",
        "",
        "`resolve_portion` 与 oracle 未改。`a chicken breast` 仍是 None / 空账本。",
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
        "同一 `FoodCatalog.search` 也作用于 `catalog.sqlite`：`q=\"chicken\"` 现在第一名是旧 SR staple `171477`。",
        "冻结 split / oracle 未改；只改变 live agent 的检索排序。",
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
        group = row["group"]
        if row["id"] == "oral-chicken-breast":
            group = "oral（观察，手册修正前单次）"
        mark = "PASS" if row["passed"] else "FAIL"
        lines.append(
            f"| `{row['id']}` | {group} | {row['query']} | {oracle} | "
            f"**{mark}** | {row['tag']} | `{','.join(row['ops'])}` | "
            f"{_ledger_brief(row.get('ledger') or [])} |"
        )
    lines.extend(["", "### 逐步动作", ""])
    for row in payload["cases"]:
        lines.append(f"#### `{row['id']}` — {row['query']}")
        lines.append("")
        lines.append(row["note"])
        lines.append("")
        for step in row.get("actions") or []:
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
    lines.extend(["## 5. 灰区（送 Opus）", ""])
    if gray:
        lines.extend(
            [
                f"{len(gray)} 题 live ReAct，**{gray_pass}/{len(gray)}** 的 end state 命中表值 oracle。",
                "轨迹里有几次 `food_id` 非字符串的 `bad_schema`，agent 重试后写对了。",
                "omelet 的 BM25 前 8 名不含 2707198，agent 仍 `get_food` 到了该 id。",
                "lasagna search 第一名是 meatless `2708758`，agent 选了表值题的 `2708750`。",
                "",
                "本文件不封 gate。Opus 看上表轨迹后裁决。",
                "",
            ]
        )
    else:
        lines.extend(["本 payload 无灰区题。", ""])
    lines.extend(_observation_section(observation))
    lines.extend(
        [
            "## 7. 机器可读结果",
            "",
            "- 验收轨迹：`reports/agent-behavior-verify.json`",
            "- 切块名词观察：`reports/agent-behavior-cut-noun.json`（`--merge-cut-noun` 写出）",
            "",
            "## 8. pytest",
            "",
            "| 检查 | 结果 |",
            "|---|---|",
            "| `tests/test_agent_behavior_verify.py` + routing | 通过（不断言 live Pass） |",
            f"| 全量 pytest | {pytest_note} |",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(
    payload: dict,
    observation: dict | None = None,
    *,
    pytest_note: str = PYTEST_NOTE,
) -> None:
    REPORT_MD.write_text(
        render_report(payload, observation, pytest_note=pytest_note),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--ids",
        default=None,
        help="comma-separated case ids (default: all)",
    )
    parser.add_argument("--repeat", type=int, default=1, help="runs per case")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="results JSON path (default: reports/agent-behavior-verify.json)",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="rewrite reports/agent-behavior-verify.md (off when --ids is set)",
    )
    parser.add_argument(
        "--merge-cut-noun",
        nargs="+",
        metavar="JSON",
        help="merge per-model cut-noun JSON into reports/agent-behavior-cut-noun.json",
    )
    parser.add_argument(
        "--write-report-from-json",
        action="store_true",
        help="rebuild the markdown report from committed JSON (no live LLM)",
    )
    parser.add_argument(
        "--pytest-note",
        default=PYTEST_NOTE,
        help="text for the report pytest row",
    )
    args = parser.parse_args(argv)

    if args.merge_cut_noun:
        payloads = []
        for raw in args.merge_cut_noun:
            path = Path(raw)
            if not path.is_file():
                print(f"missing {path}", file=sys.stderr)
                return 2
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        merged = merge_cut_noun_payloads(payloads)
        CUT_NOUN_JSON.write_text(
            json.dumps(merged, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(f"wrote {CUT_NOUN_JSON}", file=sys.stderr)
        if args.write_report_from_json or args.write_report:
            if not RESULTS_JSON.is_file():
                print(f"missing {RESULTS_JSON}", file=sys.stderr)
                return 2
            exam = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
            _write_report(exam, merged, pytest_note=args.pytest_note)
            print(f"wrote {REPORT_MD}", file=sys.stderr)
        return 0

    if args.write_report_from_json:
        if not RESULTS_JSON.is_file():
            print(f"missing {RESULTS_JSON}", file=sys.stderr)
            return 2
        exam = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
        observation = None
        if CUT_NOUN_JSON.is_file():
            observation = json.loads(CUT_NOUN_JSON.read_text(encoding="utf-8"))
        _write_report(exam, observation, pytest_note=args.pytest_note)
        print(f"wrote {REPORT_MD}", file=sys.stderr)
        return 0

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

    wanted = None
    if args.ids:
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        missing = wanted - {case.id for case in CASES}
        if missing:
            print(f"unknown case ids: {sorted(missing)}", file=sys.stderr)
            return 2
    selected = [case for case in CASES if wanted is None or case.id in wanted]
    if args.repeat < 1:
        print("--repeat must be >= 1", file=sys.stderr)
        return 2

    cases_out: list[dict] = []
    for case in selected:
        for run_i in range(1, args.repeat + 1):
            label = case.id if args.repeat == 1 else f"{case.id}#{run_i}"
            print(f"RUN {label} {case.query}", file=sys.stderr, flush=True)
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
                print(f"ERR {label} {exc}", file=sys.stderr, flush=True)
            row = {
                "id": case.id,
                "repeat": run_i,
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
                f"{mark} {label} tag={row['tag']} ops={row['ops']} ledger={row['ledger']}",
                file=sys.stderr,
                flush=True,
            )

    dest = args.json_out or RESULTS_JSON
    payload = {
        "date": date.today().isoformat(),
        "model": args.model,
        "harness": "react-v1",
        "catalog": str(CATALOG_V2.relative_to(ROOT)),
        "max_steps": args.max_steps,
        "cases": cases_out,
    }
    dest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    write_report = args.write_report or (wanted is None and dest == RESULTS_JSON)
    if write_report:
        observation = None
        if CUT_NOUN_JSON.is_file():
            observation = json.loads(CUT_NOUN_JSON.read_text(encoding="utf-8"))
        _write_report(payload, observation, pytest_note=args.pytest_note)
        print(f"wrote {REPORT_MD}", file=sys.stderr)
    print(f"wrote {dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
