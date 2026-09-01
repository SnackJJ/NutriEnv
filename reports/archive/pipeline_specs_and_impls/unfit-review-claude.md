# Claude (Opus) adjudication — Evaluate-unfit taxonomy

**Verdict: accept-with-nits.** Coverage is complete; the *shape* is mis-factored; one real gap (iso-energy failures);
and I **overturn** the AGY/codex call to cut `leftover_under` — that premise is arithmetically wrong for the last meal.

## 1. Complete? Mis-factored, one gap

The seven rows are not one partition — they mix three independent dimensions: **knife** (what code does: allergy /
bump / accompaniment / drop / step-down / **swap**), **scene** (which leg of `meal-slot ∩ remainder` binds),
**outcome** (`multi` = code cardinality, `sodium_hi` = which nutrient). `sodium_hi` ⊂ `over_slot`; `multi` is a
result, never an intent. Keep both as coverage tags with floors, not peer types — a sodium item that also fires
`kcal_hi` is otherwise two types at once and type↔gold checks become undefined. Never add a violation to earn `multi`.

**Gap: no knife produces an in-energy failure.** Every listed knife moves kcal — bump and accompaniment raise it, drop
and step-down lower it. So nearly every unfit gold set carries a kcal code, and an agent that checks only kcal scores
near-ceiling on the unfit half. Add a **swap** knife (iso-caloric substitution). It is authorable: at FDA fat 78 g /
2000 kcal, dinner slot hi ≈ 0.40×78 ≈ 31 g, so a 700 kcal dinner (inside a ~570–760 band) carrying 40 g fat fires
`fat_g_hi` alone; same for `fiber_g_lo` on a refined-grain plate at correct energy. This is what separates window
arithmetic from eyeballing.

Nothing else is missing. Two explicit non-types: an allergen in the **ledger** (descriptive, not a reject), and already-infeasible windows (§5 guard).

## 2. `leftover_under`: **keep** — the peers' cut argument is wrong

Codex's reason ("remainder lo is `max(0, lo−used)`, so the ledger relaxes a lower bound") holds against the *daily*
floor and fails against the *intersection*, which is what is judged. With `lo = max(slot_lo, remainder_lo)`:

- remainder binds ⟺ `used < (1 − share_lo)·daily_lo` → dinner: `used < 0.70·daily_lo`. Breakfast+lunch land at 55–70%,
  so **the remainder leg is the binding lo on an ordinary day.**
- non-degenerate ⟺ `remainder_lo ≤ slot_hi` → `used ≳ daily_lo − 0.40·daily_hi ≈ 0.60·daily_lo`.

The authorable band is therefore a day that has logged ~60–70% of its floor — exactly a normal breakfast+lunch. ADR
0017's "(rare)" is wrong. Cutting it removes the **only** item testing the lo side of the intersection: an agent that
computes slot share and never reads the ledger passes every `under_slot` and fails only here. Conditions: last meal of
the day only; below-60% days must be dropped by the §5 guard — those are impossible-window items that belong to
constrained Recommend.

## 3. Energy overflow: prefer `leftover_over`, but fix the confound

Agree, with two refinements. (a) The preference is against **portion multipliers**, not `over_slot` itself: "burger +
fries + soda" is an ordinary plate that overflows a dinner slot on an empty ledger. Forbid bumps beyond one catalog
portion step; allow accompaniment-add freely. (b) Bigger risk than cartoon plates: if heavy ledgers appear only on
rejects, "ledger non-empty ⇒ reject" is a free feature. Require a matching share of **fit** items with a non-trivial
ledger and a tight but satisfiable remainder. Likewise, unfit must not correlate with explicit grams vs qns.

## 4. Collisions with today's code (all blocking for unfit rows)

1. `WorldState` (`src/nutrienv/world/types.py:58-68`) holds only `profile/ledger/catalog/last_plan`; `Oracle`
   (`bench/realize.py:109-121`) has no verdict/reasons field. Gold reason codes have nowhere to live and "silence is
   not reject" is unscoreable today.
2. `_score_plan` (`bench/scorer.py:88-92`) maps empty `last_plan` → `wrong_goal` unless `allow_empty_plan`. That flag
   is **not** the fix: `_conflict_from_row` (`realize.py:604-612`) already uses `last_plan=None,
   allow_empty_plan=True, plan_must_fit_windows=True`, under which an agent submitting a *different, fitting* meal also
   passes — silently re-collapsing Evaluate-unfit into Recommend-substitute, which ADR 0016 forbids. Unfit needs its own
   marker, not a reused sentinel.
3. `_evaluate_from_row` (`realize.py:522-544`) derives windows **from the meal** via `evaluate_windows`
   (`realizations/types.py:224-243`, kcal + protein_g only) and *strips* colliding allergens — evaluate items are fit
   by construction and `carb_g/fat_g/fiber_g/sodium_mg` can never fire. The unfit path must set `plan_windows` = slot ∩
   remainder over all six keys (ADR 0014); reusing `evaluate_windows` leaves `sodium_hi` unrealizable.
4. `_remainder_windows` (`realize.py:425-431`) clamps to `max(0,·)`, so a heavy leftover_over drives remainder hi → 0:
   any non-empty plate fires that code and gold can reach 5–6 codes.
5. Scorer tags (`wrong_goal/window/allergy/log_miss/update_miss`) are failure labels, not agent reasons — reason-set
   equality is new code, not a knob. `FAMILIES` (`realize.py:59`) still lists the retired `constrain`.

I confirm codex's further items (`_validate_evaluate`, `submit_plan` schema, split freezing, `_sub_family`'s empty-plan
→ Recommend inference). No unfit rows before that seam lands.

## 5. Nits (concrete)

1. Re-express the table as knife × scene × outcome; `sodium_hi` / `multi` become coverage floors.
2. Add the **swap** knife plus a floor of ≥6 unfit items whose gold set contains no kcal code.
3. Derive the `leftover_*` label instead of declaring it: per fired code, record which leg the violated bound came
   from. `leftover_over` ⇔ a hi code bound by remainder while slot hi passes; `leftover_under` ⇔ the same on the lo
   side. Mislabels then fail at bind.
4. Admission guard: after intersection require `lo ≤ hi` on all six keys plus plate-satisfiability (`bench/windows.py:
   windows_unsatisfiable / any_pair_unsatisfiable`); drop the rest. Cap gold cardinality (reject > 3 codes) and log the
   drops — a 6-code gold set is a degenerate world, not a hard item.
5. Record each violation's margin and enforce a band mix — ≥1/3 of unfit items within 10% of the bound, and fit items
   near bounds too, so accept/reject is not linearly separable.
6. Keep `leftover_under` at a small floor (3–5), last meal only.
