#!/usr/bin/env python3
"""Verify the three v1.1 ARK runs and render separate charts; never overwrite v1.0 assets.

Run from the repository root: uv run --extra plots python scripts/render_v1_1.py
The provenance manifest binds current replay artifacts, not unrecorded run-time hashes.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPORTS = (
    ("DeepSeek-v4.1-flash", "ab_ark_deepseek-v4.1-flash_v1.1-new_fc.json", "#2DD4BF"),
    ("GLM-5.3-flash", "ab_ark_glm-5.3-flash_v1.1-new_fc.json", "#FBBF24"),
    ("Doubao-seed-2.1-lite", "ab_ark_doubao-seed-2.1-lite_v1.1-new_fc.json", "#F472B6"),
)
FAMILIES = {"update": 2, "log": 6, "evaluate": 8, "recommend": 11, "composite": 36}
IDENTITY = {
    "split": "data/splits/nutrienv-v1.1.json",
    "scorer_version": "s10-meal-mass-envelope",
    "prompt_version": "p8-published-meal-mass-limits",
    "prompt_fingerprint": "616dea69c32f9d469aac17b4ceafcadcf377d261934573ba9631c0f0cd75dfed",
    "loop_version": "l2-refused-handin-continues",
    "endpoint": "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions",
    "contract": "native-tools",
    "temperature": 0.0,
    "context_limit": None,
    "parse_error_policy": "silent",
    "reasoning_effort": "default",
    "extra_body": {},
}
BG, GRID, WHITE, MUTED = "#090D16", "#1E293B", "#F8FAFC", "#94A3B8"
FOOTNOTE = "Internal ARK · single run per model · not the official leaderboard · not comparable with v1.0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read required JSON artifact {path}: {exc}") from exc


def load_reports(root: Path = ROOT) -> list[dict]:
    runs = []
    for name, filename, color in REPORTS:
        data = read_json(root / "reports" / filename)
        for key, value in IDENTITY.items():
            if data[key] != value:
                raise ValueError(f"{filename}: incompatible {key}: {data[key]!r}")
        rows = data["tasks"]
        if data["total_tasks"] != 63 or len(rows) != 63 or len({r["task_id"] for r in rows}) != 63:
            raise ValueError(f"{filename}: expected 63 unique tasks")
        if data["void_count"] != 0 or any(r["is_void"] for r in rows):
            raise ValueError(f"{filename}: incomplete run")
        if data["passed_tasks"] != sum(r["passed"] for r in rows):
            raise ValueError(f"{filename}: pass count disagrees with task rows")
        for family, total in FAMILIES.items():
            group = [r for r in rows if r["family"] == family]
            counts = data["family_breakdown"][family]
            if len(group) != total or counts["total"] != total or counts["passed"] != sum(r["passed"] for r in group):
                raise ValueError(f"{filename}: inconsistent {family} counts")
        runs.append({"name": name, "filename": filename, "color": color, "data": data})
    return runs


def verify_replays(runs: list[dict], root: Path = ROOT) -> dict:
    from rescore_report import rescore_report

    from nutrienv.bench import load_split
    from nutrienv.harness.prompt_freeze import assert_frozen

    split_path = root / IDENTITY["split"]
    tasks = {t.id: t for t in load_split(split_path)}
    split = read_json(split_path)
    assert_frozen()
    for run in runs:
        data = run["data"]
        if {r["task_id"] for r in data["tasks"]} != tasks.keys():
            raise ValueError(f"{run['filename']}: task IDs differ from the published split")
        for row in data["tasks"]:
            if row["query"] != tasks[row["task_id"]].query:
                raise ValueError(f"{run['filename']}: changed query {row['task_id']}")
        replay = rescore_report(data, tasks)
        for original, rescored in zip(data["tasks"], replay["tasks"], strict=True):
            if (original["passed"], original["score_tag"]) != (rescored["passed"], rescored["score_tag"]):
                raise ValueError(f"{run['filename']}: replay changed {original['task_id']}")
    return {
        "identity": IDENTITY,
        "split_version": split["version"],
        "split_sha256": sha256(split_path),
        "catalog": split["catalog"],
        "catalog_sha256": sha256(root / split["catalog"]),
        "reports": {run["filename"]: sha256(root / "reports" / run["filename"]) for run in runs},
        "verification": "All 189 task queries match; action acceptance, pass and score tags replay unchanged.",
        "hash_scope": "Current published artifacts verified by replay; original reports did not record run-time split/catalog hashes.",
    }


def render_table(runs: list[dict]) -> str:
    lines = ["| Model (ARK) | Pass | Rate | Avg steps | Avg latency | Update (2) | Log (6) | Evaluate (8) | Recommend (11) | Composite (36) |",
             "|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for run in sorted(runs, key=lambda r: -r["data"]["passed_tasks"]):
        d = run["data"]
        families = " | ".join(f"{d['family_breakdown'][f]['passed']}/{n}" for f, n in FAMILIES.items())
        lines.append(f"| [{run['name']}](reports/{run['filename']}) | {d['passed_tasks']}/63 | {100*d['passed_tasks']/63:.2f}% | {d['overall_avg_steps']:.2f} | {d['overall_avg_time_seconds']:.2f}s | {families} |")
    return "\n".join(lines)


def render_charts(runs: list[dict], output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.projections.polar import PolarAxes

    plt.style.use("dark_background")
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG,
                         "text.color": WHITE, "axes.labelcolor": MUTED})
    output.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.text(.5, .025, FOOTNOTE, ha="center", color=MUTED, fontsize=9)
        fig.savefig(output / name, dpi=240, facecolor=BG)
        plt.close(fig)

    ordered = sorted(runs, key=lambda r: r["data"]["passed_tasks"])
    fig, ax = plt.subplots(figsize=(12, 4.4))
    fig.subplots_adjust(left=.26, right=.96, top=.8, bottom=.23)
    for i, run in enumerate(ordered):
        passed = run["data"]["passed_tasks"]
        rate = 100 * passed / 63
        ax.barh(i, rate, height=.5, color=run["color"], zorder=3)
        ax.text(rate + 1.5, i, f"{rate:.1f}%  ({passed}/63)", va="center", weight="bold", fontsize=11)
    ax.set_yticks(range(3), [r["name"] for r in ordered], fontsize=12)
    ax.set_xlim(0, 120)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("Pass rate (%) · 63 tasks")
    ax.grid(axis="x", color=GRID, linestyle="--", zorder=0)
    ax.set_title("NutriEnv v1.1 — Internal ARK results", loc="left", weight="bold", fontsize=15, pad=22)
    for spine in ax.spines.values():
        spine.set_visible(False)
    save(fig, "v1.1_internal_ark_pass.png")

    fig, ax = plt.subplots(figsize=(12, 5.5))
    fig.subplots_adjust(left=.09, right=.95, top=.8, bottom=.22)
    for run, offset in zip(runs, ((12, 10), (12, -30), (-12, 14)), strict=True):
        d = run["data"]
        x, y = d["overall_avg_tokens_per_task"] / 1000, 100 * d["passed_tasks"] / 63
        ax.scatter(x, y, s=130, color=run["color"], edgecolors=WHITE, zorder=3)
        ax.annotate(f"{run['name']}\n{y:.1f}% · {x:.1f}k tokens", (x, y), xytext=offset,
                    textcoords="offset points", ha="right" if offset[0] < 0 else "left", fontsize=10)
    frontier, best = [], -1
    for run in sorted(runs, key=lambda r: r["data"]["overall_avg_tokens_per_task"]):
        d = run["data"]
        if d["passed_tasks"] > best:
            frontier.append((d["overall_avg_tokens_per_task"] / 1000, 100 * d["passed_tasks"] / 63))
            best = d["passed_tasks"]
    ax.plot(*zip(*frontier, strict=True), "--", color="#38BDF8", alpha=.8, label="Observed frontier (single runs)")
    ax.set(xlim=(60, 112), ylim=(0, 110), xlabel="Average tokens per task (k)", ylabel="Pass rate (%) · 63 tasks")
    ax.set_yticks(range(0, 101, 20))
    ax.grid(color=GRID, linestyle="--")
    ax.legend(loc="lower left", facecolor="#0F172A", edgecolor=GRID)
    ax.set_title("NutriEnv v1.1 — Token cost vs. accuracy", loc="left", weight="bold", fontsize=15, pad=22)
    save(fig, "v1.1_internal_ark_efficiency.png")

    angles = np.linspace(0, 2*np.pi, 5, endpoint=False).tolist()
    fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={"polar": True})
    ax = cast(PolarAxes, ax)
    fig.subplots_adjust(left=.15, right=.85, top=.77, bottom=.23)
    ax.set_theta_offset(np.pi/2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles, [f.title() for f in FAMILIES], fontsize=12)
    ax.tick_params(axis="x", pad=15)
    ax.set_ylim(0, 105)
    ax.set_yticks([20, 40, 60, 80, 100], ["20%", "40%", "60%", "80%", "100%"], color=MUTED, fontsize=9)
    ax.grid(color=GRID)
    ax.spines["polar"].set_color(GRID)
    for run, style in zip(runs, ("-", "--", ":"), strict=True):
        d = run["data"]
        values = [100*d["family_breakdown"][f]["passed"]/n for f, n in FAMILIES.items()]
        ax.plot(angles + angles[:1], values + values[:1], style, color=run["color"], linewidth=2.5, label=run["name"])
        ax.fill(angles + angles[:1], values + values[:1], color=run["color"], alpha=.06)
    fig.suptitle("NutriEnv v1.1 — Performance by family", y=.95, fontsize=16, weight="bold")
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.15), ncol=3, fontsize=9, facecolor="#0F172A", edgecolor=GRID)
    save(fig, "v1.1_internal_ark_family.png")


def main() -> None:
    runs = load_reports()
    provenance = verify_replays(runs)
    render_charts(runs, ROOT / "reports" / "assets")
    (ROOT / "reports" / "v1.1-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(render_table(runs))


if __name__ == "__main__":
    main()
