# Four families; Constrain is a situation; Composite pairs the four

A nutrition assistant meets four problems: Log, Evaluate, Recommend, Update. Those are the Families. “Is this okay / what instead?” was a construction trick, not a fifth user problem. ADR 0009’s 36 constrain slots and ADR 0013’s “only log then recommend” pair list are superseded.

**Status**: accepted

Constrain-as-family is retired. The same scorer knobs remain: Evaluate-unfit → empty `last_plan`; Recommend under limits → any safe plan (or empty if the windows are impossible). Query “shrimp okay, or what instead?” is Recommend with a named trap, because one hand-in has one `last_plan` and cannot be both empty and a substitute.

The published 240 is four single-family slices plus Composite, not five families and not 240+extra:

| slice | n |
|---|---|
| log | 48 |
| recommend | 72 |
| evaluate | 48 |
| update | 36 |
| composite (pairs from the four) | **36** |

Do not mint 36 dedicated constrain items. Do not shrink the four single-family quotas to grow Composite further: 36/240 is already a sixth of the exam, and those four numbers sample the skills Composite then combines. Situation floors sit **inside** evaluate / recommend (at least **8** Evaluate-unfit, **8** constrained Recommends: allergy trap or impossible windows). Remainder/leftover geometry stays a Recommend situation (ADR 0009’s 24 leftover recommends). The old constrain 36 become Composite, not extra hard singles.

Composite children are any of the four families. Pairs that share one end state work (log+recommend, log+evaluate, update+recommend, update+evaluate, log+update). Evaluate-unfit + Recommend-substitute does not: final `last_plan` cannot satisfy both.

ADR 0009’s sentence that rejected-plan shapes belong only in constrain is withdrawn; they belong in Evaluate (empty) or Recommend (instead / impossible).
