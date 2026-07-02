# Policies 1, 2, 3, 4, 5, 6 -- Pairwise Overhead Crossover (260511-kqo)

**Quick task:** 260511-kqo (extends 260511-k7l / 260511-jce)
**Comparison:** Policy 1 vs Policy 2 vs Policy 3 vs Policy 4 vs Policy 5 vs Policy 6
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T18:51:24+00:00
**Git SHA:** 2880f49

## Sim-core formula (unchanged from 260511-jce)

Migration carbon at decision hour: `(expected_migration_min / 60) * source_intensity_at_h` (HW-scaled iff `use_hw=True`).
Cooldown: `max(0, ceil((expected_migration_min - 60) / 60))` hours.
During cooldown, intensity accumulates on the target grid.

## Methodology

- Carbon values in this report are kgCO2eq (sim core internally tracks gCO2eq; converted at write time, 260525-ksw).
- Policies compared: Policy 1 vs Policy 2 vs Policy 3 vs Policy 4 vs Policy 5 vs Policy 6.
- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound overhead helpers (`ckpt_overhead`/`send_overhead`/`restore_overhead` in `heuristics.policy_heuristic`) scaled by `target_minutes / baseline_total_min`.
- **The `scaled_overhead` monkey-patch is a no-op for Policies 2 and 5.** Neither imports the overhead helpers; they only feel overhead via `cfg.expected_migration_min` (the sim core's minute-granular source-side carbon charge at the decision hour). The linked knob bites Policy 6 alone via its heuristic overhead estimator.
- Baseline total: `0.045` min (linear fit at 64 MB, anchor `BANC`).
- Grid: [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360]
- Samples: 24 2020 hourly starts per direction.
- Directions: ['BANC->CISO', 'CISO->BANC', 'AECI->PACE', 'PACE->AECI', 'AECI->TEPC', 'TEPC->AECI', 'EPE->AECI', 'AECI->EPE', 'EPE->PSCO', 'PSCO->EPE', 'PACE->PSCO', 'PSCO->PACE']
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=False, hw_weighting=False, policy_use_hw_override=None.


## BANC -> CISO

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 16.8 min (interpolated between 15 and 20 min).
- P1 vs P3: P1 beats P3 at overhead >= 17.5 min (interpolated between 15 and 20 min).
- P1 vs P4: P1 beats P4 at overhead >= 90.0 min (interpolated between 60 and 90 min).
- P1 vs P5: P1 beats P5 at overhead >= 20.4 min (interpolated between 20 and 30 min).
- P1 vs P6: P1 beats P6 at overhead >= 153.8 min (interpolated between 120 and 180 min).
- P2 vs P3: P3 beats P2 at overhead >= 16.7 min (interpolated between 15 and 20 min).
- P2 vs P4: P4 beats P2 at overhead >= 11.9 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 13.7 min (interpolated between 10 and 15 min).
- P3 vs P5: P3 beats P5 at overhead >= 21.6 min (interpolated between 20 and 30 min).
- P4 vs P5: P4 beats P5 at overhead >= 16.9 min (interpolated between 15 and 20 min).
- P4 vs P6: P4 beats P6 at overhead >= 153.8 min (interpolated between 120 and 180 min).
- P5 vs P6: P6 beats P5 at overhead >= 17.9 min (interpolated between 15 and 20 min).
- All other 3 pairs: no crossover in [0, 360] min (P2-vs-P5, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 8.2 | 7.8 | 8.1 | 8.1 | 7.7 | 8.1 | 0.00 | 4.21 | 0.96 | 0.50 | 4.12 | 0.33 |
| 5 | 8.2 | 8.0 | 8.2 | 8.1 | 7.9 | 8.2 | 0.00 | 4.29 | 1.12 | 0.33 | 4.17 | 0.25 |
| 10 | 8.2 | 8.1 | 8.2 | 8.1 | 8.0 | 8.2 | 0.00 | 4.29 | 1.12 | 0.29 | 4.21 | 0.25 |
| 15 | 8.2 | 8.2 | 8.2 | 8.1 | 8.1 | 8.2 | 0.00 | 4.33 | 1.12 | 0.21 | 4.25 | 0.25 |
| 20 | 8.2 | 8.4 | 8.3 | 8.1 | 8.2 | 8.2 | 0.00 | 4.38 | 1.12 | 0.21 | 4.29 | 0.21 |
| 30 | 8.2 | 8.6 | 8.3 | 8.1 | 8.4 | 8.2 | 0.00 | 4.46 | 1.25 | 0.21 | 4.29 | 0.17 |
| 45 | 8.2 | 9.0 | 8.4 | 8.2 | 8.8 | 8.2 | 0.00 | 4.50 | 1.25 | 0.21 | 4.42 | 0.17 |
| 60 | 8.2 | 9.4 | 8.5 | 8.2 | 9.2 | 8.2 | 0.00 | 4.58 | 1.38 | 0.21 | 4.50 | 0.17 |
| 90 | 8.2 | 10.5 | 8.7 | 8.2 | 10.0 | 8.2 | 0.00 | 4.88 | 1.21 | 0.00 | 4.62 | 0.12 |
| 120 | 8.2 | 11.5 | 8.9 | 8.2 | 11.1 | 8.2 | 0.00 | 5.00 | 1.25 | 0.00 | 4.96 | 0.12 |
| 180 | 8.2 | 14.0 | 9.4 | 8.2 | 13.4 | 8.3 | 0.00 | 5.62 | 1.25 | 0.00 | 5.42 | 0.12 |
| 240 | 8.2 | 17.1 | 9.5 | 8.2 | 16.3 | 8.3 | 0.00 | 6.21 | 1.12 | 0.00 | 6.04 | 0.04 |
| 360 | 8.2 | 25.7 | 10.2 | 8.2 | 24.9 | 8.3 | 0.00 | 7.79 | 1.17 | 0.00 | 7.83 | 0.04 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.21 | 7.79 | 3.58 |
| P3 (forecast-sum) | 0.96 | 1.38 | 0.42 |
| P4 (adaptive) | 0.00 | 0.50 | 0.50 |
| P5 (always-best-1h) | 4.12 | 7.83 | 3.71 |
| P6 (heuristic) | 0.04 | 0.33 | 0.29 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## CISO -> BANC

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 74.9 min (interpolated between 60 and 90 min).
- P1 vs P3: P1 beats P3 at overhead >= 217.3 min (interpolated between 180 and 240 min).
- P1 vs P4: P1 beats P4 at overhead >= 240.0 min (interpolated between 180 and 240 min).
- P1 vs P5: P1 beats P5 at overhead >= 79.0 min (interpolated between 60 and 90 min).
- P2 vs P3: P3 beats P2 at overhead >= 17.6 min (interpolated between 15 and 20 min).
- P2 vs P4: P4 beats P2 at overhead >= 15.8 min (interpolated between 15 and 20 min).
- P2 vs P6: P6 beats P2 at overhead >= 16.2 min (interpolated between 15 and 20 min).
- P3 vs P5: P3 beats P5 at overhead >= 23.3 min (interpolated between 20 and 30 min).
- P4 vs P5: P4 beats P5 at overhead >= 21.3 min (interpolated between 20 and 30 min).
- P4 vs P6: P4 beats P6 at overhead >= 6.8 min (interpolated between 5 and 10 min).
- P5 vs P6: P6 beats P5 at overhead >= 21.7 min (interpolated between 20 and 30 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P6, P2-vs-P5, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 10.2 | 7.8 | 8.1 | 8.1 | 7.7 | 8.1 | 0.00 | 4.62 | 1.62 | 1.25 | 4.62 | 1.08 |
| 5 | 10.2 | 8.0 | 8.3 | 8.3 | 7.9 | 8.3 | 0.00 | 4.71 | 1.62 | 1.08 | 4.67 | 1.00 |
| 10 | 10.2 | 8.1 | 8.3 | 8.3 | 8.0 | 8.3 | 0.00 | 4.71 | 1.62 | 1.04 | 4.67 | 1.00 |
| 15 | 10.2 | 8.3 | 8.4 | 8.3 | 8.2 | 8.3 | 0.00 | 4.71 | 1.62 | 1.04 | 4.75 | 1.00 |
| 20 | 10.2 | 8.4 | 8.4 | 8.4 | 8.3 | 8.4 | 0.00 | 4.75 | 1.62 | 1.04 | 4.79 | 0.96 |
| 30 | 10.2 | 8.8 | 8.5 | 8.4 | 8.6 | 8.4 | 0.00 | 4.88 | 1.62 | 1.04 | 4.88 | 0.92 |
| 45 | 10.2 | 9.2 | 8.6 | 8.5 | 9.1 | 8.5 | 0.00 | 5.00 | 1.79 | 1.00 | 4.96 | 0.92 |
| 60 | 10.2 | 9.7 | 8.7 | 8.6 | 9.5 | 8.5 | 0.00 | 5.04 | 1.79 | 0.88 | 5.04 | 0.92 |
| 90 | 10.2 | 10.8 | 9.0 | 8.9 | 10.6 | 8.7 | 0.00 | 5.21 | 1.54 | 0.83 | 5.42 | 0.88 |
| 120 | 10.2 | 12.0 | 9.2 | 9.1 | 11.8 | 8.8 | 0.00 | 5.58 | 1.54 | 0.50 | 5.71 | 0.88 |
| 180 | 10.2 | 14.9 | 9.8 | 9.8 | 14.5 | 9.1 | 0.00 | 6.29 | 1.67 | 0.21 | 6.33 | 0.88 |
| 240 | 10.2 | 18.4 | 10.4 | 10.2 | 17.8 | 9.4 | 0.00 | 7.00 | 1.71 | 0.00 | 7.00 | 0.83 |
| 360 | 10.2 | 28.0 | 12.0 | 10.2 | 26.9 | 10.0 | 0.00 | 8.71 | 1.96 | 0.00 | 8.62 | 0.75 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.62 | 8.71 | 4.08 |
| P3 (forecast-sum) | 1.54 | 1.96 | 0.42 |
| P4 (adaptive) | 0.00 | 1.25 | 1.25 |
| P5 (always-best-1h) | 4.62 | 8.62 | 4.00 |
| P6 (heuristic) | 0.75 | 1.08 | 0.33 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## AECI -> PACE

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 18.5 min (interpolated between 15 and 20 min).
- P1 vs P3: P1 beats P3 at overhead >= 23.1 min (interpolated between 20 and 30 min).
- P1 vs P4: P1 beats P4 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P1 vs P5: P1 beats P5 at overhead >= 19.2 min (interpolated between 15 and 20 min).
- P1 vs P6: P1 beats P6 at overhead >= 123.9 min (interpolated between 120 and 180 min).
- P2 vs P3: P3 beats P2 at overhead >= 16.2 min (interpolated between 15 and 20 min).
- P2 vs P4: P4 beats P2 at overhead >= 13.3 min (interpolated between 10 and 15 min).
- P2 vs P5: P2 beats P5 at overhead >= 108.6 min (interpolated between 90 and 120 min).
- P2 vs P6: P6 beats P2 at overhead >= 12.4 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 4.7 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 17.0 min (interpolated between 15 and 20 min).
- P3 vs P6: P6 beats P3 at overhead >= 0.1 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 14.0 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 41.0 min (interpolated between 30 and 45 min).
- P5 vs P6: P6 beats P5 at overhead >= 13.3 min (interpolated between 10 and 15 min).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 29.1 | 27.2 | 28.1 | 28.2 | 27.1 | 28.1 | 0.00 | 4.21 | 1.62 | 1.25 | 4.25 | 0.62 |
| 5 | 29.1 | 28.0 | 28.6 | 28.6 | 27.9 | 28.4 | 0.00 | 4.25 | 1.75 | 1.08 | 4.46 | 0.62 |
| 10 | 29.1 | 28.3 | 28.7 | 28.6 | 28.2 | 28.5 | 0.00 | 4.29 | 1.75 | 1.04 | 4.46 | 0.50 |
| 15 | 29.1 | 28.7 | 28.8 | 28.6 | 28.6 | 28.5 | 0.00 | 4.33 | 1.75 | 0.96 | 4.54 | 0.50 |
| 20 | 29.1 | 29.2 | 29.0 | 28.6 | 29.1 | 28.5 | 0.00 | 4.42 | 1.79 | 0.88 | 4.54 | 0.50 |
| 30 | 29.1 | 30.1 | 29.3 | 28.6 | 30.0 | 28.6 | 0.00 | 4.54 | 1.92 | 0.58 | 4.62 | 0.42 |
| 45 | 29.1 | 31.7 | 29.9 | 28.7 | 31.5 | 28.7 | 0.00 | 4.62 | 1.79 | 0.50 | 4.75 | 0.42 |
| 60 | 29.1 | 33.0 | 30.3 | 28.7 | 32.9 | 28.7 | 0.00 | 4.71 | 1.79 | 0.33 | 4.83 | 0.42 |
| 90 | 29.1 | 36.2 | 31.4 | 29.0 | 36.0 | 29.0 | 0.00 | 4.83 | 1.75 | 0.04 | 4.88 | 0.38 |
| 120 | 29.1 | 39.8 | 32.1 | 29.1 | 39.9 | 29.1 | 0.00 | 5.08 | 1.67 | 0.00 | 5.29 | 0.29 |
| 180 | 29.1 | 49.7 | 34.7 | 29.1 | 49.1 | 29.2 | 0.00 | 6.08 | 1.79 | 0.00 | 6.08 | 0.21 |
| 240 | 29.1 | 57.5 | 37.8 | 29.1 | 57.2 | 29.2 | 0.00 | 6.17 | 2.00 | 0.00 | 6.25 | 0.08 |
| 360 | 29.1 | 87.1 | 44.7 | 29.1 | 86.5 | 29.2 | 0.00 | 8.00 | 2.29 | 0.00 | 8.08 | 0.04 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.21 | 8.00 | 3.79 |
| P3 (forecast-sum) | 1.62 | 2.29 | 0.67 |
| P4 (adaptive) | 0.00 | 1.25 | 1.25 |
| P5 (always-best-1h) | 4.25 | 8.08 | 3.83 |
| P6 (heuristic) | 0.04 | 0.62 | 0.58 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## PACE -> AECI

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 27.5 min (interpolated between 20 and 30 min).
- P1 vs P3: P1 beats P3 at overhead >= 45.4 min (interpolated between 45 and 60 min).
- P1 vs P4: P1 beats P4 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P1 vs P5: P1 beats P5 at overhead >= 28.4 min (interpolated between 20 and 30 min).
- P1 vs P6: P1 beats P6 at overhead >= 320.3 min (interpolated between 240 and 360 min).
- P2 vs P3: P3 beats P2 at overhead >= 17.0 min (interpolated between 15 and 20 min).
- P2 vs P4: P4 beats P2 at overhead >= 15.2 min (interpolated between 15 and 20 min).
- P2 vs P5: P2 beats P5 at overhead >= 155.7 min (interpolated between 120 and 180 min).
- P2 vs P6: P6 beats P2 at overhead >= 13.4 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 11.2 min (interpolated between 10 and 15 min).
- P3 vs P5: P3 beats P5 at overhead >= 18.0 min (interpolated between 15 and 20 min).
- P3 vs P6: P6 beats P3 at overhead >= 0.3 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 15.7 min (interpolated between 15 and 20 min).
- P4 vs P6: P4 beats P6 at overhead >= 320.3 min (interpolated between 240 and 360 min).
- P5 vs P6: P6 beats P5 at overhead >= 14.3 min (interpolated between 10 and 15 min).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 30.1 | 27.3 | 28.1 | 28.2 | 27.2 | 28.1 | 0.00 | 4.38 | 1.88 | 1.50 | 4.42 | 0.83 |
| 5 | 30.1 | 28.1 | 28.7 | 28.8 | 28.0 | 28.6 | 0.00 | 4.42 | 1.92 | 1.33 | 4.62 | 0.83 |
| 10 | 30.1 | 28.4 | 28.8 | 28.8 | 28.3 | 28.7 | 0.00 | 4.46 | 1.92 | 1.29 | 4.67 | 0.71 |
| 15 | 30.1 | 28.8 | 29.0 | 28.8 | 28.8 | 28.7 | 0.00 | 4.50 | 1.96 | 1.21 | 4.67 | 0.71 |
| 20 | 30.1 | 29.4 | 29.1 | 28.8 | 29.3 | 28.7 | 0.00 | 4.62 | 2.04 | 1.04 | 4.75 | 0.71 |
| 30 | 30.1 | 30.3 | 29.5 | 28.8 | 30.2 | 28.8 | 0.00 | 4.71 | 1.96 | 0.79 | 4.79 | 0.62 |
| 45 | 30.1 | 31.9 | 30.1 | 29.0 | 31.9 | 28.9 | 0.00 | 4.79 | 1.92 | 0.62 | 4.96 | 0.46 |
| 60 | 30.1 | 33.4 | 30.4 | 29.0 | 33.1 | 29.0 | 0.00 | 4.96 | 1.92 | 0.42 | 4.96 | 0.46 |
| 90 | 30.1 | 37.0 | 31.9 | 29.4 | 36.9 | 29.3 | 0.00 | 5.17 | 1.96 | 0.25 | 5.29 | 0.42 |
| 120 | 30.1 | 40.5 | 32.7 | 29.6 | 40.4 | 29.4 | 0.00 | 5.38 | 1.88 | 0.17 | 5.46 | 0.33 |
| 180 | 30.1 | 50.1 | 34.7 | 30.1 | 50.3 | 29.7 | 0.00 | 6.17 | 1.79 | 0.00 | 6.38 | 0.25 |
| 240 | 30.1 | 58.4 | 37.0 | 30.1 | 57.4 | 29.9 | 0.00 | 6.33 | 1.83 | 0.00 | 6.29 | 0.21 |
| 360 | 30.1 | 87.1 | 43.2 | 30.1 | 85.8 | 30.2 | 0.00 | 8.00 | 2.08 | 0.00 | 8.00 | 0.17 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.38 | 8.00 | 3.62 |
| P3 (forecast-sum) | 1.79 | 2.08 | 0.29 |
| P4 (adaptive) | 0.00 | 1.50 | 1.50 |
| P5 (always-best-1h) | 4.42 | 8.00 | 3.58 |
| P6 (heuristic) | 0.17 | 0.83 | 0.67 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## AECI -> TEPC

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 15.5 min (interpolated between 15 and 20 min).
- P1 vs P3: P1 beats P3 at overhead >= 19.5 min (interpolated between 15 and 20 min).
- P1 vs P4: P1 beats P4 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P1 vs P5: P1 beats P5 at overhead >= 17.0 min (interpolated between 15 and 20 min).
- P1 vs P6: P1 beats P6 at overhead >= 318.9 min (interpolated between 240 and 360 min).
- P2 vs P3: P3 beats P2 at overhead >= 13.8 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 13.1 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 11.5 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 10.9 min (interpolated between 10 and 15 min).
- P3 vs P5: P3 beats P5 at overhead >= 15.7 min (interpolated between 15 and 20 min).
- P3 vs P6: P6 beats P3 at overhead >= 0.2 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 14.4 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 318.9 min (interpolated between 240 and 360 min).
- P5 vs P6: P6 beats P5 at overhead >= 12.6 min (interpolated between 10 and 15 min).
- All other 1 pairs: no crossover in [0, 360] min (P2-vs-P5).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 29.1 | 27.3 | 28.2 | 28.3 | 27.1 | 28.2 | 0.00 | 4.92 | 1.92 | 1.50 | 4.83 | 0.62 |
| 5 | 29.1 | 28.1 | 28.7 | 28.8 | 28.0 | 28.5 | 0.00 | 5.00 | 1.75 | 1.25 | 5.00 | 0.58 |
| 10 | 29.1 | 28.5 | 28.8 | 28.8 | 28.4 | 28.6 | 0.00 | 5.04 | 1.75 | 1.17 | 5.08 | 0.42 |
| 15 | 29.1 | 29.0 | 28.9 | 28.8 | 28.8 | 28.6 | 0.00 | 5.17 | 1.75 | 1.04 | 5.12 | 0.42 |
| 20 | 29.1 | 29.6 | 29.1 | 28.8 | 29.4 | 28.6 | 0.00 | 5.25 | 1.88 | 0.96 | 5.21 | 0.42 |
| 30 | 29.1 | 30.6 | 29.4 | 28.8 | 30.4 | 28.7 | 0.00 | 5.42 | 1.92 | 0.62 | 5.38 | 0.42 |
| 45 | 29.1 | 32.4 | 30.0 | 28.8 | 32.1 | 28.7 | 0.00 | 5.62 | 1.88 | 0.29 | 5.46 | 0.33 |
| 60 | 29.1 | 34.0 | 30.4 | 28.9 | 33.6 | 28.7 | 0.00 | 5.71 | 1.92 | 0.21 | 5.58 | 0.29 |
| 90 | 29.1 | 37.4 | 31.4 | 29.0 | 37.1 | 28.9 | 0.00 | 5.67 | 1.79 | 0.08 | 5.62 | 0.25 |
| 120 | 29.1 | 41.7 | 32.8 | 29.1 | 40.9 | 28.9 | 0.00 | 6.08 | 2.04 | 0.00 | 5.88 | 0.21 |
| 180 | 29.1 | 49.0 | 35.2 | 29.1 | 48.1 | 29.0 | 0.00 | 6.12 | 2.04 | 0.00 | 6.00 | 0.08 |
| 240 | 29.1 | 58.8 | 36.7 | 29.1 | 57.9 | 29.0 | 0.00 | 6.67 | 1.83 | 0.00 | 6.62 | 0.04 |
| 360 | 29.1 | 87.2 | 41.1 | 29.1 | 85.8 | 29.1 | 0.00 | 8.38 | 1.88 | 0.00 | 8.33 | 0.04 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.92 | 8.38 | 3.46 |
| P3 (forecast-sum) | 1.75 | 2.04 | 0.29 |
| P4 (adaptive) | 0.00 | 1.50 | 1.50 |
| P5 (always-best-1h) | 4.83 | 8.33 | 3.50 |
| P6 (heuristic) | 0.04 | 0.62 | 0.58 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## TEPC -> AECI

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 21.8 min (interpolated between 20 and 30 min).
- P1 vs P3: P1 beats P3 at overhead >= 43.2 min (interpolated between 30 and 45 min).
- P1 vs P4: P1 beats P4 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P1 vs P5: P1 beats P5 at overhead >= 23.6 min (interpolated between 20 and 30 min).
- P1 vs P6: P1 beats P6 at overhead >= 226.4 min (interpolated between 180 and 240 min).
- P2 vs P3: P3 beats P2 at overhead >= 14.7 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 14.1 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 12.1 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 10.5 min (interpolated between 10 and 15 min).
- P3 vs P5: P3 beats P5 at overhead >= 16.8 min (interpolated between 15 and 20 min).
- P4 vs P5: P4 beats P5 at overhead >= 15.8 min (interpolated between 15 and 20 min).
- P4 vs P6: P4 beats P6 at overhead >= 226.4 min (interpolated between 180 and 240 min).
- P5 vs P6: P6 beats P5 at overhead >= 14.1 min (interpolated between 10 and 15 min).
- All other 2 pairs: no crossover in [0, 360] min (P2-vs-P5, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 29.6 | 27.2 | 28.2 | 28.3 | 27.1 | 28.1 | 0.00 | 4.75 | 1.67 | 1.50 | 4.58 | 0.67 |
| 5 | 29.6 | 28.0 | 28.7 | 28.7 | 27.9 | 28.5 | 0.00 | 4.83 | 1.42 | 1.17 | 4.75 | 0.62 |
| 10 | 29.6 | 28.4 | 28.8 | 28.8 | 28.2 | 28.6 | 0.00 | 4.96 | 1.42 | 1.17 | 4.79 | 0.42 |
| 15 | 29.6 | 28.9 | 28.8 | 28.8 | 28.7 | 28.6 | 0.00 | 5.00 | 1.42 | 1.00 | 4.83 | 0.42 |
| 20 | 29.6 | 29.4 | 29.0 | 28.8 | 29.2 | 28.6 | 0.00 | 5.08 | 1.42 | 0.83 | 4.96 | 0.42 |
| 30 | 29.6 | 30.4 | 29.2 | 28.7 | 30.2 | 28.7 | 0.00 | 5.17 | 1.54 | 0.71 | 5.00 | 0.38 |
| 45 | 29.6 | 32.2 | 29.6 | 28.8 | 31.9 | 28.7 | 0.00 | 5.29 | 1.58 | 0.50 | 5.21 | 0.38 |
| 60 | 29.6 | 33.7 | 30.0 | 28.9 | 33.3 | 28.8 | 0.00 | 5.46 | 1.58 | 0.33 | 5.29 | 0.38 |
| 90 | 29.6 | 37.4 | 31.1 | 29.3 | 36.6 | 29.1 | 0.00 | 5.62 | 1.67 | 0.12 | 5.33 | 0.33 |
| 120 | 29.6 | 41.2 | 31.8 | 29.6 | 40.3 | 29.1 | 0.00 | 5.88 | 1.62 | 0.00 | 5.62 | 0.29 |
| 180 | 29.6 | 47.6 | 32.9 | 29.6 | 46.7 | 29.4 | 0.00 | 5.75 | 1.38 | 0.00 | 5.62 | 0.25 |
| 240 | 29.6 | 58.0 | 35.3 | 29.6 | 55.0 | 29.6 | 0.00 | 6.46 | 1.54 | 0.00 | 6.00 | 0.21 |
| 360 | 29.6 | 84.1 | 40.0 | 29.6 | 81.3 | 30.0 | 0.00 | 7.96 | 1.71 | 0.00 | 7.71 | 0.17 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.75 | 7.96 | 3.21 |
| P3 (forecast-sum) | 1.38 | 1.71 | 0.33 |
| P4 (adaptive) | 0.00 | 1.50 | 1.50 |
| P5 (always-best-1h) | 4.58 | 7.71 | 3.12 |
| P6 (heuristic) | 0.17 | 0.67 | 0.50 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## EPE -> AECI

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 5.3 min (interpolated between 5 and 10 min).
- P1 vs P3: P1 beats P3 at overhead >= 2.5 min (interpolated between 0 and 5 min).
- P1 vs P4: P1 beats P4 at overhead >= 3.6 min (interpolated between 0 and 5 min).
- P1 vs P5: P1 beats P5 at overhead >= 6.4 min (interpolated between 5 and 10 min).
- P1 vs P6: P1 beats P6 at overhead >= 64.2 min (interpolated between 60 and 90 min).
- P2 vs P3: P3 beats P2 at overhead >= 8.8 min (interpolated between 5 and 10 min).
- P2 vs P4: P4 beats P2 at overhead >= 6.2 min (interpolated between 5 and 10 min).
- P2 vs P6: P6 beats P2 at overhead >= 4.8 min (interpolated between 0 and 5 min).
- P3 vs P4: P4 beats P3 at overhead >= 1.5 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 10.4 min (interpolated between 10 and 15 min).
- P4 vs P5: P4 beats P5 at overhead >= 7.5 min (interpolated between 5 and 10 min).
- P4 vs P6: P4 beats P6 at overhead >= 64.2 min (interpolated between 60 and 90 min).
- P5 vs P6: P6 beats P5 at overhead >= 5.7 min (interpolated between 5 and 10 min).
- All other 2 pairs: no crossover in [0, 360] min (P2-vs-P5, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 26.6 | 25.8 | 26.4 | 26.4 | 25.8 | 26.4 | 0.00 | 4.00 | 1.00 | 0.75 | 3.92 | 0.25 |
| 5 | 26.6 | 26.5 | 26.7 | 26.6 | 26.5 | 26.5 | 0.00 | 4.04 | 1.04 | 0.62 | 4.08 | 0.25 |
| 10 | 26.6 | 26.9 | 26.8 | 26.6 | 26.8 | 26.5 | 0.00 | 4.08 | 1.04 | 0.62 | 4.12 | 0.25 |
| 15 | 26.6 | 27.1 | 26.8 | 26.6 | 27.1 | 26.5 | 0.00 | 4.12 | 1.04 | 0.46 | 4.21 | 0.25 |
| 20 | 26.6 | 27.7 | 26.9 | 26.6 | 27.6 | 26.5 | 0.00 | 4.25 | 1.04 | 0.33 | 4.21 | 0.21 |
| 30 | 26.6 | 28.4 | 27.0 | 26.6 | 28.2 | 26.5 | 0.00 | 4.33 | 1.04 | 0.17 | 4.25 | 0.21 |
| 45 | 26.6 | 29.7 | 27.4 | 26.6 | 29.6 | 26.5 | 0.00 | 4.42 | 1.08 | 0.08 | 4.46 | 0.17 |
| 60 | 26.6 | 31.1 | 27.6 | 26.6 | 30.9 | 26.6 | 0.00 | 4.62 | 1.08 | 0.00 | 4.58 | 0.12 |
| 90 | 26.6 | 34.1 | 28.5 | 26.6 | 33.9 | 26.6 | 0.00 | 4.79 | 1.25 | 0.00 | 4.79 | 0.08 |
| 120 | 26.6 | 37.1 | 29.1 | 26.6 | 36.5 | 26.6 | 0.00 | 4.96 | 1.21 | 0.00 | 4.79 | 0.04 |
| 180 | 26.6 | 43.3 | 30.5 | 26.6 | 42.4 | 26.6 | 0.00 | 5.17 | 1.25 | 0.00 | 5.00 | 0.00 |
| 240 | 26.6 | 50.0 | 31.8 | 26.6 | 48.9 | 26.6 | 0.00 | 5.33 | 1.21 | 0.00 | 5.21 | 0.00 |
| 360 | 26.6 | 67.1 | 35.8 | 26.6 | 65.4 | 26.6 | 0.00 | 6.04 | 1.42 | 0.00 | 5.88 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.00 | 6.04 | 2.04 |
| P3 (forecast-sum) | 1.00 | 1.42 | 0.42 |
| P4 (adaptive) | 0.00 | 0.75 | 0.75 |
| P5 (always-best-1h) | 3.92 | 5.88 | 1.96 |
| P6 (heuristic) | 0.00 | 0.25 | 0.25 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## AECI -> EPE

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 32.1 min (interpolated between 30 and 45 min).
- P1 vs P3: P1 beats P3 at overhead >= 79.4 min (interpolated between 60 and 90 min).
- P1 vs P4: P1 beats P4 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P1 vs P5: P1 beats P5 at overhead >= 33.4 min (interpolated between 30 and 45 min).
- P1 vs P6: P1 beats P6 at overhead >= 283.1 min (interpolated between 240 and 360 min).
- P2 vs P3: P3 beats P2 at overhead >= 11.4 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 11.4 min (interpolated between 10 and 15 min).
- P2 vs P5: P2 beats P5 at overhead >= 44.0 min (interpolated between 30 and 45 min).
- P2 vs P6: P6 beats P2 at overhead >= 10.4 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 11.5 min (interpolated between 10 and 15 min).
- P3 vs P5: P3 beats P5 at overhead >= 12.2 min (interpolated between 10 and 15 min).
- P4 vs P5: P4 beats P5 at overhead >= 12.2 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 283.1 min (interpolated between 240 and 360 min).
- P5 vs P6: P6 beats P5 at overhead >= 11.0 min (interpolated between 10 and 15 min).
- All other 1 pairs: no crossover in [0, 360] min (P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 29.1 | 25.9 | 26.4 | 26.5 | 25.8 | 26.4 | 0.00 | 4.50 | 1.67 | 1.33 | 4.50 | 0.92 |
| 5 | 29.1 | 26.7 | 27.0 | 27.1 | 26.6 | 27.0 | 0.00 | 4.58 | 1.50 | 1.21 | 4.67 | 0.83 |
| 10 | 29.1 | 27.0 | 27.1 | 27.1 | 26.9 | 27.0 | 0.00 | 4.58 | 1.50 | 1.21 | 4.75 | 0.83 |
| 15 | 29.1 | 27.5 | 27.2 | 27.2 | 27.4 | 27.0 | 0.00 | 4.75 | 1.50 | 1.12 | 4.79 | 0.83 |
| 20 | 29.1 | 27.9 | 27.3 | 27.2 | 27.7 | 27.1 | 0.00 | 4.88 | 1.50 | 1.00 | 4.79 | 0.79 |
| 30 | 29.1 | 28.8 | 27.5 | 27.2 | 28.7 | 27.2 | 0.00 | 4.88 | 1.50 | 0.88 | 4.79 | 0.71 |
| 45 | 29.1 | 30.4 | 27.9 | 27.4 | 30.4 | 27.3 | 0.00 | 5.00 | 1.54 | 0.62 | 5.21 | 0.71 |
| 60 | 29.1 | 31.8 | 28.2 | 27.7 | 31.8 | 27.4 | 0.00 | 5.21 | 1.54 | 0.38 | 5.33 | 0.71 |
| 90 | 29.1 | 35.3 | 29.6 | 28.1 | 35.0 | 27.9 | 0.00 | 5.38 | 1.75 | 0.29 | 5.33 | 0.71 |
| 120 | 29.1 | 38.6 | 30.6 | 28.7 | 38.0 | 28.0 | 0.00 | 5.58 | 1.88 | 0.17 | 5.42 | 0.58 |
| 180 | 29.1 | 45.8 | 33.4 | 29.1 | 45.3 | 28.5 | 0.00 | 5.83 | 2.04 | 0.00 | 5.79 | 0.38 |
| 240 | 29.1 | 53.9 | 35.8 | 29.1 | 52.9 | 28.9 | 0.00 | 6.17 | 2.08 | 0.00 | 6.04 | 0.38 |
| 360 | 29.1 | 73.4 | 41.6 | 29.1 | 73.0 | 29.4 | 0.00 | 6.92 | 2.25 | 0.00 | 6.96 | 0.25 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.50 | 6.92 | 2.42 |
| P3 (forecast-sum) | 1.50 | 2.25 | 0.75 |
| P4 (adaptive) | 0.00 | 1.33 | 1.33 |
| P5 (always-best-1h) | 4.50 | 6.96 | 2.46 |
| P6 (heuristic) | 0.25 | 0.92 | 0.67 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## EPE -> PSCO

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 27.3 min (interpolated between 20 and 30 min).
- P1 vs P3: P1 beats P3 at overhead >= 80.0 min (interpolated between 60 and 90 min).
- P1 vs P4: P1 beats P4 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P1 vs P5: P1 beats P5 at overhead >= 29.7 min (interpolated between 20 and 30 min).
- P1 vs P6: P1 beats P6 at overhead >= 250.7 min (interpolated between 240 and 360 min).
- P2 vs P3: P3 beats P2 at overhead >= 11.5 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 11.3 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 10.2 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 8.8 min (interpolated between 5 and 10 min).
- P3 vs P5: P3 beats P5 at overhead >= 12.8 min (interpolated between 10 and 15 min).
- P3 vs P6: P6 beats P3 at overhead >= 0.6 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 12.5 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 250.7 min (interpolated between 240 and 360 min).
- P5 vs P6: P6 beats P5 at overhead >= 11.3 min (interpolated between 10 and 15 min).
- All other 1 pairs: no crossover in [0, 360] min (P2-vs-P5).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 26.6 | 24.2 | 24.8 | 24.9 | 24.1 | 24.8 | 0.00 | 4.33 | 1.17 | 1.08 | 4.38 | 0.62 |
| 5 | 26.6 | 24.9 | 25.3 | 25.3 | 24.8 | 25.2 | 0.00 | 4.46 | 1.17 | 1.00 | 4.50 | 0.62 |
| 10 | 26.6 | 25.2 | 25.3 | 25.3 | 25.1 | 25.2 | 0.00 | 4.46 | 1.17 | 0.92 | 4.50 | 0.62 |
| 15 | 26.6 | 25.6 | 25.4 | 25.3 | 25.5 | 25.2 | 0.00 | 4.54 | 1.17 | 0.83 | 4.50 | 0.62 |
| 20 | 26.6 | 26.0 | 25.4 | 25.3 | 25.9 | 25.3 | 0.00 | 4.54 | 1.17 | 0.83 | 4.50 | 0.62 |
| 30 | 26.6 | 26.8 | 25.6 | 25.4 | 26.6 | 25.3 | 0.00 | 4.62 | 1.17 | 0.83 | 4.54 | 0.62 |
| 45 | 26.6 | 28.0 | 25.9 | 25.6 | 27.9 | 25.4 | 0.00 | 4.62 | 1.17 | 0.75 | 4.67 | 0.58 |
| 60 | 26.6 | 29.2 | 26.1 | 25.6 | 28.9 | 25.4 | 0.00 | 4.71 | 1.17 | 0.42 | 4.67 | 0.58 |
| 90 | 26.6 | 31.8 | 26.8 | 26.0 | 31.5 | 25.8 | 0.00 | 4.62 | 1.17 | 0.21 | 4.62 | 0.50 |
| 120 | 26.6 | 34.9 | 27.4 | 26.2 | 34.4 | 26.0 | 0.00 | 4.92 | 1.21 | 0.17 | 4.88 | 0.50 |
| 180 | 26.6 | 40.7 | 29.2 | 26.6 | 39.6 | 26.3 | 0.00 | 5.08 | 1.38 | 0.00 | 4.92 | 0.38 |
| 240 | 26.6 | 48.1 | 29.6 | 26.6 | 47.0 | 26.5 | 0.00 | 5.50 | 1.12 | 0.00 | 5.38 | 0.29 |
| 360 | 26.6 | 64.5 | 32.6 | 26.6 | 62.8 | 26.8 | 0.00 | 6.17 | 1.21 | 0.00 | 6.04 | 0.21 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.33 | 6.17 | 1.83 |
| P3 (forecast-sum) | 1.12 | 1.38 | 0.25 |
| P4 (adaptive) | 0.00 | 1.08 | 1.08 |
| P5 (always-best-1h) | 4.38 | 6.04 | 1.67 |
| P6 (heuristic) | 0.21 | 0.62 | 0.42 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## PSCO -> EPE

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 21.3 min (interpolated between 20 and 30 min).
- P1 vs P3: P1 beats P3 at overhead >= 64.9 min (interpolated between 60 and 90 min).
- P1 vs P4: P1 beats P4 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P1 vs P5: P1 beats P5 at overhead >= 22.9 min (interpolated between 20 and 30 min).
- P1 vs P6: P1 beats P6 at overhead >= 240.0 min (interpolated between 240 and 360 min).
- P2 vs P3: P3 beats P2 at overhead >= 12.0 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 11.7 min (interpolated between 10 and 15 min).
- P2 vs P5: P2 beats P5 at overhead >= 175.0 min (interpolated between 120 and 180 min).
- P2 vs P6: P6 beats P2 at overhead >= 9.9 min (interpolated between 5 and 10 min).
- P3 vs P4: P4 beats P3 at overhead >= 9.6 min (interpolated between 5 and 10 min).
- P3 vs P5: P3 beats P5 at overhead >= 13.5 min (interpolated between 10 and 15 min).
- P3 vs P6: P6 beats P3 at overhead >= 1.6 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 13.0 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 240.0 min (interpolated between 240 and 360 min).
- P5 vs P6: P6 beats P5 at overhead >= 11.2 min (interpolated between 10 and 15 min).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 25.9 | 24.2 | 24.8 | 24.9 | 24.1 | 24.9 | 0.00 | 4.00 | 0.92 | 1.08 | 4.12 | 0.38 |
| 5 | 25.9 | 24.9 | 25.2 | 25.3 | 24.8 | 25.1 | 0.00 | 4.12 | 0.96 | 1.00 | 4.25 | 0.38 |
| 10 | 25.9 | 25.1 | 25.2 | 25.2 | 25.0 | 25.1 | 0.00 | 4.12 | 0.96 | 0.92 | 4.25 | 0.38 |
| 15 | 25.9 | 25.5 | 25.3 | 25.2 | 25.4 | 25.1 | 0.00 | 4.21 | 0.96 | 0.83 | 4.25 | 0.38 |
| 20 | 25.9 | 25.9 | 25.3 | 25.2 | 25.7 | 25.1 | 0.00 | 4.21 | 0.96 | 0.75 | 4.25 | 0.38 |
| 30 | 25.9 | 26.5 | 25.5 | 25.3 | 26.4 | 25.2 | 0.00 | 4.21 | 0.96 | 0.67 | 4.29 | 0.38 |
| 45 | 25.9 | 27.8 | 25.7 | 25.4 | 27.6 | 25.2 | 0.00 | 4.29 | 0.92 | 0.46 | 4.29 | 0.38 |
| 60 | 25.9 | 28.7 | 25.8 | 25.3 | 28.6 | 25.2 | 0.00 | 4.29 | 0.92 | 0.25 | 4.38 | 0.33 |
| 90 | 25.9 | 31.0 | 26.7 | 25.6 | 31.0 | 25.5 | 0.00 | 4.17 | 1.08 | 0.12 | 4.29 | 0.29 |
| 120 | 25.9 | 33.7 | 27.3 | 25.9 | 33.5 | 25.6 | 0.00 | 4.38 | 1.17 | 0.00 | 4.46 | 0.29 |
| 180 | 25.9 | 39.0 | 28.4 | 25.9 | 39.0 | 25.7 | 0.00 | 4.54 | 1.12 | 0.00 | 4.67 | 0.21 |
| 240 | 25.9 | 46.3 | 29.6 | 25.9 | 45.4 | 25.9 | 0.00 | 5.08 | 1.12 | 0.00 | 5.00 | 0.21 |
| 360 | 25.9 | 60.1 | 32.5 | 25.9 | 59.2 | 26.2 | 0.00 | 5.50 | 1.21 | 0.00 | 5.50 | 0.17 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.00 | 5.50 | 1.50 |
| P3 (forecast-sum) | 0.92 | 1.21 | 0.29 |
| P4 (adaptive) | 0.00 | 1.08 | 1.08 |
| P5 (always-best-1h) | 4.12 | 5.50 | 1.38 |
| P6 (heuristic) | 0.17 | 0.38 | 0.21 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## PACE -> PSCO

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 50.9 min (interpolated between 45 and 60 min).
- P1 vs P3: P1 beats P3 at overhead >= 148.0 min (interpolated between 120 and 180 min).
- P1 vs P4: P1 beats P4 at overhead >= 240.0 min (interpolated between 180 and 240 min).
- P1 vs P5: P1 beats P5 at overhead >= 52.3 min (interpolated between 45 and 60 min).
- P2 vs P3: P3 beats P2 at overhead >= 11.8 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 12.7 min (interpolated between 10 and 15 min).
- P2 vs P5: P2 beats P5 at overhead >= 117.3 min (interpolated between 90 and 120 min).
- P2 vs P6: P6 beats P2 at overhead >= 10.9 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 18.0 min (interpolated between 15 and 20 min).
- P3 vs P5: P3 beats P5 at overhead >= 13.0 min (interpolated between 10 and 15 min).
- P4 vs P5: P4 beats P5 at overhead >= 14.0 min (interpolated between 10 and 15 min).
- P5 vs P6: P6 beats P5 at overhead >= 11.9 min (interpolated between 10 and 15 min).
- All other 3 pairs: no crossover in [0, 360] min (P1-vs-P6, P3-vs-P6, P4-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 30.1 | 25.3 | 25.8 | 26.0 | 25.2 | 25.8 | 0.00 | 4.50 | 1.42 | 1.67 | 4.54 | 1.08 |
| 5 | 30.1 | 26.0 | 26.4 | 26.6 | 25.9 | 26.4 | 0.00 | 4.54 | 1.46 | 1.33 | 4.62 | 1.00 |
| 10 | 30.1 | 26.3 | 26.5 | 26.6 | 26.3 | 26.4 | 0.00 | 4.54 | 1.46 | 1.33 | 4.62 | 1.00 |
| 15 | 30.1 | 26.8 | 26.5 | 26.6 | 26.7 | 26.4 | 0.00 | 4.62 | 1.46 | 1.25 | 4.67 | 1.00 |
| 20 | 30.1 | 27.2 | 26.6 | 26.6 | 27.0 | 26.5 | 0.00 | 4.62 | 1.46 | 1.12 | 4.67 | 1.00 |
| 30 | 30.1 | 28.1 | 26.8 | 26.7 | 28.0 | 26.6 | 0.00 | 4.67 | 1.46 | 1.04 | 4.75 | 1.00 |
| 45 | 30.1 | 29.6 | 27.2 | 26.9 | 29.5 | 26.8 | 0.00 | 4.83 | 1.46 | 0.88 | 4.96 | 0.92 |
| 60 | 30.1 | 30.8 | 27.5 | 27.2 | 30.7 | 26.9 | 0.00 | 4.92 | 1.46 | 0.83 | 5.00 | 0.92 |
| 90 | 30.1 | 34.0 | 28.4 | 28.3 | 33.7 | 27.6 | 0.00 | 5.04 | 1.38 | 0.67 | 5.04 | 0.88 |
| 120 | 30.1 | 36.7 | 29.0 | 28.4 | 36.8 | 27.8 | 0.00 | 5.08 | 1.42 | 0.38 | 5.25 | 0.75 |
| 180 | 30.1 | 44.4 | 31.3 | 29.5 | 44.2 | 28.5 | 0.00 | 5.58 | 1.62 | 0.08 | 5.67 | 0.67 |
| 240 | 30.1 | 53.0 | 33.4 | 30.1 | 52.8 | 29.2 | 0.00 | 6.04 | 1.71 | 0.00 | 6.12 | 0.62 |
| 360 | 30.1 | 73.4 | 40.3 | 30.1 | 72.6 | 30.1 | 0.00 | 6.92 | 2.08 | 0.00 | 6.96 | 0.46 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.50 | 6.92 | 2.42 |
| P3 (forecast-sum) | 1.38 | 2.08 | 0.71 |
| P4 (adaptive) | 0.00 | 1.67 | 1.67 |
| P5 (always-best-1h) | 4.54 | 6.96 | 2.42 |
| P6 (heuristic) | 0.46 | 1.08 | 0.62 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## PSCO -> PACE

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 7.9 min (interpolated between 5 and 10 min).
- P1 vs P3: P1 beats P3 at overhead >= 5.0 min (interpolated between 0 and 5 min).
- P1 vs P4: P1 beats P4 at overhead >= 0.6 min (interpolated between 0 and 5 min).
- P1 vs P5: P1 beats P5 at overhead >= 10.5 min (interpolated between 10 and 15 min).
- P1 vs P6: P1 beats P6 at overhead >= 76.7 min (interpolated between 60 and 90 min).
- P2 vs P3: P3 beats P2 at overhead >= 8.3 min (interpolated between 5 and 10 min).
- P2 vs P4: P4 beats P2 at overhead >= 9.3 min (interpolated between 5 and 10 min).
- P2 vs P6: P6 beats P2 at overhead >= 5.6 min (interpolated between 5 and 10 min).
- P3 vs P4: P4 beats P3 at overhead >= 13.3 min (interpolated between 10 and 15 min).
- P3 vs P5: P3 beats P5 at overhead >= 11.0 min (interpolated between 10 and 15 min).
- P4 vs P5: P4 beats P5 at overhead >= 11.4 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 39.5 min (interpolated between 30 and 45 min).
- P5 vs P6: P6 beats P5 at overhead >= 8.1 min (interpolated between 5 and 10 min).
- All other 2 pairs: no crossover in [0, 360] min (P2-vs-P5, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 25.9 | 25.2 | 25.7 | 25.9 | 25.1 | 25.7 | 0.00 | 3.83 | 0.58 | 0.92 | 3.71 | 0.25 |
| 5 | 25.9 | 25.8 | 25.9 | 26.1 | 25.7 | 25.8 | 0.00 | 3.88 | 0.62 | 0.58 | 3.79 | 0.25 |
| 10 | 25.9 | 26.0 | 26.0 | 26.0 | 25.9 | 25.8 | 0.00 | 3.88 | 0.62 | 0.50 | 3.79 | 0.25 |
| 15 | 25.9 | 26.4 | 26.0 | 26.0 | 26.2 | 25.8 | 0.00 | 3.96 | 0.62 | 0.42 | 3.79 | 0.25 |
| 20 | 25.9 | 26.8 | 26.0 | 25.9 | 26.6 | 25.8 | 0.00 | 3.96 | 0.62 | 0.29 | 3.83 | 0.25 |
| 30 | 25.9 | 27.4 | 26.1 | 25.9 | 27.2 | 25.8 | 0.00 | 4.00 | 0.62 | 0.21 | 3.88 | 0.25 |
| 45 | 25.9 | 28.8 | 26.3 | 25.9 | 28.5 | 25.9 | 0.00 | 4.17 | 0.62 | 0.12 | 4.08 | 0.17 |
| 60 | 25.9 | 29.9 | 26.4 | 25.9 | 29.6 | 25.9 | 0.00 | 4.25 | 0.62 | 0.12 | 4.17 | 0.17 |
| 90 | 25.9 | 32.3 | 26.7 | 25.9 | 32.0 | 26.0 | 0.00 | 4.21 | 0.62 | 0.00 | 4.21 | 0.08 |
| 120 | 25.9 | 35.3 | 27.0 | 25.9 | 34.7 | 26.0 | 0.00 | 4.50 | 0.62 | 0.00 | 4.38 | 0.08 |
| 180 | 25.9 | 41.1 | 28.2 | 25.9 | 40.4 | 25.9 | 0.00 | 4.67 | 0.75 | 0.00 | 4.62 | 0.00 |
| 240 | 25.9 | 48.9 | 29.1 | 25.9 | 47.8 | 25.9 | 0.00 | 5.17 | 0.79 | 0.00 | 5.08 | 0.00 |
| 360 | 25.9 | 64.6 | 32.9 | 25.9 | 64.1 | 25.9 | 0.00 | 5.71 | 1.12 | 0.00 | 5.79 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 3.83 | 5.71 | 1.87 |
| P3 (forecast-sum) | 0.58 | 1.12 | 0.54 |
| P4 (adaptive) | 0.00 | 0.92 | 0.92 |
| P5 (always-best-1h) | 3.71 | 5.79 | 2.08 |
| P6 (heuristic) | 0.00 | 0.25 | 0.25 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## Files

- `curves.csv` -- long-format per-run results (one row per (overhead, direction, policy, start_ts)); kgCO2eq columns (`total_carbon_kgco2eq`, `baseline_carbon_kgco2eq`) per 260525-ksw.
- `curves.png` -- two-subplot multi-policy line plot with pairwise crossover annotations where present.
