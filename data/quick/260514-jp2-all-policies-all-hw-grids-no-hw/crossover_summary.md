# Policies 1, 2, 3, 4, 5, 6 -- All-HW-Grids Sweep (260511-kqo)

**Quick task:** 260511-kqo (Sweep B: dynamic source + 26-grid HW destinations)
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T18:57:52+00:00
**Git SHA:** 2880f49

## Methodology

- Carbon values in this report are kgCO2eq (sim core internally tracks gCO2eq; converted at write time, 260525-ksw).
- Destination candidate pool: all 25 HW-pool grids (from `data/hardware/hw_avg.csv`).
- Source grid per `start_ts`: dynamic — `argmin over HW_POOL_GRIDS of lookup_intensity(g, start_ts)` (HW-scaled iff `use_hw=True`). Computed ONCE per timestamp; all policies and overhead values share the same source per ts.
- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound overhead helpers scaled by `target_minutes / baseline_total_min`.
- Baseline total: `0.045` min (linear fit at 64 MB, anchor `BANC`).
- Overhead grid: [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360]
- Samples: 24 sub-sampled 2020 hourly starts.
- Stdev reported is population stdev (`statistics.pstdev`).
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=False, hw_weighting=False, policy_use_hw_override=None.


## Pairwise crossovers on aggregated curves

- P1 vs P2: P1 beats P2 at overhead >= 13.7 min (interpolated between 10 and 15 min).
- P1 vs P3: P1 beats P3 at overhead >= 45.3 min (interpolated between 45 and 60 min).
- P1 vs P4: P1 beats P4 at overhead >= 360.0 min (interpolated between 240 and 360 min).
- P1 vs P5: P1 beats P5 at overhead >= 16.9 min (interpolated between 15 and 20 min).
- P2 vs P3: P3 beats P2 at overhead >= 7.1 min (interpolated between 5 and 10 min).
- P2 vs P4: P4 beats P2 at overhead >= 5.5 min (interpolated between 5 and 10 min).
- P2 vs P6: P6 beats P2 at overhead >= 5.4 min (interpolated between 5 and 10 min).
- P3 vs P4: P4 beats P3 at overhead >= 0.9 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 10.4 min (interpolated between 10 and 15 min).
- P3 vs P6: P6 beats P3 at overhead >= 1.3 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 8.4 min (interpolated between 5 and 10 min).
- P4 vs P6: P4 beats P6 at overhead >= 7.5 min (interpolated between 5 and 10 min).
- P5 vs P6: P6 beats P5 at overhead >= 8.5 min (interpolated between 5 and 10 min).
- All other 2 pairs: no crossover in [0, 360] min (P1-vs-P6, P2-vs-P5).

## Per-overhead aggregates

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 5.3 | 4.9 | 5.1 | 5.1 | 4.9 | 5.1 | 0.00 | 5.58 | 1.04 | 0.46 | 5.67 | 0.21 |
| 5 | 5.3 | 5.1 | 5.2 | 5.1 | 5.0 | 5.1 | 0.00 | 5.67 | 1.00 | 0.46 | 5.83 | 0.21 |
| 10 | 5.3 | 5.2 | 5.2 | 5.1 | 5.2 | 5.1 | 0.00 | 5.75 | 1.00 | 0.33 | 6.00 | 0.21 |
| 15 | 5.3 | 5.4 | 5.2 | 5.1 | 5.3 | 5.1 | 0.00 | 5.88 | 1.00 | 0.25 | 6.04 | 0.21 |
| 20 | 5.3 | 5.5 | 5.2 | 5.1 | 5.4 | 5.1 | 0.00 | 6.04 | 1.00 | 0.25 | 6.08 | 0.21 |
| 30 | 5.3 | 5.8 | 5.2 | 5.1 | 5.7 | 5.1 | 0.00 | 6.08 | 1.00 | 0.17 | 6.33 | 0.21 |
| 45 | 5.3 | 6.3 | 5.3 | 5.1 | 6.2 | 5.1 | 0.00 | 6.46 | 1.12 | 0.12 | 6.58 | 0.21 |
| 60 | 5.3 | 6.8 | 5.4 | 5.2 | 6.7 | 5.1 | 0.00 | 6.88 | 1.12 | 0.04 | 7.12 | 0.12 |
| 90 | 5.3 | 8.0 | 5.6 | 5.2 | 7.8 | 5.2 | 0.00 | 7.33 | 1.33 | 0.04 | 7.33 | 0.08 |
| 120 | 5.3 | 9.5 | 5.7 | 5.2 | 9.2 | 5.2 | 0.00 | 8.21 | 1.21 | 0.04 | 8.17 | 0.08 |
| 180 | 5.3 | 11.8 | 6.1 | 5.2 | 11.4 | 5.2 | 0.00 | 8.04 | 1.38 | 0.04 | 8.08 | 0.04 |
| 240 | 5.3 | 14.9 | 6.9 | 5.2 | 14.5 | 5.2 | 0.00 | 8.54 | 1.71 | 0.04 | 8.79 | 0.04 |
| 360 | 5.3 | 24.2 | 8.1 | 5.3 | 23.5 | 5.2 | 0.00 | 10.62 | 1.88 | 0.00 | 10.79 | 0.04 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 5.58 | 10.62 | 5.04 |
| P3 (forecast-sum) | 1.00 | 1.88 | 0.88 |
| P4 (adaptive) | 0.00 | 0.46 | 0.46 |
| P5 (always-best-1h) | 5.67 | 10.79 | 5.12 |
| P6 (heuristic) | 0.04 | 0.21 | 0.17 |

## Destination diversity

For each policy, the set of unique destinations actually visited across all (overhead, start_ts) runs. A policy with high diversity is exploring more of the destination pool; low diversity may indicate the policy locks in a single attractor early.

| Policy | Distinct destinations | Top-5 (count) |
| --- | --- | --- |
| P1 (no-migration) | 0 | (none) |
| P2 (always-best) | 10 | PGE(799), BANC(428), IPCO(262), ISNE(238), NYIS(191) |
| P3 (forecast-sum) | 8 | PGE(144), ISNE(54), NYIS(54), BANC(51), IPCO(31) |
| P4 (adaptive) | 5 | PGE(22), BANC(14), NYIS(8), ISNE(7), IPCO(3) |
| P5 (always-best-1h) | 10 | PGE(814), BANC(436), IPCO(269), ISNE(243), NYIS(196) |
| P6 (heuristic) | 4 | PGE(18), BANC(13), NYIS(7), ISNE(7) |

Headline: distinct destinations per policy across the run set — P1=0, P2=10, P3=8, P4=5, P5=10, P6=4.

## Source diversity

Across the 24 timestamps, the dynamic argmin chose 5 distinct source grids.

| Source grid | Times chosen |
| --- | --- |
| PGE | 19 |
| ISNE | 2 |
| BANC | 1 |
| IPCO | 1 |
| DUK | 1 |

## Files

- `curves.csv` -- per-run rows (overhead_min, start_ts, source_grid_chosen, policy, total_carbon_kgco2eq, migration_count, dest_grids_visited); kgCO2eq column per 260525-ksw.
- `aggregates.csv` -- per-(overhead, policy) means/stds across start_ts (mean/std columns: `mean_total_carbon_kgco2eq`, `std_total_carbon_kgco2eq`).
- `curves.png` -- single-panel mean-carbon-vs-overhead plot with one curve per policy (kgCO2eq y-axis).
