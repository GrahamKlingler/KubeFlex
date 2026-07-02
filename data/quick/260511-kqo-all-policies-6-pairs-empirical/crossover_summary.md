# Policies 6 -- Pairwise Overhead Crossover (260511-kqo)

**Quick task:** 260511-kqo (extends 260511-k7l / 260511-jce)
**Comparison:** Policy 6
**Policy legend:** P6=heuristic
**Generated:** 2026-05-25T22:27:24+00:00
**Git SHA:** 9fd523a

## Sim-core formula (unchanged from 260511-jce)

Migration carbon at decision hour: `(expected_migration_min / 60) * source_intensity_at_h` (HW-scaled iff `use_hw=True`).
Cooldown: `max(0, ceil((expected_migration_min - 60) / 60))` hours.
During cooldown, intensity accumulates on the target grid.

## Methodology

- Carbon values in this report are kgCO2eq (sim core internally tracks gCO2eq; converted at write time, 260525-ksw).
- Policies compared: Policy 6.
- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound overhead helpers (`ckpt_overhead`/`send_overhead`/`restore_overhead` in `heuristics.policy_heuristic`) scaled by `target_minutes / baseline_total_min`.
- **The `scaled_overhead` monkey-patch is a no-op for Policies 2 and 5.** Neither imports the overhead helpers; they only feel overhead via `cfg.expected_migration_min` (the sim core's minute-granular source-side carbon charge at the decision hour). The linked knob bites Policy 6 alone via its heuristic overhead estimator.
- Baseline total: `0.045` min (linear fit at 64 MB, anchor `BANC`).
- Grid: [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360]
- Samples: 24 2020 hourly starts per direction.
- Directions: ['BANC->CISO', 'CISO->BANC']
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.

## BANC -> CISO

**Pairwise crossover analysis:**


| overhead_min | P6 kgCO2eq | P6 mig_count |
| --- | --- | --- |
| 0 | 65.2 | 0.04 |
| 5 | 65.3 | 0.04 |
| 10 | 65.3 | 0.04 |
| 15 | 65.2 | 0.04 |
| 20 | 65.2 | 0.04 |
| 30 | 65.3 | 0.04 |
| 45 | 65.3 | 0.04 |
| 60 | 65.3 | 0.04 |
| 90 | 65.3 | 0.04 |
| 120 | 65.3 | 0.00 |
| 180 | 65.3 | 0.00 |
| 240 | 65.3 | 0.00 |
| 360 | 65.3 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P6 (heuristic) | 0.00 | 0.04 | 0.04 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## CISO -> BANC

**Pairwise crossover analysis:**


| overhead_min | P6 kgCO2eq | P6 mig_count |
| --- | --- | --- |
| 0 | 66.1 | 1.04 |
| 5 | 67.7 | 1.04 |
| 10 | 67.9 | 1.04 |
| 15 | 68.0 | 1.04 |
| 20 | 68.2 | 1.04 |
| 30 | 68.6 | 1.04 |
| 45 | 69.2 | 1.04 |
| 60 | 69.8 | 1.04 |
| 90 | 72.2 | 1.04 |
| 120 | 73.3 | 1.00 |
| 180 | 76.9 | 1.00 |
| 240 | 80.3 | 1.00 |
| 360 | 87.0 | 0.96 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P6 (heuristic) | 0.96 | 1.04 | 0.08 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## Files

- `curves.csv` -- long-format per-run results (one row per (overhead, direction, policy, start_ts)); kgCO2eq columns (`total_carbon_kgco2eq`, `baseline_carbon_kgco2eq`) per 260525-ksw.
- `curves.png` -- two-subplot multi-policy line plot with pairwise crossover annotations where present.
