#!/usr/bin/env python3
"""Admit an agent-authored draft after a separate review, with no query parsing.

First prepare the grounded review request:
    uv run python scripts/generate_one_cli.py --draft draft.json --prepare-review
Then pass a separate agent's exact-hash review:
    uv run python scripts/generate_one_cli.py --draft draft.json --review review.json --output item.json

The former parser/template CLI lives in scripts/archive/generate_one_cli.py.
This entry never falls back to it or silently invokes a paid model provider.
"""

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

def _read_artifact(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read agent artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"agent artifact {path} must be a JSON object")
    return payload


def main(argv=None) -> int:
    from nutrienv.bench.pipeline.generate_one import generate_one, review_packet
    from nutrienv.bench.pipeline.freezer import task_to_item
    from nutrienv.world.catalog_store import GOLD_CATALOG_PATH, load_catalog

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=GOLD_CATALOG_PATH)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare-review", action="store_true")
    modes.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    draft = _read_artifact(args.draft)
    catalog = load_catalog(args.catalog)
    if args.prepare_review:
        _, payload = review_packet(draft, catalog)
        code = 0
    else:
        review = _read_artifact(args.review)
        result = generate_one(catalog=catalog, author=lambda: draft, reviewer=lambda request: review)
        payload = {"status": "accepted" if result.accepted is not None else "rejected",
                   "draft_sha256": result.draft_sha256, "review": result.review,
                   "author_packet": draft}
        if result.accepted is not None:
            payload["item"] = task_to_item(result.accepted)
        else:
            assert result.rejected is not None
            payload["reason"] = result.rejected.reason
        code = 0 if result.accepted is not None else 1
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
