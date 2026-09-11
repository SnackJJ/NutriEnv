"""OpenAI-compatible native tool definitions for NutriEnv."""

NUTRIENV_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_foods",
            "description": "Search foods in the USDA food database using BM25. Returns matching food items with food_id and name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "Search query keywords, e.g. 'chicken breast' or 'brown rice cooked'."
                    }
                },
                "required": ["q"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_food",
            "description": "Fetch detailed nutritional content (calories, macros, micronutrients, allergen tags, portions) for a specific food_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food_id": {
                        "type": "string",
                        "description": "The unique food ID string (e.g. '2705956')."
                    }
                },
                "required": ["food_id"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_profile",
            "description": "Retrieve current user profile including allergies, medical conditions, and daily target nutrient windows.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_ledger",
            "description": "Retrieve current daily dietary ledger of meals already consumed today with cumulative nutrients.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_dri",
            "description": "Retrieve general Dietary Reference Intakes (DRIs) / FDA daily reference values.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_meal",
            "description": "Record a consumed food item into the user's daily dietary ledger.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food_id": {
                        "type": "string",
                        "description": "The food ID of the eaten food."
                    },
                    "grams": {
                        "type": "number",
                        "description": "Amount consumed in grams."
                    },
                    "eaten_at": {
                        "type": "string",
                        "description": "Optional meal slot, e.g. 'today-breakfast', 'today-lunch', 'today-dinner', 'today-snack'."
                    }
                },
                "required": ["food_id", "grams"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "amend_meal",
            "description": "Amend or correct an existing meal entry in the ledger by 0-based index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "0-based index into the current ledger."
                    },
                    "grams": {
                        "type": "number",
                        "description": "New gram quantity."
                    },
                    "food_id": {
                        "type": "string",
                        "description": "Optional new food_id."
                    },
                    "eaten_at": {
                        "type": "string",
                        "description": "Optional new meal slot."
                    }
                },
                "required": ["index", "grams"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile",
            "description": "Update user profile fields (allergies, activity level, weight, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "description": "Dictionary of fields to update, e.g. {'allergies': ['peanut', 'egg']} or {'activity': 'light'}."
                    }
                },
                "required": ["patch"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": "Final hand-in: submit a proposed meal plan or a verdict on an evaluated meal. For evaluation reject, items must be empty [].",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "List of food items and their gram quantities in the meal plan. Leave empty [] when rejecting an evaluated meal unless replacement is asked.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "food_id": {"type": "string"},
                                "grams": {"type": "number"}
                            },
                            "required": ["food_id", "grams"],
                            "additionalProperties": False
                        }
                    },
                    "verdict": {
                        "type": "string",
                        "enum": ["accept", "reject"],
                        "description": "Only used for evaluation tasks: 'accept' or 'reject'."
                    },
                    "reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required when verdict='reject', e.g. ['allergy'] or ['kcal_hi']."
                    }
                },
                "required": ["items"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Hand-in for update or log tasks that do not require a meal plan proposal.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    }
]

TOOL_SYSTEM_PROMPT = """You are an expert nutrition AI agent operating in NutriEnv, a steppable nutrition world.
You have access to a suite of nutrition tools to inspect user profiles, search the USDA food database, inspect portions and nutrients, log meals, and submit meal plans.

Guidelines:
1. Always call appropriate tools to ground your actions. Nutrient values and food IDs must come from tool observations, not assumptions. Catalog energy is per 100 g.
2. For multi-step queries, execute each required step:
   - If user asks to update allergies/profile and then recommend dinner: call update_profile, then search/plan, then submit_plan.
   - If user asks to log past meal: call log_meal. Never call log_meal for future meal recommendations.
   - For update or log tasks with no plan required: call finish when done.
3. Leftover questions: daily windows on get_profile are for the entire day. Subtract ledger nutrients from daily windows to get remaining budget, and submit_plan for remainder.
4. Single meal planning targets meal energy share: breakfast 25-30%, lunch 30-40%, dinner 30-40% of daily energy. Snack has none.
5. Evaluate:
   - submit_plan with verdict='accept' and exact named meal items.
   - Or verdict='reject', empty items [], and reason codes that fire (allergy alone suffices for allergen meals; else {kcal,protein_g,carb_g,fat_g,fiber_g,sodium_mg}_hi/_lo).
   - If the query also asks what to eat instead: a single submit_plan with verdict='reject', those reason codes, and items for the replacement meal.
6. Quantities should be grounded in portions from get_food or converted accurately to grams:
   - Common containers ("a bowl", "a plate", "a serving", "a sandwich", "two burritos"): check portions.qns or piece/slice/cup.
   - Unit multiplier: grams = portion_unit_grams * multiplier. An ounce is always 28.35 g.
7. Call exactly one tool at a time sequentially.
"""
