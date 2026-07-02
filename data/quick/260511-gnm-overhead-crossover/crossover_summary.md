# Policy 2 vs Policy 6 -- Overhead Crossover

**Quick task:** 260511-gnm
**Generated:** 2026-05-11T19:10:12+00:00
**Git SHA:** 97984a6

## Result

**Crossover:** none in swept range [0, 60] min. Policy 6 dominates throughout.

## Methodology

- Linked-knob sweep: `expected_migration_min` is set to each grid value AND Policy 6's internal overhead estimates (`ckpt_overhead`/`send_overhead`/`restore_overhead` as bound in `heuristics.policy_heuristic`) are scaled by `target_minutes / baseline_total_min`.
- Baseline total used for scaling: `0.048` min (linear fit at 64 MB, anchor grid `ISNE` used as both src and dst).
- Grid: [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
- Samples: 24 2020 hourly starts x source_grids=['ISNE'] (sub-sampled from Phase 4 `_main_sweep_timestamps`).
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.

## Per-overhead mean total carbon (gCO2eq)

| overhead_min | Policy 2 | Policy 6 | P2 - P6 |
| --- | --- | --- | --- |
| 0 | 1086.2 | 1086.2 | +0.0 |
| 5 | 1086.2 | 1086.2 | +0.0 |
| 10 | 1086.2 | 1086.2 | +0.0 |
| 15 | 1086.2 | 1086.2 | +0.0 |
| 20 | 1086.2 | 1086.2 | +0.0 |
| 25 | 1086.2 | 1086.2 | +0.0 |
| 30 | 1086.2 | 1086.2 | +0.0 |
| 35 | 1086.2 | 1086.2 | +0.0 |
| 40 | 1086.2 | 1086.2 | +0.0 |
| 45 | 1086.2 | 1086.2 | +0.0 |
| 50 | 1086.2 | 1086.2 | +0.0 |
| 55 | 1086.2 | 1086.2 | +0.0 |
| 60 | 1086.2 | 1086.2 | +0.0 |

## Files

- `curves.csv` -- long-format per-run results.
- `curves.png` -- Policy 2 vs Policy 6 line plot with crossover annotation.
