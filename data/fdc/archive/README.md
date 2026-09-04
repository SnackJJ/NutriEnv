# Archived catalogs

`catalog.sqlite` and `catalog-v1.sqlite` are pinned mill / v0.x fixtures, not
the published NutriEnv v1.0 world.

The v1.0 exam binds `data/fdc/catalog-v2.sqlite` (FNDDS-only). Realization
tables and v0.x splits still need the SR Legacy `tsp` / overlay keys that
catalog-v2 drops, so these files stay in the clone. Do not point
`EXAM_SPLIT_PATH` or a v1.0 eval at them.
