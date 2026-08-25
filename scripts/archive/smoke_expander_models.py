#!/usr/bin/env python3
"""Phase-1 availability smoke: one real Expander call per model id.

Reports success/failure for each id in the expander pool. A failed id is an
availability finding (wrong 百炼 id, quota, or provider). It does not fail
the script unless every model fails.

Run:  .venv/bin/python scripts/smoke_expander_models.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nutrienv.bench.pipeline.expander import (  # noqa: E402
    make_llm_expander,
    parse_expander_payload,
)
from nutrienv.bench.pipeline.models import DEFAULT_EXPANDER_MODELS  # noqa: E402
from nutrienv.bench.pipeline.types import (  # noqa: E402
    FoodPool,
    PoolFood,
    PortionAlternative,
)
from nutrienv.io.chat import EXPANDER_MODELS, complete_chat, lookup_chat_model  # noqa: E402
from nutrienv.io.dotenv import load_dotenv_keys  # noqa: E402

load_dotenv_keys(ROOT / ".env.local")


def _tiny_pool() -> FoodPool:
    return FoodPool(
        pool_id="smoke-0000",
        family="log",
        foods=(
            PoolFood(
                food_id="milk_whole",
                name="Milk, whole",
                aliases=("milk", "whole milk"),
                alternatives=(
                    PortionAlternative("cup", 1.0, "a cup", 244.0),
                    PortionAlternative("cup", 2.0, "two cups", 488.0),
                ),
            ),
            PoolFood(
                food_id="egg",
                name="Egg, whole",
                aliases=("egg", "eggs"),
                alternatives=(
                    PortionAlternative("piece", 1.0, "a piece", 50.0),
                    PortionAlternative("piece", 2.0, "two pieces", 100.0),
                ),
            ),
        ),
    )


def _probe(model_id: str, pool: FoodPool) -> tuple[bool, str, str]:
    """Return (ok, detail, stage). Tries primary, then fallback if any."""
    spec = lookup_chat_model(model_id)

    def primary(mid: str, messages):
        return complete_chat(mid, messages, attempt="primary", timeout=45.0, retries=2)

    try:
        expander = make_llm_expander(
            model_route=[model_id], seed=0, complete=primary, parse_retries=1
        )
        payload = expander(pool, persona="everyday", family="log")
        parsed = parse_expander_payload(json.dumps(payload))
        if parsed is None:
            return False, "primary answered but schema failed after retry", "primary"
        return True, f"primary ok query={parsed['query']!r:.120}", "primary"
    except Exception as exc:
        primary_err = f"{type(exc).__name__}: {exc}"

    if not spec.fallback_url:
        return False, primary_err, "primary"

    def fallback(mid: str, messages):
        return complete_chat(mid, messages, attempt="fallback", timeout=45.0, retries=2)

    try:
        expander = make_llm_expander(
            model_route=[model_id], seed=0, complete=fallback, parse_retries=1
        )
        payload = expander(pool, persona="everyday", family="log")
        parsed = parse_expander_payload(json.dumps(payload))
        if parsed is None:
            return False, f"primary failed ({primary_err}); fallback schema failed", "fallback"
        return True, f"fallback ok (primary: {primary_err})", "fallback"
    except Exception as exc:
        return False, f"primary: {primary_err} | fallback: {type(exc).__name__}: {exc}", "fallback"


def main() -> int:
    pool = _tiny_pool()
    print("expander model smoke (one real call each)")
    print(f"pool: {len(DEFAULT_EXPANDER_MODELS)} ids")
    print("-" * 72)
    failed: list[str] = []
    ok_ids: list[str] = []
    disabled_ids: list[str] = []
    for model_id in DEFAULT_EXPANDER_MODELS:
        spec = EXPANDER_MODELS.get(model_id)
        if spec is not None and spec.disabled:
            print(f"SKIP  {model_id:28}  already marked disabled")
            disabled_ids.append(model_id)
            continue
        try:
            ok, detail, stage = _probe(model_id, pool)
        except Exception as exc:  # noqa: BLE001 — smoke must report, not crash
            ok, detail, stage = False, f"{type(exc).__name__}: {exc}", "crash"
            traceback.print_exc()
        mark = "OK   " if ok else "FAIL "
        print(f"{mark} {model_id:28}  [{stage}] {detail}")
        if ok:
            ok_ids.append(model_id)
        else:
            failed.append(model_id)
    print("-" * 72)
    print(f"ok:       {ok_ids or ['(none)']}")
    print(f"failed:   {failed or ['(none)']}")
    print(f"disabled: {disabled_ids or ['(none)']}")
    print("keep in route table:", ok_ids)
    print("mark disabled:      ", failed)
    if not ok_ids:
        print("SYSTEMIC: every expander model failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
