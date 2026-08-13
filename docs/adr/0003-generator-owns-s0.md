# Generator owns per-task S0; Env only loads it

Each Task needs its own Profile, Ledger gaps, and constraint tension. That variation is the Generator’s job (seed + knobs → S0, query, Oracle). Env is the same machine every time: load S0, step Actions, expose observations.

Pass on an update Task is Oracle match on the resulting patch/state, not “the agent emitted some profile-edit command.”

**Status**: accepted
