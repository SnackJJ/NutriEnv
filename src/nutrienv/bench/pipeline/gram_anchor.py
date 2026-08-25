"""Live gram-anchor: LLM proposes a portion, code verifies against the table.

``resolve_portion`` / ``_bind_log_foods`` call a ``GramAnchor`` only when the
grammar cannot parse a spoken clause. The anchor is authoring-time only and
its output is never a gram fact: the portion-table whitelist is the veto.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence

__all__ = ["LlmGramAnchor", "make_llm_gram_anchor"]

#: Quantity multiples the portion whitelist accepts. A proposed quantity
#: outside this set can never pass ``matches_portion_table``.
_QUANTITY_MULTIPLES = (0.5, 1.0, 1.5, 2.0)

_SCHEMA_BLOCK = """\
Return exactly one JSON object and nothing else (no markdown, no prose).
Prefer a table key: {"quantity": <number>, "key": "<portion key>"}
(e.g. {"quantity": 2, "key": "wing"}). Otherwise propose grams directly:
{"grams": <number>}. Use only one of the two shapes."""  # noqa: E501


class LlmGramAnchor:
    """One LLM completion → parsed portion, validated by the table whitelist.

    ``call`` returns grams for the food's portion table (``quantity * key``
    for the key shape), or ``None`` when the API fails, the payload is
    malformed, or the result is not a finite positive number. The caller's
    ``matches_portion_table`` remains the final deterministic veto.
    """

    def __init__(
        self,
        *,
        catalog: Mapping,
        complete: Callable[[str, Sequence[Mapping[str, str]]], str] | None = None,
        model_id: str = "qwen3.8-max",
        parse_retries: int = 0,
    ) -> None:
        self._catalog = catalog
        if complete is None:
            from nutrienv.io.chat import complete_chat

            def _live(model_id: str, messages: Sequence[Mapping[str, str]]) -> str:
                return complete_chat(model_id, messages)

            complete = _live
        self._complete = complete
        self._model_id = model_id
        self._parse_retries = max(0, int(parse_retries))

    def __call__(self, food_id: str, expression: str, query: str) -> float | None:
        messages: list[Mapping[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You propose the portion quantity and key for a spoken "
                    "meal phrase. Do not invent gram facts: the proposal is "
                    "checked against the food's portion table by code."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Food id: {food_id}\n"
                    f"Spoken portion phrase: {expression!r}\n"
                    f"Full user query: {query!r}\n\n"
                    + _SCHEMA_BLOCK
                ),
            },
        ]
        for attempt in range(1 + self._parse_retries):
            try:
                text = str(self._complete(self._model_id, messages))
            except Exception:
                return None  # fail-closed on network/API failure
            grams = self._grams_from_payload(_parse_anchor_payload(text), food_id)
            if grams is not None:
                return grams
            if attempt < self._parse_retries:
                messages = messages + [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": "Return only the JSON object per the schema.",
                    },
                ]
        return None

    def _grams_from_payload(
        self, payload: Mapping[str, object] | None, food_id: str
    ) -> float | None:
        if payload is None:
            return None
        entry = self._catalog.get(food_id) if self._catalog is not None else None
        portions = entry.get("portions") if isinstance(entry, Mapping) else {}
        portions = portions if isinstance(portions, Mapping) else {}
        if "grams" in payload:
            grams = payload.get("grams")
            if isinstance(grams, bool) or not isinstance(grams, (int, float)):
                return None
            out = round(float(grams), 2)
            return out if out > 0 else None
        if "quantity" in payload and "key" in payload:
            quantity = payload.get("quantity")
            key = payload.get("key")
            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
                return None
            if not isinstance(key, str) or not key.strip():
                return None
            key = key.strip()
            one = portions.get(key)
            if isinstance(one, bool) or not isinstance(one, (int, float)):
                return None
            rounded_quantity = round(float(quantity), 2)
            if rounded_quantity not in _QUANTITY_MULTIPLES:
                return None
            out = round(rounded_quantity * float(one), 2)
            return out if out > 0 else None
        return None


def _parse_anchor_payload(text: str) -> Mapping[str, object] | None:
    data = _extract_json_object(text)
    if not isinstance(data, Mapping):
        return None
    if "grams" in data:
        return {"grams": data.get("grams")}
    if "quantity" in data and "key" in data:
        return {"quantity": data.get("quantity"), "key": data.get("key")}
    return None


def _extract_json_object(text: str) -> object | None:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S | re.I)
    candidates = [fenced.group(1), stripped] if fenced else [stripped]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        first = len(candidate) - len(candidate.lstrip())
        if first < len(candidate) and candidate[first] in "{[":
            try:
                data, _ = decoder.raw_decode(candidate, first)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                return data
        for start in (match.start() for match in re.finditer(r"\\{", candidate)):
            try:
                data, _ = decoder.raw_decode(candidate, start)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return None


def make_llm_gram_anchor(
    *,
    catalog: Mapping,
    model_id: str = "qwen3.8-max",
    complete: Callable[[str, Sequence[Mapping[str, str]]], str] | None = None,
    parse_retries: int = 0,
) -> LlmGramAnchor:
    return LlmGramAnchor(
        catalog=catalog,
        complete=complete,
        model_id=model_id,
        parse_retries=parse_retries,
    )
