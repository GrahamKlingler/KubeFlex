# Policies 1, 2, 3, 4, 5, 6 -- All-HW-Grids Sweep (260511-kqo)

**Quick task:** 260511-kqo (Sweep B: dynamic source + 26-grid HW destinations)
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T19:11:13+00:00
**Git SHA:** 2880f49

## Methodology

- Carbon values in this report are kgCO2eq (sim core internally tracks gCO2eq; converted at write time, 260525-ksw).
- Destination candidate pool: all 6 HW-pool grids (from `data/hardware/hw_avg.csv`).
- Source grid per `start_ts`: dynamic — `argmin over HW_POOL_GRIDS of lookup_intensity(g, start_ts)` (HW-scaled iff `use_hw=True`). Computed ONCE per timestamp; all policies and overhead values share the same source per ts.
- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound overhead helpers scaled by `target_minutes / baseline_total_min`.
- Baseline total: `0.046` min (linear fit at 64 MB, anchor `PSCO`).
- Overhead grid: [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360]
- Samples: 1 sub-sampled 2020 hourly starts.
- Stdev reported is population stdev (`statistics.pstdev`).
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.


## Pairwise crossovers on aggregated curves

- P1 vs P2: P1 beats P2 at overhead >= 41.6 min (interpolated between 30 and 45 min).
- P1 vs P3: P1 beats P3 at overhead >= 131.4 min (interpolated between 120 and 180 min).
- P1 vs P4: P1 beats P4 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P1 vs P5: P1 beats P5 at overhead >= 43.9 min (interpolated between 30 and 45 min).
- P2 vs P3: P3 beats P2 at overhead >= 31.3 min (interpolated between 30 and 45 min).
- P2 vs P4: P4 beats P2 at overhead >= 10.0 min (interpolated between 5 and 10 min).
- P2 vs P6: P6 beats P2 at overhead >= 23.4 min (interpolated between 20 and 30 min).
- P3 vs P4: P3 beats P4 at overhead >= 100.1 min (interpolated between 90 and 120 min).
- P3 vs P5: P3 beats P5 at overhead >= 33.6 min (interpolated between 30 and 45 min).
- P4 vs P5: P4 beats P5 at overhead >= 15.8 min (interpolated between 15 and 20 min).
- P4 vs P6: P6 beats P4 at overhead >= 67.9 min (interpolated between 60 and 90 min).
- P5 vs P6: P6 beats P5 at overhead >= 28.0 min (interpolated between 20 and 30 min).
- All other 3 pairs: no crossover in [0, 360] min (P1-vs-P6, P2-vs-P5, P3-vs-P6).

## Per-overhead aggregates

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 155.8 | 118.7 | 136.1 | 125.1 | 116.8 | 132.1 | 0.00 | 8.00 | 2.00 | 2.00 | 8.00 | 1.00 |
| 5 | 155.8 | 122.7 | 138.5 | 126.9 | 120.7 | 134.3 | 0.00 | 8.00 | 2.00 | 2.00 | 8.00 | 1.00 |
| 10 | 155.8 | 126.7 | 138.9 | 126.7 | 124.6 | 134.4 | 0.00 | 8.00 | 2.00 | 2.00 | 8.00 | 1.00 |
| 15 | 155.8 | 128.6 | 139.2 | 126.9 | 126.3 | 134.5 | 0.00 | 8.00 | 2.00 | 2.00 | 8.00 | 1.00 |
| 20 | 155.8 | 132.7 | 139.6 | 127.3 | 130.3 | 134.7 | 0.00 | 8.00 | 2.00 | 2.00 | 8.00 | 1.00 |
| 30 | 155.8 | 138.8 | 140.4 | 127.3 | 136.0 | 134.9 | 0.00 | 8.00 | 2.00 | 2.00 | 8.00 | 1.00 |
| 45 | 155.8 | 160.8 | 143.7 | 130.9 | 157.4 | 135.3 | 0.00 | 11.00 | 2.00 | 2.00 | 11.00 | 1.00 |
| 60 | 155.8 | 172.3 | 144.8 | 133.5 | 168.5 | 135.7 | 0.00 | 11.00 | 2.00 | 2.00 | 11.00 | 1.00 |
| 90 | 155.8 | 192.4 | 147.2 | 145.1 | 188.6 | 138.7 | 0.00 | 10.00 | 2.00 | 1.00 | 10.00 | 1.00 |
| 120 | 155.8 | 223.7 | 151.7 | 155.8 | 218.8 | 139.5 | 0.00 | 11.00 | 2.00 | 0.00 | 11.00 | 1.00 |
| 180 | 155.8 | 267.5 | 173.5 | 155.8 | 259.4 | 143.3 | 0.00 | 11.00 | 3.00 | 0.00 | 11.00 | 1.00 |
| 240 | 155.8 | 398.0 | 186.6 | 155.8 | 382.4 | 147.1 | 0.00 | 16.00 | 3.00 | 0.00 | 16.00 | 1.00 |
| 360 | 155.8 | 412.4 | 264.0 | 155.8 | 399.8 | 154.9 | 0.00 | 11.00 | 5.00 | 0.00 | 11.00 | 1.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 8.00 | 16.00 | 8.00 |
| P3 (forecast-sum) | 2.00 | 5.00 | 3.00 |
| P4 (adaptive) | 0.00 | 2.00 | 2.00 |
| P5 (always-best-1h) | 8.00 | 16.00 | 8.00 |
| P6 (heuristic) | 1.00 | 1.00 | 0.00 |

## Destination diversity

For each policy, the set of unique destinations actually visited across all (overhead, start_ts) runs. A policy with high diversity is exploring more of the destination pool; low diversity may indicate the policy locks in a single attractor early.

| Policy | Distinct destinations | Top-5 (count) |
| --- | --- | --- |
| P1 (no-migration) | 0 | (none) |
| P2 (always-best) | 6 | ERCO(49), PSCO(45), PJM(13), PACE(13), SWPP(8) |
| P3 (forecast-sum) | 4 | ERCO(14), PJM(13), PSCO(3), SWPP(1) |
| P4 (adaptive) | 2 | PSCO(9), ERCO(8) |
| P5 (always-best-1h) | 6 | ERCO(49), PSCO(45), PJM(13), PACE(13), SWPP(8) |
| P6 (heuristic) | 1 | ERCO(13) |

Headline: distinct destinations per policy across the run set — P1=0, P2=6, P3=4, P4=2, P5=6, P6=1.

## Source diversity

Across the 1 timestamps, the dynamic argmin chose 1 distinct source grids.

| Source grid | Times chosen |
| --- | --- |
| SWPP | 1 |

## Files

- `curves.csv` -- per-run rows (overhead_min, start_ts, source_grid_chosen, policy, total_carbon_kgco2eq, migration_count, dest_grids_visited); kgCO2eq column per 260525-ksw.
- `aggregates.csv` -- per-(overhead, policy) means/stds across start_ts (mean/std columns: `mean_total_carbon_kgco2eq`, `std_total_carbon_kgco2eq`).
- `curves.png` -- single-panel mean-carbon-vs-overhead plot with one curve per policy (kgCO2eq y-axis).
