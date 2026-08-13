# Sibling Python repo for Env and Bench

NutriEnv is the frozen ruler for harness and training work. It lives at `/home/jzq/Projects/nutri-env`, not inside NutriBuddy, and the runtime is Python.

TypeScript-inside-NutriBuddy would reuse the product kernel but force a Python wrapper for VERL `reset`/`step`. A mixed tree in one git repo blurs the freeze boundary. Product TS remains a future client; it is not this repo's hot path.

**Status**: accepted
