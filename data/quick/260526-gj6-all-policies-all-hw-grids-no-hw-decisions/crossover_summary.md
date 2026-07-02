# Policies 1, 2, 3, 4, 5, 6 -- All-HW-Grids Sweep (260511-kqo)

**Quick task:** 260511-kqo (Sweep B: dynamic source + 26-grid HW destinations)
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T19:10:14+00:00
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
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True, hw_weighting=False, policy_use_hw_override=False.
- **Regime:** HW-blind decisions, HW x CI accounting (`--no-hw-decisions`, 260526-gj6).

## Pairwise crossovers on aggregated curves

- P1 vs P2: P1 beats P2 at overhead >= 9.1 min (interpolated between 5 and 10 min).
- P1 vs P3: P1 beats P3 at overhead >= 32.4 min (interpolated between 30 and 45 min).
- P1 vs P4: P1 beats P4 at overhead >= 360.0 min (interpolated between 240 and 360 min).
- P1 vs P5: P1 beats P5 at overhead >= 11.9 min (interpolated between 10 and 15 min).
- P1 vs P6: P1 beats P6 at overhead >= 329.9 min (interpolated between 240 and 360 min).
- P2 vs P3: P3 beats P2 at overhead >= 5.7 min (interpolated between 5 and 10 min).
- P2 vs P4: P4 beats P2 at overhead >= 4.8 min (interpolated between 0 and 5 min).
- P2 vs P6: P6 beats P2 at overhead >= 4.8 min (interpolated between 0 and 5 min).
- P3 vs P4: P4 beats P3 at overhead >= 1.2 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 8.7 min (interpolated between 5 and 10 min).
- P3 vs P6: P6 beats P3 at overhead >= 1.5 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 7.7 min (interpolated between 5 and 10 min).
- P4 vs P6: P4 beats P6 at overhead >= 13.5 min (interpolated between 10 and 15 min).
- P5 vs P6: P6 beats P5 at overhead >= 7.5 min (interpolated between 5 and 10 min).
- All other 1 pairs: no crossover in [0, 360] min (P2-vs-P5).

## Per-overhead aggregates

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 39.6 | 37.4 | 38.2 | 38.3 | 36.9 | 38.3 | 0.00 | 5.83 | 1.25 | 0.62 | 5.83 | 0.42 |
| 5 | 39.6 | 38.8 | 38.9 | 38.7 | 38.2 | 38.7 | 0.00 | 5.92 | 1.12 | 0.62 | 6.00 | 0.42 |
| 10 | 39.6 | 39.8 | 39.0 | 38.8 | 39.2 | 38.7 | 0.00 | 6.00 | 1.12 | 0.50 | 6.17 | 0.42 |
| 15 | 39.6 | 40.8 | 39.1 | 38.7 | 40.2 | 38.8 | 0.00 | 6.12 | 1.12 | 0.42 | 6.21 | 0.42 |
| 20 | 39.6 | 42.0 | 39.2 | 38.8 | 41.2 | 38.8 | 0.00 | 6.29 | 1.17 | 0.42 | 6.25 | 0.42 |
| 30 | 39.6 | 44.3 | 39.5 | 38.8 | 43.5 | 38.8 | 0.00 | 6.42 | 1.17 | 0.42 | 6.50 | 0.42 |
| 45 | 39.6 | 48.3 | 40.4 | 38.3 | 47.1 | 38.9 | 0.00 | 6.79 | 1.29 | 0.33 | 6.75 | 0.42 |
| 60 | 39.6 | 52.5 | 40.7 | 38.0 | 51.4 | 38.7 | 0.00 | 7.17 | 1.29 | 0.29 | 7.33 | 0.33 |
| 90 | 39.6 | 62.1 | 42.1 | 37.7 | 59.9 | 38.7 | 0.00 | 7.54 | 1.29 | 0.17 | 7.42 | 0.29 |
| 120 | 39.6 | 73.9 | 42.9 | 37.8 | 70.8 | 38.8 | 0.00 | 8.50 | 1.25 | 0.17 | 8.29 | 0.29 |
| 180 | 39.6 | 93.5 | 48.2 | 38.2 | 90.0 | 39.0 | 0.00 | 8.38 | 1.67 | 0.12 | 8.38 | 0.25 |
| 240 | 39.6 | 118.4 | 51.8 | 38.3 | 114.2 | 39.5 | 0.00 | 8.83 | 1.62 | 0.04 | 8.96 | 0.25 |
| 360 | 39.6 | 191.6 | 57.9 | 39.6 | 186.8 | 39.7 | 0.00 | 10.83 | 1.62 | 0.00 | 11.04 | 0.21 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 5.83 | 10.83 | 5.00 |
| P3 (forecast-sum) | 1.12 | 1.67 | 0.54 |
| P4 (adaptive) | 0.00 | 0.62 | 0.62 |
| P5 (always-best-1h) | 5.83 | 11.04 | 5.21 |
| P6 (heuristic) | 0.21 | 0.42 | 0.21 |

## Destination diversity

For each policy, the set of unique destinations actually visited across all (overhead, start_ts) runs. A policy with high diversity is exploring more of the destination pool; low diversity may indicate the policy locks in a single attractor early.

| Policy | Distinct destinations | Top-5 (count) |
| --- | --- | --- |
| P1 (no-migration) | 0 | (none) |
| P2 (always-best) | 10 | PGE(869), BANC(429), IPCO(263), ISNE(234), NYIS(193) |
| P3 (forecast-sum) | 8 | PGE(192), BANC(52), ISNE(46), NYIS(44), IPCO(31) |
| P4 (adaptive) | 6 | PGE(66), BANC(14), NYIS(8), DUK(6), IPCO(3) |
| P5 (always-best-1h) | 10 | PGE(854), BANC(439), IPCO(270), ISNE(238), NYIS(198) |
| P6 (heuristic) | 4 | PGE(82), BANC(13), NYIS(7), ISNE(7) |

Headline: distinct destinations per policy across the run set — P1=0, P2=10, P3=8, P4=6, P5=10, P6=4.

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
