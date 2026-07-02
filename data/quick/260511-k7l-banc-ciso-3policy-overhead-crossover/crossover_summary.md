# Policies 2, 5, 6 -- Pairwise Overhead Crossover (260511-kqo)

**Quick task:** 260511-kqo (extends 260511-k7l / 260511-jce)
**Comparison:** Policy 2 vs Policy 5 vs Policy 6
**Policy legend:** P2=always-best, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T18:48:28+00:00
**Git SHA:** 2880f49

## Sim-core formula (unchanged from 260511-jce)

Migration carbon at decision hour: `(expected_migration_min / 60) * source_intensity_at_h` (HW-scaled iff `use_hw=True`).
Cooldown: `max(0, ceil((expected_migration_min - 60) / 60))` hours.
During cooldown, intensity accumulates on the target grid.

## Methodology

- Carbon values in this report are kgCO2eq (sim core internally tracks gCO2eq; converted at write time, 260525-ksw).
- Policies compared: Policy 2 vs Policy 5 vs Policy 6.
- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound overhead helpers (`ckpt_overhead`/`send_overhead`/`restore_overhead` in `heuristics.policy_heuristic`) scaled by `target_minutes / baseline_total_min`.
- **The `scaled_overhead` monkey-patch is a no-op for Policies 2 and 5.** Neither imports the overhead helpers; they only feel overhead via `cfg.expected_migration_min` (the sim core's minute-granular source-side carbon charge at the decision hour). The linked knob bites Policy 6 alone via its heuristic overhead estimator.
- Baseline total: `0.045` min (linear fit at 64 MB, anchor `BANC`).
- Grid: [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360]
- Samples: 24 2020 hourly starts per direction.
- Directions: ['BANC->CISO', 'CISO->BANC']
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.


## BANC -> CISO

**Pairwise crossover analysis:**

- P2 vs P5: no crossover in swept range [0, 360] min.
- P2 vs P6: P6 beats P2 at overhead >= 3.1 min (interpolated between 0 and 5 min).
- P5 vs P6: P6 beats P5 at overhead >= 4.6 min (interpolated between 0 and 5 min).

| overhead_min | P2 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P2 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 64.6 | 64.3 | 65.2 | 2.21 | 2.17 | 0.04 |
| 5 | 65.6 | 65.3 | 65.3 | 2.25 | 2.21 | 0.04 |
| 10 | 65.9 | 65.6 | 65.3 | 2.25 | 2.21 | 0.04 |
| 15 | 66.4 | 66.0 | 65.3 | 2.29 | 2.21 | 0.04 |
| 20 | 67.1 | 66.7 | 65.3 | 2.29 | 2.21 | 0.04 |
| 30 | 67.9 | 67.5 | 65.2 | 2.29 | 2.29 | 0.04 |
| 45 | 69.8 | 69.1 | 65.3 | 2.38 | 2.29 | 0.04 |
| 60 | 71.4 | 71.0 | 65.3 | 2.38 | 2.42 | 0.04 |
| 90 | 75.1 | 74.1 | 65.3 | 2.42 | 2.38 | 0.04 |
| 120 | 78.8 | 77.6 | 65.3 | 2.46 | 2.42 | 0.00 |
| 180 | 88.4 | 86.3 | 65.3 | 2.71 | 2.62 | 0.00 |
| 240 | 99.2 | 97.3 | 65.3 | 2.92 | 2.92 | 0.00 |
| 360 | 131.4 | 128.0 | 65.3 | 3.58 | 3.54 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P2 (always-best) | 2.21 | 3.58 | 1.38 |
| P5 (always-best-1h) | 2.17 | 3.54 | 1.38 |
| P6 (heuristic) | 0.00 | 0.04 | 0.04 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## CISO -> BANC

**Pairwise crossover analysis:**

- P2 vs P5: no crossover in swept range [0, 360] min.
- P2 vs P6: P6 beats P2 at overhead >= 10.3 min (interpolated between 10 and 15 min).
- P5 vs P6: P6 beats P5 at overhead >= 13.0 min (interpolated between 10 and 15 min).

| overhead_min | P2 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P2 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 65.5 | 65.2 | 66.1 | 3.04 | 3.00 | 1.04 |
| 5 | 67.3 | 67.0 | 67.7 | 3.08 | 3.04 | 1.04 |
| 10 | 67.8 | 67.4 | 67.9 | 3.08 | 3.04 | 1.04 |
| 15 | 68.7 | 68.4 | 68.0 | 3.08 | 3.04 | 1.04 |
| 20 | 69.3 | 68.8 | 68.2 | 3.12 | 3.04 | 1.04 |
| 30 | 71.1 | 70.4 | 68.6 | 3.17 | 3.08 | 1.04 |
| 45 | 73.5 | 73.1 | 69.2 | 3.21 | 3.25 | 1.04 |
| 60 | 76.0 | 75.0 | 69.8 | 3.33 | 3.25 | 1.04 |
| 90 | 81.7 | 80.5 | 72.2 | 3.29 | 3.25 | 1.04 |
| 120 | 87.1 | 86.4 | 73.3 | 3.42 | 3.54 | 1.00 |
| 180 | 99.9 | 97.3 | 76.9 | 3.62 | 3.54 | 1.00 |
| 240 | 114.7 | 111.6 | 80.4 | 3.83 | 3.79 | 1.00 |
| 360 | 152.1 | 150.9 | 87.0 | 4.46 | 4.58 | 0.96 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P2 (always-best) | 3.04 | 4.46 | 1.42 |
| P5 (always-best-1h) | 3.00 | 4.58 | 1.58 |
| P6 (heuristic) | 0.96 | 1.04 | 0.08 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## Files

- `curves.csv` -- long-format per-run results (one row per (overhead, direction, policy, start_ts)); kgCO2eq columns (`total_carbon_kgco2eq`, `baseline_carbon_kgco2eq`) per 260525-ksw.
- `curves.png` -- two-subplot multi-policy line plot with pairwise crossover annotations where present.
