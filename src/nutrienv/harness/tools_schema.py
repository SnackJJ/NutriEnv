"""OpenAI-compatible native tool definitions for NutriEnv.

Each tool carries exactly what the text arm's manual line for that op says (``react._SYSTEM_V2``),
no more and no less: the description is the line's description, and a parameter description
appears only where the line says something about that argument. Structure the text arm spells out
in the signature (which arguments exist, which are optional via ``?``) is expressed here as the
JSON schema. ``tests/test_harness_modes.py`` pins the correspondence, so the two arms stay a
protocol comparison rather than an advice comparison.
"""


def _tool(name: str, description: str, properties: dict | None = None, required=()) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                **({"required": list(required)} if required else {}),
                "additionalProperties": False,
            },
        },
    }


NUTRIENV_TOOLS = [
    _tool(
        "search_foods",
        "BM25 search over the local USDA catalog; returns food_id and name",
        {"q": {"type": "string"}},
        ["q"],
    ),
    _tool(
        "get_food",
        "portions, nutrients and allergen tags for one food",
        {"food_id": {"type": "string"}},
        ["food_id"],
    ),
    _tool("get_profile", "allergies, daily target nutrient windows and published plan mass limits"),
    _tool("get_ledger", "meals logged so far today, with cumulative nutrients"),
    _tool("get_dri", "FDA daily reference values"),
    _tool(
        "log_meal",
        "record a consumed item; eaten_at e.g. today-lunch",
        {
            "food_id": {"type": "string"},
            "grams": {"type": "number"},
            "eaten_at": {"type": "string"},
        },
        ["food_id", "grams"],
    ),
    _tool(
        "amend_meal",
        "index is 0-based into the current ledger",
        {
            "index": {"type": "integer"},
            "grams": {"type": "number"},
            "food_id": {"type": "string"},
            "eaten_at": {"type": "string"},
        },
        ["index", "grams"],
    ),
    _tool(
        "submit_plan",
        "hand in a plan; verdict and reasons belong to evaluation tasks, and a reject carries "
        "no items",
        {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "food_id": {"type": "string"},
                        "grams": {"type": "number"},
                    },
                    "required": ["food_id", "grams"],
                    "additionalProperties": False,
                },
            },
            "verdict": {"type": "string"},
            "reasons": {"type": "array", "items": {"type": "string"}},
        },
        ["items"],
    ),
    _tool(
        "update_profile",
        'patch is a dict of profile fields, e.g. {"allergies": ["peanut"], "activity": "light"}',
        {"patch": {"type": "object"}},
        ["patch"],
    ),
    _tool("update_plan", "", {"patch": {"type": "object"}}, ["patch"]),
    _tool("finish", "hand in the episode"),
]

TOOL_SYSTEM_PROMPT = """You are an agent in NutriEnv, a steppable nutrition world.
Each turn call exactly one of the provided tools.
"""


from nutrienv.harness.prompt_freeze import SHARED_TASK_SPEC  # noqa: E402

TOOL_SYSTEM_PROMPT = TOOL_SYSTEM_PROMPT + SHARED_TASK_SPEC
