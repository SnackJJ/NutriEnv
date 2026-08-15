# The world catalog is a frozen USDA FoodData Central snapshot

The Env food table is official FDC data ingested once into `data/fdc/catalog.sqlite`. Runtime never calls the USDA API. The default snapshot is FNDDS + SR Legacy (~13k foods). Branded is optional (`scripts/build_fdc_catalog.py --branded`): about 1.8M rows / 2GB, so it stays a local rebuild, not the committed default. Search is SQLite FTS5 BM25, capped at 25; the opening observation publishes `catalog_size` only.

Staple slugs (`milk_whole`, …) remain aliases so existing Tasks can name foods the old way. Canonical `food_id` is the FDC id.

Allergen tags are not an FDC field; they are a local overlay inferred from the official description.

**Status**: accepted
