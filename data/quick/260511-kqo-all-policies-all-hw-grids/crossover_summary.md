# Policies 1, 2, 3, 4, 5, 6 -- All-HW-Grids Sweep (260511-kqo)

**Quick task:** 260511-kqo (Sweep B: dynamic source + 26-grid HW destinations)
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T18:50:22+00:00
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
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.


## Pairwise crossovers on aggregated curves

- P1 vs P2: P1 beats P2 at overhead >= 17.4 min (interpolated between 15 and 20 min).
- P1 vs P3: P1 beats P3 at overhead >= 32.4 min (interpolated between 30 and 45 min).
- P1 vs P4: P1 beats P4 at overhead >= 360.0 min (interpolated between 240 and 360 min).
- P1 vs P5: P1 beats P5 at overhead >= 20.2 min (interpolated between 20 and 30 min).
- P2 vs P3: P3 beats P2 at overhead >= 14.4 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 6.7 min (interpolated between 5 and 10 min).
- P2 vs P6: P6 beats P2 at overhead >= 5.8 min (interpolated between 5 and 10 min).
- P3 vs P5: P3 beats P5 at overhead >= 17.8 min (interpolated between 15 and 20 min).
- P4 vs P5: P4 beats P5 at overhead >= 9.0 min (interpolated between 5 and 10 min).
- P4 vs P6: P4 beats P6 at overhead >= 51.2 min (interpolated between 45 and 60 min).
- P5 vs P6: P6 beats P5 at overhead >= 8.2 min (interpolated between 5 and 10 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P6, P2-vs-P5, P3-vs-P4, P3-vs-P6).

## Per-overhead aggregates

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 39.6 | 36.0 | 38.2 | 37.4 | 35.6 | 37.2 | 0.00 | 5.58 | 1.25 | 0.62 | 5.62 | 0.21 |
| 5 | 39.6 | 37.2 | 38.9 | 37.6 | 36.8 | 37.4 | 0.00 | 5.62 | 1.12 | 0.46 | 5.79 | 0.21 |
| 10 | 39.6 | 38.3 | 39.0 | 37.5 | 37.7 | 37.4 | 0.00 | 5.75 | 1.12 | 0.29 | 5.88 | 0.21 |
| 15 | 39.6 | 39.2 | 39.1 | 37.5 | 38.6 | 37.4 | 0.00 | 5.83 | 1.12 | 0.21 | 6.00 | 0.21 |
| 20 | 39.6 | 40.1 | 39.2 | 37.6 | 39.6 | 37.4 | 0.00 | 5.92 | 1.17 | 0.21 | 6.08 | 0.17 |
| 30 | 39.6 | 42.3 | 39.5 | 37.6 | 41.7 | 37.5 | 0.00 | 6.25 | 1.17 | 0.21 | 6.38 | 0.17 |
| 45 | 39.6 | 45.9 | 40.4 | 37.5 | 45.0 | 37.5 | 0.00 | 6.58 | 1.29 | 0.17 | 6.67 | 0.17 |
| 60 | 39.6 | 49.5 | 40.7 | 37.5 | 48.4 | 37.5 | 0.00 | 6.88 | 1.29 | 0.17 | 6.92 | 0.17 |
| 90 | 39.6 | 57.2 | 42.1 | 37.8 | 56.2 | 37.7 | 0.00 | 7.00 | 1.29 | 0.12 | 7.12 | 0.17 |
| 120 | 39.6 | 69.4 | 42.9 | 38.0 | 67.3 | 37.8 | 0.00 | 8.17 | 1.25 | 0.12 | 8.21 | 0.17 |
| 180 | 39.6 | 88.0 | 48.2 | 38.4 | 85.9 | 38.0 | 0.00 | 8.33 | 1.67 | 0.04 | 8.46 | 0.12 |
| 240 | 39.6 | 107.7 | 51.8 | 38.6 | 105.9 | 38.2 | 0.00 | 8.42 | 1.62 | 0.04 | 8.62 | 0.12 |
| 360 | 39.6 | 144.9 | 57.9 | 39.6 | 140.9 | 38.6 | 0.00 | 8.50 | 1.62 | 0.00 | 8.58 | 0.12 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 5.58 | 8.50 | 2.92 |
| P3 (forecast-sum) | 1.12 | 1.67 | 0.54 |
| P4 (adaptive) | 0.00 | 0.62 | 0.62 |
| P5 (always-best-1h) | 5.62 | 8.62 | 3.00 |
| P6 (heuristic) | 0.12 | 0.21 | 0.08 |

## Destination diversity

For each policy, the set of unique destinations actually visited across all (overhead, start_ts) runs. A policy with high diversity is exploring more of the destination pool; low diversity may indicate the policy locks in a single attractor early.

| Policy | Distinct destinations | Top-5 (count) |
| --- | --- | --- |
| P1 (no-migration) | 0 | (none) |
| P2 (always-best) | 8 | PGE(888), ISNE(594), IPCO(279), BANC(276), NYIS(35) |
| P3 (forecast-sum) | 8 | PGE(192), BANC(52), ISNE(46), NYIS(44), IPCO(31) |
| P4 (adaptive) | 4 | PGE(37), ISNE(12), BANC(12), IPCO(3) |
| P5 (always-best-1h) | 8 | PGE(899), ISNE(607), IPCO(286), BANC(281), NYIS(35) |
| P6 (heuristic) | 2 | PGE(40), BANC(13) |

Headline: distinct destinations per policy across the run set — P1=0, P2=8, P3=8, P4=4, P5=8, P6=2.

## Source diversity

Across the 24 timestamps, the dynamic argmin chose 4 distinct source grids.

| Source grid | Times chosen |
| --- | --- |
| PGE | 14 |
| ISNE | 8 |
| BANC | 1 |
| IPCO | 1 |

## Files

- `curves.csv` -- per-run rows (overhead_min, start_ts, source_grid_chosen, policy, total_carbon_kgco2eq, migration_count, dest_grids_visited); kgCO2eq column per 260525-ksw.
- `aggregates.csv` -- per-(overhead, policy) means/stds across start_ts (mean/std columns: `mean_total_carbon_kgco2eq`, `std_total_carbon_kgco2eq`).
- `curves.png` -- single-panel mean-carbon-vs-overhead plot with one curve per policy (kgCO2eq y-axis).
