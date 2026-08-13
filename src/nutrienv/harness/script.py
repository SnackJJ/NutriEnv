"""Deterministic scripted harness. No LLM, no scorer."""

from __future__ import annotations

import re

from .protocol import Harness

__all__ = ["ScriptHarness"]

_LOG_MARKERS = ("log", "ate", "eaten", "ledger")
_RECOMMEND_MARKERS = ("recommend", "suggest", "evaluate", "submit a", "food plan")
_UPDATE_MARKERS = ("tired", "update my profile", "kcal window")

_GRAMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*g(?:rams)?\s+(?:of\s+)?([a-z][a-z0-9_ ]+?)"
    r"(?=\s+at\b|\s+and\b|,|;|\.|$)",
    re.IGNORECASE,
)
_OUNCES = re.compile(
    r"(\d+(?:\.\d+)?)\s*ounces?\s+of\s+([a-z][a-z0-9_ ]+?)"
    r"(?=\s+at\b|\s+and\b|,|;|\.|$)",
    re.IGNORECASE,
)
_AT = re.compile(r"\bat\s+([a-z0-9_-]+)", re.IGNORECASE)
_KCAL_WINDOW = re.compile(
    r"kcal window to\s+([0-9.]+)\s*-\s*([0-9.]+)", re.IGNORECASE
)
_TRAILING = re.compile(
    r"\s+(entry|only|items|converted to grams|each)$", re.IGNORECASE
)

_OUNCE_G = 28.35
_CHICKEN = "chicken_breast"
_RICE = "white_rice"


class ScriptHarness(Harness):
    """Heuristic policy. Emits only typed Env actions; never scores."""

    def act(self, observation: dict, query: str, history: list) -> dict:
        text = query.lower()
        if _looks_like(text, _LOG_MARKERS):
            return self._log(observation, query, history)
        if _looks_like(text, _RECOMMEND_MARKERS):
            return self._recommend(observation, history)
        if _looks_like(text, _UPDATE_MARKERS):
            return self._update(observation, query, history)
        return self._read(history)

    def _log(self, observation: dict, query: str, history: list) -> dict:
        seen = _food_ids(observation, history)
        searched = _searched(history)
        logged = {
            event["action"]["food_id"]
            for event in history
            if event["action"].get("op") == "log_meal" and "food_id" in event["action"]
        }
        for item in _parse_log_items(query):
            match = _resolve_seen(item["q"], seen)
            if match is None:
                needle = item["q"]
                if needle in searched:
                    continue
                return {"op": "search_foods", "q": needle}
            if match in logged:
                continue
            action: dict = {"op": "log_meal", "food_id": match, "grams": item["grams"]}
            if item["eaten_at"]:
                action["eaten_at"] = item["eaten_at"]
            return action
        return self._read(history)

    def _recommend(self, observation: dict, history: list) -> dict:
        if _has_op(history, "submit_plan"):
            return self._read(history)
        seen = _food_ids(observation, history)
        searched = _searched(history)
        for food_id in (_CHICKEN, _RICE):
            if food_id in seen:
                continue
            if food_id in searched:
                return self._read(history)
            return {"op": "search_foods", "q": food_id}
        items = _plan_in_windows(
            _profile(observation, history),
            [
                {"food_id": _CHICKEN, "grams": 200.0},
                {"food_id": _RICE, "grams": 300.0},
            ],
        )
        return {"op": "submit_plan", "items": items}

    def _update(self, observation: dict, query: str, history: list) -> dict:
        if _has_op(history, "update_profile"):
            return self._read(history)
        match = _KCAL_WINDOW.search(query)
        if match:
            lo, hi = float(match.group(1)), float(match.group(2))
        else:
            profile = _profile(observation, history)
            current = (profile.get("windows") or {}).get("kcal")
            if isinstance(current, (list, tuple)) and len(current) == 2:
                lo, hi = float(current[0]) + 200.0, float(current[1]) + 200.0
            else:
                lo, hi = 2000.0, 2400.0
        return {"op": "update_profile", "patch": {"windows": {"kcal": [lo, hi]}}}

    @staticmethod
    def _read(history: list) -> dict:
        if not _has_op(history, "get_profile"):
            return {"op": "get_profile"}
        return {"op": "get_ledger"}


