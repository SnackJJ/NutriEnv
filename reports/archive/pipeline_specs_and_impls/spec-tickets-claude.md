# Claude (Opus) adjudication — tracer-bullet tickets (exam-generation pipeline + Evaluate verdict)

**Verdict: accept-with-nits — two nits are publish-blocking. HOLD.**

## 1. Verdict — accept-with-nits

The decomposition is sound: root parallelism (01/02), `05` before any mill-unfit, `07 ← 05,06`, and the splits of
verdict-envelope (01) from verdict-consumers (03) and Profile-fields (02) from Mifflin-derivation (04) match the spec's
implementation order 1–6. Wrong: one missing edge, one unowned family, one atomicity rule. Blocking: **E1** (handbook swap
unowned), **E2** (Composite unowned). Non-blocking: N1–N3.

## 2. Blocking edges

| Edge | Ruling |
|---|---|
| 01, 02 roots; parallel | keep |
| 03 ← 01 · 04 ← 02 · 05 ← 03,04 | keep |
| 07 ← 05, 06 | keep — this is the "do not mill-unfit before 5" line |
| 09 ← 06 (07 if unfit plates) | keep |
| **06 ← 02** | **change → 06 ← 02, 04** (E3) |
| **08 ← 06, 04** | keep the 04 edge; after E3 it is transitive via 06 |

**Must 08 wait on 04? Yes** — but that is not the interesting half. ADR 0017's Recommend world fill opens with "pick a roster
person (**windows already derived**)" and the spec says windows are derived, never sampled, in the world module — so *every*
mill ticket that fills a roster world needs 04. 08 has that edge; **06 does not, and 06 is the first ticket that fills one**:
its implementer must invent windows (violating the gram/window anchor discipline) or duplicate Mifflin. Two consistent fixes:

- **(a) preferred — 06 ← 02, 04**, with 06 owning roster world fill (sample person → derive windows via the world module →
  S0). 08's 04 edge is then transitive; keep or drop it, cosmetic.
- (b) scope 06 to expander contract + bind on the existing profile shape, no roster worlds — then 06 ← 02 stands, but a new
  ticket must own roster world fill. Do not leave it unowned: 07 and 08 will each build it.

## 3. Merge / split

No merges — 01/03 and 02/04 look mergeable and are not; each pair has its own "240 still Pass" checkpoint between them.

**Required addition — ticket 10, Composite.** None of the nine owns it, yet Composite is 36 published items with its own ADR
0017 contract (expander on the log step only; **two sub-oracles; recommend remainder computed after the log step**) plus
story 46's validator forbidding Evaluate-unfit paired with Recommend-substitute in one episode; 06 covers the log-step JSON
shape and nothing more. Add: *10 Composite episode — log-step remainder, two sub-oracles, forbidden-pair validator. Blocked
by: 07 and 08.*

**Optional split (not required):** 08 → 08a Rec templates + ledger-from-earlier-Logs, 08b Update templates + band scoring —
different seams (S0 ledger vs profile-patch oracle), identical blockers, so it buys clarity, not parallelism.

**Publish-blocking edits.** **E1** — 01 must carry the handbook swap: the spec puts it *in the same change as the envelope*
and story 41 says the moment verdict exists; no other ticket names the booklet, and CLAUDE.md discipline 4 is handbook
symmetry. Add to 01: delete the "empty items means reject a bad last_plan" line; add the accept/reject two-liner, Recommend
omit-verdict, and the meal-share line; stay in the ~575-token class. **E2** — add ticket 10 (Composite). **E3** — 06 ← 04,
taking option (a).

**Nits (fold into ticket bodies).** **N1** 03's title names Scorer/split/freezer; spec step 2 is
Oracle/split/freezer/scorer/**validator** — put `Oracle.last_verdict` (None → legacy scoring) and "reject oracles do not set
plan-must-fit / allow-empty-plan" in 03, or 05 inherits them silently. **N2** "swap" sits in both 05 and 07: 05 owns bind +
scoring (iso-caloric gold with **no** kcal code), 07 owns the knife generator — say which, or both agents build it. **N3** 09
needs a soft edge on 08 too; Stage B's leak scan is defined over Recommend speech (story 22).

## 4. One sentence

Publish with the listed edits — E1 into 01, E3 onto 06, E2 as a tenth Composite ticket — folding N1–N3 into ticket bodies.
