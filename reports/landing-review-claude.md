# Claude (Opus) adjudication — mill landing + Env seam

**Section A: accept-with-nits** (5, all authoring-time; nothing contradicts ADR 0016/0017/CONTEXT).
**Section C: accept, with the 4 decisions below, 6 omissions, and a reordered C7.**

| Q | Decision |
|---|---|
| C2.1 infer accept | **Keep inference**, amended: `submit_plan` writes all three fields; empty + no verdict → `(None, [], ())` |
| C2.3 reject + items | **Require `items == []`**; non-empty → Illegal Action, world unchanged |
| C2.4 reasons vs meal | **Confirmed**: Env checks vocabulary + envelope coherence only, never fit |
| C5 Profile | **Stacked, and split in two**; the verdict PR does not wait on it |

## 1. Mill section A — nits

1. **Admission is not dependency-aware.** ADR 0017 forbids a leftover S0 whose foods were never a Log item, but admission drops drafts: drop a
   parent Log and every dependent leftover Evaluate/Recommend is orphaned. State the rule — dependents drop with the parent, or re-parent, or
   relax to "came from the Log pipeline" rather than "published". State the supply bound too: 48 logs / 20 people ≈ 2.4 log-days each, so "prefer
   `leftover_over`" must degrade to a bump when a person's day has no earlier log, or the same few ledgers repeat.
2. **"~20 × ~12" reads as a grid** — the generate-time kill switch ADR 0017 rejects. Say it describes the *published* set and that per-person
   counts are approximate (72 recommend / 20 = 3.6, so 12-per-person cannot be a quota), and whether a composite consumes one of the 12.
3. **Stage A will systematically reject the unfit slice.** Voters see food+grams blind and are asked "eatable plate?", but an `over_slot` draft is
   *supposed* to be over. Keep the vote blind (disclosing the knife leaks gold); fix the prompt: "could one person eat this at one meal?" plus an
   explicit "large portions are allowed; you are not judging whether the meal is wise". Otherwise admission tracks knife size, not eatability.
4. **`leftover_under`'s "drop if it does not discriminate" has no decision rule** — at freeze that becomes a taste call on the exam file. Fix one
   now, e.g. keep iff ≥1 baseline fails it while passing its matched fit control.
5. **`generate_one` is in flight** (`scripts/`, `pipeline/`, `tests/`) while A closes "four `generate_one` scripts". Say plainly that the single
   `generate_one` is the one-pipeline entry and only the four-per-family split is closed.

## 2. Env seam decisions

**C2.1 — keep inference, but no stale field.** Inference is forced: the 48 frozen evaluate and 72 recommend items submit with no verdict, and Oracle
`last_verdict=None` makes the scorer skip it. Requiring explicit `accept` on new Evaluate-fit would split one family into two handbook rules — worse
than a vacuous check. Amend rule 1's "leave `last_verdict` as it was": that yields `accept` + empty plan after accept-then-retract, a state no Oracle
can match and no invariant can assert. Make `submit_plan` **total** on the triple — non-empty + no verdict → `(accept, items, ())`; empty + no verdict
→ `(None, [], ())`. Silence still stays silence, old items still Pass, and the world keeps `accept ⇔ non-empty plan`.

**C2.3 — require `items == []`.** Ignoring items is Env deciding the verdict beats the payload — semantics, and it contradicts `schemas.py`'s own
contract ("unknown keys are a schema error, not silently ignored"). It also opens the hole the seam exists to close: an agent that rejects *and*
substitutes lands a world byte-identical to a clean reject, so ADR 0016's forbidden reject-then-replace **Passes**. `ActionError("bad_schema", …)`
leaves the world untouched and leaks nothing about fit — the message is envelope shape, not whether the meal was over. Add the two symmetric rules C2
omits: `accept` with non-empty `reasons` → Illegal; `reasons` without `verdict` → Illegal. Leave `reject` with empty `reasons` **legal** — a losing
state, not an incoherent one; forcing a reason would be Env asserting semantics.

**C2.4 — confirmed.** Env cannot check reasons without becoming Bench: "the named meal" is a Task fact Env does not hold, and `plan_windows` =
meal-slot ∩ remainder is a Bench view (CONTEXT: Remainder is "not a field anyone writes"). Checking is Env inventing evaluation (ADR 0003/0004). Env
owns only the *vocabulary*, same class as `normalize_tags` — with two constraints: put `REASON_CODES` in `world/types.py` (Env owns world vocabulary;
Bench imports it, as the scorer already imports `normalize_tags`), and make it a **frozen constant**, not derived from that profile's window keys. A
token legal on one Task and illegal on another breaks "every Action is available on every Task".

**C5 — stacked, and split C5 itself.** Do not bundle with verdict: different blast radius (verdict risks 48 evaluate items and the Action envelope;
Profile touches all 240 profiles and the Update family), so a bundled zero-drift failure cannot be attributed. C5 is not a debate anyway — ADR
0014/0015 already accept Env re-derivation; this is execution. Split it because the halves differ in risk: **(a) fields + defaults** is purely
additive and can land first, unblocking roster S0 breadth; **(b) re-derivation on body/phase patch** touches Update semantics and needs its own gate.
Freeze the verdict envelope early — handbook, freezer payload and every future split header depend on it.

