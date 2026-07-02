# Policies 1, 2, 3, 4, 5, 6 -- All-HW-Grids Sweep (260511-kqo)

**Quick task:** 260511-kqo (Sweep B: dynamic source + 26-grid HW destinations)
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T19:10:54+00:00
**Git SHA:** 2880f49

## Methodology

- Carbon values in this report are kgCO2eq (sim core internally tracks gCO2eq; converted at write time, 260525-ksw).
- Destination candidate pool: all 8 HW-pool grids (from `data/hardware/hw_avg.csv`).
- Source grid per `start_ts`: dynamic — `argmin over HW_POOL_GRIDS of lookup_intensity(g, start_ts)` (HW-scaled iff `use_hw=True`). Computed ONCE per timestamp; all policies and overhead values share the same source per ts.
- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound overhead helpers scaled by `target_minutes / baseline_total_min`.
- Baseline total: `0.043` min (linear fit at 64 MB, anchor `PNM`).
- Overhead grid: [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360]
- Samples: 1 sub-sampled 2020 hourly starts.
- Stdev reported is population stdev (`statistics.pstdev`).
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.


## Pairwise crossovers on aggregated curves

- P1 vs P2: P1 beats P2 at overhead >= 4.8 min (interpolated between 0 and 5 min).
- P1 vs P4: P4 beats P1 at overhead >= 45.0 min (interpolated between 30 and 45 min).
- P1 vs P5: P1 beats P5 at overhead >= 8.0 min (interpolated between 5 and 10 min).
- P1 vs P6: P1 beats P6 at overhead >= 60.0 min (interpolated between 45 and 60 min).
- P2 vs P3: P3 beats P2 at overhead >= 13.3 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 11.6 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 4.2 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 15.9 min (interpolated between 15 and 20 min).
- P4 vs P5: P4 beats P5 at overhead >= 14.3 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 60.0 min (interpolated between 45 and 60 min).
- P5 vs P6: P6 beats P5 at overhead >= 7.6 min (interpolated between 5 and 10 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P3, P2-vs-P5, P3-vs-P4, P3-vs-P6).

## Per-overhead aggregates

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 108.1 | 99.5 | 115.4 | 113.2 | 96.4 | 105.3 | 0.00 | 14.00 | 3.00 | 2.00 | 15.00 | 1.00 |
| 5 | 108.1 | 108.5 | 118.2 | 116.2 | 104.7 | 107.5 | 0.00 | 15.00 | 1.00 | 2.00 | 15.00 | 1.00 |
| 10 | 108.1 | 114.4 | 118.4 | 116.5 | 110.3 | 107.6 | 0.00 | 15.00 | 1.00 | 2.00 | 15.00 | 1.00 |
| 15 | 108.1 | 120.5 | 118.6 | 115.9 | 117.0 | 107.8 | 0.00 | 15.00 | 1.00 | 2.00 | 16.00 | 1.00 |
| 20 | 108.1 | 130.9 | 118.7 | 116.1 | 125.9 | 107.9 | 0.00 | 16.00 | 1.00 | 2.00 | 16.00 | 1.00 |
| 30 | 108.1 | 143.3 | 119.1 | 114.8 | 137.8 | 107.9 | 0.00 | 16.00 | 1.00 | 2.00 | 16.00 | 1.00 |
| 45 | 108.1 | 173.4 | 119.6 | 108.1 | 166.8 | 107.8 | 0.00 | 18.00 | 1.00 | 0.00 | 18.00 | 1.00 |
| 60 | 108.1 | 196.0 | 120.1 | 108.1 | 188.3 | 108.1 | 0.00 | 19.00 | 1.00 | 0.00 | 19.00 | 0.00 |
| 90 | 108.1 | 241.4 | 123.8 | 108.1 | 231.2 | 108.1 | 0.00 | 19.00 | 1.00 | 0.00 | 19.00 | 0.00 |
| 120 | 108.1 | 305.1 | 124.8 | 108.1 | 292.8 | 108.1 | 0.00 | 22.00 | 1.00 | 0.00 | 22.00 | 0.00 |
| 180 | 108.1 | 387.2 | 129.7 | 108.1 | 368.9 | 108.1 | 0.00 | 20.00 | 1.00 | 0.00 | 20.00 | 0.00 |
| 240 | 108.1 | 646.2 | 134.8 | 108.1 | 619.5 | 108.1 | 0.00 | 26.00 | 1.00 | 0.00 | 26.00 | 0.00 |
| 360 | 108.1 | 884.0 | 213.5 | 108.1 | 851.8 | 108.1 | 0.00 | 24.00 | 3.00 | 0.00 | 24.00 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 14.00 | 26.00 | 12.00 |
| P3 (forecast-sum) | 1.00 | 3.00 | 2.00 |
| P4 (adaptive) | 0.00 | 2.00 | 2.00 |
| P5 (always-best-1h) | 15.00 | 26.00 | 11.00 |
| P6 (heuristic) | 0.00 | 1.00 | 1.00 |

## Destination diversity

For each policy, the set of unique destinations actually visited across all (overhead, start_ts) runs. A policy with high diversity is exploring more of the destination pool; low diversity may indicate the policy locks in a single attractor early.

| Policy | Distinct destinations | Top-5 (count) |
| --- | --- | --- |
| P1 (no-migration) | 0 | (none) |
| P2 (always-best) | 7 | ERCO(78), IPCO(52), PNM(42), SWPP(27), NEVP(27) |
| P3 (forecast-sum) | 3 | PNM(14), IPCO(2), ERCO(1) |
| P4 (adaptive) | 2 | PNM(6), ERCO(6) |
| P5 (always-best-1h) | 7 | ERCO(79), IPCO(52), PNM(43), SWPP(27), NEVP(27) |
| P6 (heuristic) | 1 | PNM(7) |

Headline: distinct destinations per policy across the run set — P1=0, P2=7, P3=3, P4=2, P5=7, P6=1.

## Source diversity

Across the 1 timestamps, the dynamic argmin chose 1 distinct source grids.

| Source grid | Times chosen |
| --- | --- |
| ERCO | 1 |

## Files

- `curves.csv` -- per-run rows (overhead_min, start_ts, source_grid_chosen, policy, total_carbon_kgco2eq, migration_count, dest_grids_visited); kgCO2eq column per 260525-ksw.
- `aggregates.csv` -- per-(overhead, policy) means/stds across start_ts (mean/std columns: `mean_total_carbon_kgco2eq`, `std_total_carbon_kgco2eq`).
- `curves.png` -- single-panel mean-carbon-vs-overhead plot with one curve per policy (kgCO2eq y-axis).
