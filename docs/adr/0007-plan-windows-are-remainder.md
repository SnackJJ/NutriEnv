# Plan windows can differ from the profile the agent reads

A leftover-calorie recommend shows daily windows on the Profile (what `get_profile` returns) but Pass checks the submitted meal against the remainder after the ledger. `Oracle.plan_windows` is that remainder. Profile equality still uses `Oracle.profile`, so the agent cannot pass by shrinking the daily targets.

**Status**: accepted
