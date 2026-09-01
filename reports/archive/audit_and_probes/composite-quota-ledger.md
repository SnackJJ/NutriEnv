# Composite quota ledger (issue 11 / ADR 0013)

Two columns. They do not share a pot.

| Ledger | n | Where it lives | Frozen into an exam? |
|---|---|---|---|
| 基础 240 | 240 | ADR 0009 family allocation (log 48 / recommend 72 / evaluate 48 / update 36 / constrain 36). v0.5-gold holds this set. v1.0-gold is the 20-item single-family pilot, not a replacement of the 240. | Yes (v0.5). |
| 复合题额外配额 | **24** (+10%) | ADR 0013 proposal. Pipeline key `family_quotas.composite`. `Task.family` stays the primary family (`log`). | **No.** Pilot-20 stays single-family. |

`run_batch` writes `quota_ledger` on every freeze payload:

```
base_quota: 240
composite_extra_quota: 24
base_accepted: {family: count}     # items with no sub_oracles
composite_accepted: K              # items with sub_oracles
requested: {family: quota, composite: quota}
```

A composite item is **never** added to `base_accepted[log]`.

Sample freeze: `data/splits/v1.0-composite-sample.json` (version `v1.0-composite-sample`). It proves load_exam + scoring, it is not the 24-item extra exam.

| Sample field | Value |
|---|---|
| items | 2 |
| rejected | 0 |
| `Task.family` | `log` (primary) |
| sub-oracles | log + recommend |
| catalog | `data/fdc/catalog-v1.sqlite` (same sha as v1.0-gold) |
| `quota_ledger.base_accepted` | `{}` |
| `quota_ledger.composite_accepted` | 2 |

v1 pair: log → recommend only. Other pairs are scorer-legal but not generated.
