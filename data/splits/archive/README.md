# Archived splits

Frozen records of earlier exam generations (`v0.x`, `v2.x`). They are not the published ruler,
but active tests still load several of them — `tests/test_split.py` loads v2.3 / v2.5 / v2.6 /
v2.8, `tests/test_achievable.py` loads v2.3, `tests/test_validator_gates.py` loads v0.5 — so a
catalog that moves has to leave these loadable.

The `catalog` field in these files was updated **mechanically** when the live catalog was renamed
`data/fdc/catalog-v2.sqlite` → `data/fdc/catalog.sqlite` (the `-v2` suffix was dropped for the
public release, since v2 is the settled generation). Only the pointer changed: no task, oracle,
start state or window was touched, and the catalog bytes are identical under either name
(`sha256 57184b2b…`). These splits therefore resolve to exactly the world they always did.

If you are reading a report produced before that rename, its split still names the old path; the
file it means is the one now called `data/fdc/catalog.sqlite`.
