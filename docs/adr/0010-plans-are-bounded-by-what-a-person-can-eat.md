# Food quantities are bounded by what a person can eat

Env rejects a single quantity above **2000 g** and a submitted plan whose total
exceeds **4000 g**, as an Illegal Action with code `implausible_quantity`.

## Why

The `constrain`/`conflict` family freezes 17 items whose nutrient windows no
combination of foods can satisfy. The scored answer is to submit nothing.

They were all beatable. The catalog holds 14 entries with **0 kcal and a trace
of protein or fat** — decaf coffee at 0.1 g protein per 100 g. A kcal ceiling
cannot bind a food with no kcal, so any protein or fat floor is reachable by
eating enough of it. Seven of eight sampled conflict items fell, including the
gold item `v0-rec-conflict-001`, which passes on 90,909 g of brewed coffee.

`validate_draft` already assumed such a plan is not food: `_windows_unsatisfiable`
skips zero-kcal sources below 1 g/100 g. The Scorer shared no such assumption,
so the factory and the exam disagreed about what counts as a meal.

## Why in Env rather than the Scorer

A person cannot eat 91 kg. That is a fact about the world, not a grading rule.
CONTEXT.md defines Env as the objective nutrition world and an Illegal Action as
something Env "rejects immediately as physics" — an unminted id today, an
uneatable quantity now. Putting the bound in the Scorer would locate a world
fact in the grader, and would let the agent build a whole trajectory on an
impossible premise before learning at hand-in that it never counted.

## The numbers

Generous on purpose. The largest quantity anywhere in the four frozen splits is
300 g; the largest legitimate plan total is 670 g; the achievability search
never exceeds about 1200 g. The bounds sit far above every real item and far
below the 50,000 g the exploit needs, so no existing item changes meaning.

Both bounds are needed. Without the plan total, 35 items of 2000 g rebuild the
attack.

## What this does not do

It does not remove the odd catalog entries. They are real foods and dropping
them would change `catalog_sha256`, invalidating the build hash every frozen
split is pinned to.

It does not make the feasibility gate exact. `_windows_unsatisfiable` still
reasons about ratios rather than about bounded quantities, and its 1 g/100 g
threshold is still a heuristic. The gate is a factory filter; this bound is
what the exam actually enforces.

**Status**: accepted