def _looks_like(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _has_op(history: list, op: str) -> bool:
    return any(event["action"].get("op") == op for event in history)


def _searched(history: list) -> set[str]:
    return {
        event["action"]["q"]
        for event in history
        if event["action"].get("op") == "search_foods" and "q" in event["action"]
    }


def _observations(observation: dict, history: list) -> list[dict]:
    blobs = [observation] if isinstance(observation, dict) else []
    for event in history:
        result = event.get("result") or event.get("step") or {}
        obs = result.get("observation") if isinstance(result, dict) else None
        if isinstance(obs, dict):
            blobs.append(obs)
        if isinstance(result, dict) and result.get("error"):
            blobs.append(result)
    return blobs


def _food_ids(observation: dict, history: list) -> set[str]:
    ids: set[str] = set()
    for obs in _observations(observation, history):
        for row in obs.get("results") or []:
            if isinstance(row, dict) and row.get("food_id"):
                ids.add(str(row["food_id"]))
        food = obs.get("food")
        if isinstance(food, dict) and food.get("food_id"):
            ids.add(str(food["food_id"]))
        for row in obs.get("ledger") or []:
            if isinstance(row, dict) and row.get("food_id"):
                ids.add(str(row["food_id"]))
        for item in obs.get("last_plan") or []:
            if isinstance(item, dict) and item.get("food_id"):
                ids.add(str(item["food_id"]))
    return ids


def _profile(observation: dict, history: list) -> dict:
    for obs in reversed(_observations(observation, history)):
        profile = obs.get("profile")
        if isinstance(profile, dict):
            return profile
    return {}


def _resolve_seen(needle: str, seen: set[str]) -> str | None:
    key = needle.strip().lower().replace(" ", "_")
    if key in seen:
        return key
    compact = key.replace("_", "")
    for food_id in sorted(seen):
        if compact in food_id.replace("_", "") or food_id.replace("_", "") in compact:
            return food_id
    return None


def _parse_log_items(query: str) -> list[dict]:
    eaten = None
    at = _AT.search(query)
    if at:
        eaten = at.group(1)
    items: list[dict] = []
    for match in _GRAMS.finditer(query):
        items.append(
            {
                "q": _TRAILING.sub("", match.group(2).strip()).strip(),
                "grams": float(match.group(1)),
                "eaten_at": eaten,
            }
        )
    for match in _OUNCES.finditer(query):
        items.append(
            {
                "q": match.group(2).strip(),
                "grams": float(match.group(1)) * _OUNCE_G,
                "eaten_at": eaten,
            }
        )
    lowered = query.lower()
    if "cup of milk" in lowered:
        grams = 122.0 if "half" in lowered else 244.0
        items.append({"q": "milk", "grams": grams, "eaten_at": eaten})
    return items


def _plan_in_windows(profile: dict, items: list[dict]) -> list[dict]:
    """Leave default grams unless a single kcal window can absorb the pair."""
    windows = profile.get("windows") or {}
    kcal = windows.get("kcal")
    if not isinstance(kcal, (list, tuple)) or len(kcal) != 2:
        return items
    lo, hi = float(kcal[0]), float(kcal[1])
    # chicken_breast 165 kcal/100g, white_rice 130 kcal/100g
    base = 165.0 * items[0]["grams"] / 100.0 + 130.0 * items[1]["grams"] / 100.0
    if lo <= base <= hi or base <= 0:
        return items
    mid = (lo + hi) / 2.0
    scale = mid / base
    scaled = []
    for item in items:
        grams = round(item["grams"] * scale, 1)
        if grams <= 0:
            return items
        scaled.append({"food_id": item["food_id"], "grams": grams})
    return scaled
