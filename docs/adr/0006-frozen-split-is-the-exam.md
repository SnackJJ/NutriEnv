# Frozen split is the exam; Generator is only a factory

The published ruler is a versioned JSON split (`data/splits/*.json`) plus the catalog snapshot. Humans author or curate items, then freeze them. A seed is not an exam: it cannot be reviewed, and a template bug ships as hundreds of bad questions.

Generator stays as an optional factory for tests and draft ideas. Reported Pass numbers must name a split file (and later a git tag). We still do not import NutriBench / NGQA / FoodBench items or their official metrics.

**Status**: accepted
