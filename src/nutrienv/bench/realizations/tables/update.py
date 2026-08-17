from __future__ import annotations

from ..types import UpdateRow

UPDATE_ROWS: tuple[UpdateRow, ...] = (
    UpdateRow(
        "up-gold-shrimp",
        "I just found out I'm allergic to shrimp. Add that to my profile.",
        add_allergens=("shellfish",),
        source="gold",
    ),
    UpdateRow(
        "up-gold-kcal",
        "I've been exhausted. Move my whole calorie range up by 200 — both the floor and the ceiling. Leave everything else alone.",
        window_shifts={"kcal": 200.0},
        source="gold",
    ),
    UpdateRow(
        "up-gold-both",
        "Add shellfish to my allergies — I reacted to shrimp — and move my whole calorie range up by 200. Don't change anything else.",
        add_allergens=("shellfish",),
        window_shifts={"kcal": 200.0},
        source="gold",
    ),
    UpdateRow(
        "up-gold-peanut",
        "Add peanut to my allergies.",
        add_allergens=("peanut",),
        s0_allergies=("shellfish",),
        source="gold",
    ),
    UpdateRow(
        "up-gold-protein",
        "I want more protein. Shift my protein range up 20 grams at both ends.",
        window_shifts={"protein_g": 20.0},
        source="gold",
    ),
    UpdateRow(
        "up-gold-cut",
        "I'm cutting now. Take 300 off both ends of my calorie range.",
        window_shifts={"kcal": -300.0},
        s0_allergies=(),
        s0_plan_preset={"goal": "cut"},
        source="gold",
    ),
    UpdateRow(
        "up-milk",
        "I reacted to milk. Add that to my allergies.",
        add_allergens=("milk",),
    ),
    UpdateRow(
        "up-soy-tofu",
        "I reacted to tofu. Add that to my allergies.",
        add_allergens=("soy",),
    ),
    UpdateRow(
        "up-egg",
        "I reacted to eggs. Add that to my allergies.",
        add_allergens=("egg",),
    ),
    UpdateRow(
        "up-fish-salmon",
        "I reacted to salmon. Add that to my allergies.",
        add_allergens=("fish",),
    ),
    UpdateRow(
        "up-tree-nut-almonds",
        "I reacted to almonds. Add that to my allergies.",
        add_allergens=("tree_nut",),
    ),
    UpdateRow(
        "up-kcal-plus-300",
        "Raise my whole calorie range by 300 at both ends.",
        window_shifts={"kcal": 300.0},
    ),
    UpdateRow(
        "up-kcal-minus-200",
        "Lower my whole calorie range by 200 at both ends.",
        window_shifts={"kcal": -200.0},
    ),
    UpdateRow(
        "up-protein-plus-30",
        "I want more protein. Shift my protein range up 30 grams at both ends.",
        window_shifts={"protein_g": 30.0},
    ),
    UpdateRow(
        "up-milk-kcal-200",
        "I reacted to milk. Add that to my allergies and raise my calorie range by 200 at both ends.",
        add_allergens=("milk",),
        window_shifts={"kcal": 200.0},
    ),
    UpdateRow(
        "up-soy-kcal-300",
        "I reacted to tofu. Add that to my allergies and increase my calorie range by 300 at both ends.",
        add_allergens=("soy",),
        window_shifts={"kcal": 300.0},
    ),
    UpdateRow(
        "up-egg-protein-20",
        "I reacted to eggs. Add that to my allergies and shift my protein range up 20 grams at both ends.",
        add_allergens=("egg",),
        window_shifts={"protein_g": 20.0},
    ),
    UpdateRow(
        "up-fish-protein-30",
        "I reacted to salmon. Add that to my allergies and raise my protein range 30 grams at both ends.",
        add_allergens=("fish",),
        window_shifts={"protein_g": 30.0},
    ),
    UpdateRow(
        "up-almond-kcal-minus-200",
        "I reacted to almonds. Add that to my allergies and lower my calorie range by 200 at both ends.",
        add_allergens=("tree_nut",),
        window_shifts={"kcal": -200.0},
    ),
    UpdateRow(
        "up-cut-400",
        "I'm cutting. Reduce my calorie range by 400 at both ends.",
        window_shifts={"kcal": -400.0},
        s0_allergies=(),
        s0_plan_preset={"goal": "cut"},
    ),
    UpdateRow(
        "up-milk-protein-30",
        "I reacted to milk. Add that to my allergies and shift my protein range up 30 grams at both ends.",
        add_allergens=("milk",),
        window_shifts={"protein_g": 30.0},
    ),
    UpdateRow(
        "up-egg-kcal-300",
        "I reacted to eggs. Add that to my allergies and raise my calorie range by 300 at both ends.",
        add_allergens=("egg",),
        window_shifts={"kcal": 300.0},
    ),
    UpdateRow(
        "up-rm-peanut",
        "I got tested — I'm not actually allergic to peanuts. Take that off my list.",
        remove_allergens=("peanut",),
    ),
    UpdateRow(
        "up-rm-shellfish",
        "I got tested — I'm not actually allergic to shellfish. Remove it.",
        remove_allergens=("shellfish",),
        s0_allergies=("peanut", "shellfish"),
    ),
    UpdateRow(
        "up-rm-milk",
        "The milk allergy was a false alarm. I'm not actually allergic to milk — remove it.",
        remove_allergens=("milk",),
        s0_allergies=("milk",),
    ),
    UpdateRow(
        "up-rm-egg",
        "I got tested — I'm not actually allergic to eggs. Take that off my allergies.",
        remove_allergens=("egg",),
        s0_allergies=("peanut", "egg"),
    ),
    UpdateRow(
        "up-floor-protein-20",
        "Raise just my protein floor by 20 grams. Leave the ceiling alone.",
        window_shifts={"protein_g": (20.0, 0.0)},
    ),
    UpdateRow(
        "up-floor-protein-30",
        "Bump the lower end of my protein range up 30 grams. Don't move the top.",
        window_shifts={"protein_g": (30.0, 0.0)},
    ),
    UpdateRow(
        "up-ceil-kcal-200",
        "Bring the calorie ceiling down by 200. Leave the floor where it is.",
        window_shifts={"kcal": (0.0, -200.0)},
    ),
    UpdateRow(
        "up-ceil-kcal-300",
        "Take 300 off the top of my calorie range. Don't touch the bottom.",
        window_shifts={"kcal": (0.0, -300.0)},
    ),
    UpdateRow(
        "up-floor-kcal-200",
        "Raise just the lower end of my calorie range by 200. Leave the ceiling alone.",
        window_shifts={"kcal": (200.0, 0.0)},
    ),
    UpdateRow(
        "up-ceil-protein-20",
        "Bring the upper end of my protein range down 20 grams. Leave the floor alone.",
        window_shifts={"protein_g": (0.0, -20.0)},
    ),
    UpdateRow(
        "up-two-kcal-200-prot-20",
        "Raise my calorie range by 200 at both ends and my protein range by 20 at both ends.",
        window_shifts={"kcal": 200.0, "protein_g": 20.0},
    ),
    UpdateRow(
        "up-two-kcal-300-prot-30",
        "Take 300 off both ends of my calorie range and raise protein 30 grams at both ends.",
        window_shifts={"kcal": -300.0, "protein_g": 30.0},
    ),
    UpdateRow(
        "up-two-kcal-200-prot-30",
        "Move my calorie range down 200 at both ends and raise protein 30 grams at both ends.",
        window_shifts={"kcal": -200.0, "protein_g": 30.0},
    ),
    UpdateRow(
        "up-add-milk-egg",
        "I reacted to milk and eggs. Add both to my allergies.",
        add_allergens=("egg", "milk"),
        s0_allergies=(),
    ),
    UpdateRow(
        "up-add-fish-treenut",
        "I reacted to salmon and almonds. Add both of those allergies.",
        add_allergens=("fish", "tree_nut"),
        s0_allergies=(),
    ),
    UpdateRow(
        "up-add-soy-wheat",
        "I reacted to tofu and pasta. Add both to my allergies.",
        add_allergens=("soy", "wheat"),
        s0_allergies=(),
    ),
    UpdateRow(
        "up-preset-cut-muscle",
        "I'm switching from a cut to a muscle plan. Update my plan.",
        s0_plan_preset={"goal": "cut"},
        set_plan_preset={"goal": "muscle"},
    ),
    UpdateRow(
        "up-preset-muscle-cut",
        "I was on a muscle plan; now I want to cut. Change my plan.",
        s0_plan_preset={"goal": "muscle"},
        set_plan_preset={"goal": "cut"},
    ),
)