**Six omissions in C.**
- **Scorer branch order.** `oracle.last_plan == []` is today's free-recommendation sentinel. Dispatch on `last_verdict` **before** it, or a reject
  Oracle falls into "any fitting plan Passes".
- **Reject Oracles must set `plan_must_fit_windows=False`, `plan_must_be_safe=False`, `allow_empty_plan=False`** — the verdict branch owns scoring.
  This also silences `validator.py:257`, whose reachability check would otherwise flag **every** unfit draft as "unpassable" and drop the slice.
- **`freezer._sub_family` is a silent-corruption path**: it returns `"recommend"` for any `last_plan == []`, so a frozen reject child re-loads as a
  Recommend. Must become verdict-aware alongside `split.py::_oracle`.
- **Mifflin×PAL does not exist yet and must not live in `bench/`.** If Env re-derives on patch the formula belongs in `world/` with Bench importing
  it; Env importing Bench inverts the Runner composition root.
- **ADR 0015 band scoring is missing from C5.** The scorer has only exact `profile != oracle.profile → update_miss`; implicit Update Passes on a
  *band*. Without it C5 lands and those items are unscoreable.
- **Reason bind must reuse `_remainder_windows`' `round(…, 2)` and `max(0.0, …)` exactly.** Reason sets Pass on exact set equality, so 0.005 of drift
  flips a code and flips Pass. Note the clamp's consequence: once a daily floor is met the remainder leg can never fire a `_lo` code, so every `_lo`
  must be attributable to the slot leg — consistent with `leftover_under` being last-meal-only, but assert it rather than assume it.

## 3. C7 order — reorder

Two problems: step 3 bundles realize-unfit with Profile re-derivation (unrelated, separately risky), and `react.py` at step 4 leaves an actively wrong
handbook line ("If `last_plan` already violates the windows, `submit_plan {"items": []}`") teaching exactly the behavior that is now silence. Hard
discipline #4 wants symmetry the moment the expression exists.

0. Capture the zero-drift baseline: 240 Pass + the report digest (1049).
1. `WorldState` + `REASON_CODES` in `world/types.py` + schema + dispatch + `reset`/`get_profile` observations **+ the two `react.py` lines, replacing
   the old empty-items line, in the same PR** → verify silence / accept / reject / every Illegal variant, world byte-identical on each Illegal.
2. Oracle fields + `split.py::_oracle` + `freezer._oracle_payload` + `_sub_family` + scorer verdict branch + validator → verify **all 240 Pass and the
   report digest is unchanged**, not just "old evaluate fixtures".
3. C5a: Profile fields + defaults + `profile_view` + split load → verify 240 Pass unchanged. *May land before 1.*
4. C5b: `world/` Mifflin×PAL + re-derivation + `PROFILE_PATCH_KEYS` + ADR 0015 bands → verify the 36 update items Pass unchanged and a windows-only
   patch does **not** re-derive.
5. Realize evaluate-unfit + six-key `plan_windows` (the meal-slot leg does not exist today) + reason bind + validator reason-equality.
6. Mill emits unfit candidates.

## 4. Tests required before "done"

The one that must exist: **a reject Oracle against a fitting, allergen-safe, non-empty substitute must fail** — verdict omitted *and* `verdict=accept`.
That is the hole `allow_empty_plan` opens and the ADR 0016 rule the seam exists to enforce; without it a later refactor reusing `allow_empty_plan`
re-opens it and nothing goes red. Also required:

- **Zero drift**: all 240, and specifically the 48 evaluate items Passing via `submit_plan {items:[…]}` with no verdict.
- **Silence ≠ reject**: no action → fail; `{items: []}` with no verdict → fail.
- **Reason sets**: subset fails, superset fails, permuted+duplicated passes (set equality), empty-on-reject fails.
- **Env does not judge**: reject with a legal-but-wrong code on a *fit* meal → `ok=True` from Env, fail from the scorer. Pins C2.4 so nobody later
  adds a "helpful" check in dispatch.
- **Illegal leaves the world byte-identical** for reject+items, accept+reasons, reasons-without-verdict, unknown token — deepcopy-compare, since the
  write is now three fields and `dispatch.py` promises validate-then-mutate.
- **Last write wins**: accept→reject, reject→accept, accept→empty. No stale field survives.
- **Round-trip**: unfit Oracle → freezer → JSON → `load_split` → identical Oracle, `_sub_family` says `evaluate`, and a split JSON with **no**
  `last_verdict` key loads as `None`.
- **Boundary**: a meal exactly at a rounded `plan_windows` lo and hi; the reason set must match the bind's arithmetic.
- **Composite mutual exclusion (missing today).** CONTEXT states Evaluate-unfit and Recommend cannot both be scored in one episode — one hand-in, one
  `last_plan` — and no validator check enforces it, so the mill will eventually mint an unpassable composite. Add check and test in step 2.
- **Observations**: `reset` and `get_profile` return `last_verdict` / `last_reasons` so an agent can read back its hand-in.
- **Handbook symmetry**: assert every `REASON_CODES` token pattern and both verdict words appear in `react.py`'s prompt.
