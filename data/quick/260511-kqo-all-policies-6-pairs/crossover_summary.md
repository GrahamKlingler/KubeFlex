# Policies 1, 2, 3, 4, 5, 6 -- Pairwise Overhead Crossover (260511-kqo)

**Quick task:** 260511-kqo (extends 260511-k7l / 260511-jce)
**Comparison:** Policy 1 vs Policy 2 vs Policy 3 vs Policy 4 vs Policy 5 vs Policy 6
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T18:49:14+00:00
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
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.


## BANC -> CISO

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 3.3 min (interpolated between 0 and 5 min).
- P1 vs P5: P1 beats P5 at overhead >= 4.7 min (interpolated between 0 and 5 min).
- P1 vs P6: P1 beats P6 at overhead >= 63.7 min (interpolated between 60 and 90 min).
- P2 vs P3: P3 beats P2 at overhead >= 63.7 min (interpolated between 60 and 90 min).
- P2 vs P4: P4 beats P2 at overhead >= 3.3 min (interpolated between 0 and 5 min).
- P2 vs P6: P6 beats P2 at overhead >= 3.1 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 70.8 min (interpolated between 60 and 90 min).
- P4 vs P5: P4 beats P5 at overhead >= 4.7 min (interpolated between 0 and 5 min).
- P4 vs P6: P4 beats P6 at overhead >= 63.7 min (interpolated between 60 and 90 min).
- P5 vs P6: P6 beats P5 at overhead >= 4.6 min (interpolated between 0 and 5 min).
- All other 5 pairs: no crossover in [0, 360] min (P1-vs-P3, P1-vs-P4, P2-vs-P5, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 65.3 | 64.6 | 67.8 | 65.3 | 64.3 | 65.2 | 0.00 | 2.21 | 0.96 | 0.00 | 2.17 | 0.04 |
| 5 | 65.3 | 65.6 | 68.6 | 65.3 | 65.3 | 65.3 | 0.00 | 2.25 | 1.12 | 0.00 | 2.21 | 0.04 |
| 10 | 65.3 | 65.9 | 68.8 | 65.3 | 65.6 | 65.3 | 0.00 | 2.25 | 1.12 | 0.00 | 2.21 | 0.04 |
| 15 | 65.3 | 66.4 | 68.9 | 65.3 | 66.0 | 65.3 | 0.00 | 2.29 | 1.12 | 0.00 | 2.21 | 0.04 |
| 20 | 65.3 | 67.1 | 69.1 | 65.3 | 66.7 | 65.3 | 0.00 | 2.29 | 1.12 | 0.00 | 2.21 | 0.04 |
| 30 | 65.3 | 67.9 | 69.7 | 65.3 | 67.5 | 65.2 | 0.00 | 2.29 | 1.25 | 0.00 | 2.29 | 0.04 |
| 45 | 65.3 | 69.8 | 70.5 | 65.3 | 69.1 | 65.3 | 0.00 | 2.38 | 1.25 | 0.00 | 2.29 | 0.04 |
| 60 | 65.3 | 71.4 | 71.7 | 65.3 | 71.0 | 65.3 | 0.00 | 2.38 | 1.38 | 0.00 | 2.42 | 0.04 |
| 90 | 65.3 | 75.1 | 72.9 | 65.3 | 74.1 | 65.3 | 0.00 | 2.42 | 1.21 | 0.00 | 2.38 | 0.04 |
| 120 | 65.3 | 78.8 | 74.8 | 65.3 | 77.6 | 65.3 | 0.00 | 2.46 | 1.25 | 0.00 | 2.42 | 0.00 |
| 180 | 65.3 | 88.4 | 79.2 | 65.3 | 86.3 | 65.3 | 0.00 | 2.71 | 1.25 | 0.00 | 2.62 | 0.00 |
| 240 | 65.3 | 99.2 | 80.4 | 65.3 | 97.3 | 65.3 | 0.00 | 2.92 | 1.12 | 0.00 | 2.92 | 0.00 |
| 360 | 65.3 | 131.4 | 86.9 | 65.3 | 128.0 | 65.3 | 0.00 | 3.58 | 1.17 | 0.00 | 3.54 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 2.21 | 3.58 | 1.38 |
| P3 (forecast-sum) | 0.96 | 1.38 | 0.42 |
| P4 (adaptive) | 0.00 | 0.00 | 0.00 |
| P5 (always-best-1h) | 2.17 | 3.54 | 1.38 |
| P6 (heuristic) | 0.00 | 0.04 | 0.04 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## CISO -> BANC

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 210.0 min (interpolated between 180 and 240 min).
- P1 vs P4: P1 beats P4 at overhead >= 360.0 min (interpolated between 240 and 360 min).
- P1 vs P5: P1 beats P5 at overhead >= 221.9 min (interpolated between 180 and 240 min).
- P2 vs P3: P3 beats P2 at overhead >= 34.6 min (interpolated between 30 and 45 min).
- P2 vs P4: P4 beats P2 at overhead >= 10.6 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 10.3 min (interpolated between 10 and 15 min).
- P3 vs P4: P3 beats P4 at overhead >= 197.1 min (interpolated between 180 and 240 min).
- P3 vs P5: P3 beats P5 at overhead >= 41.1 min (interpolated between 30 and 45 min).
- P4 vs P5: P4 beats P5 at overhead >= 13.2 min (interpolated between 10 and 15 min).
- P5 vs P6: P6 beats P5 at overhead >= 13.0 min (interpolated between 10 and 15 min).
- All other 5 pairs: no crossover in [0, 360] min (P1-vs-P3, P1-vs-P6, P2-vs-P5, P3-vs-P6, P4-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 107.3 | 65.5 | 68.7 | 66.2 | 65.2 | 66.1 | 0.00 | 3.04 | 1.62 | 1.00 | 3.00 | 1.04 |
| 5 | 107.3 | 67.3 | 70.0 | 67.7 | 67.0 | 67.7 | 0.00 | 3.08 | 1.62 | 1.00 | 3.04 | 1.04 |
| 10 | 107.3 | 67.8 | 70.2 | 67.9 | 67.4 | 67.9 | 0.00 | 3.08 | 1.62 | 1.00 | 3.04 | 1.04 |
| 15 | 107.3 | 68.7 | 70.5 | 68.1 | 68.4 | 68.0 | 0.00 | 3.08 | 1.62 | 1.00 | 3.04 | 1.04 |
| 20 | 107.3 | 69.3 | 70.7 | 68.3 | 68.8 | 68.2 | 0.00 | 3.12 | 1.62 | 1.00 | 3.04 | 1.04 |
| 30 | 107.3 | 71.1 | 71.4 | 68.6 | 70.4 | 68.6 | 0.00 | 3.17 | 1.62 | 1.00 | 3.08 | 1.04 |
| 45 | 107.3 | 73.5 | 72.8 | 69.2 | 73.1 | 69.2 | 0.00 | 3.21 | 1.79 | 1.00 | 3.25 | 1.04 |
| 60 | 107.3 | 76.0 | 73.7 | 70.3 | 75.0 | 69.8 | 0.00 | 3.33 | 1.79 | 0.96 | 3.25 | 1.04 |
| 90 | 107.3 | 81.7 | 75.8 | 72.6 | 80.5 | 72.2 | 0.00 | 3.29 | 1.54 | 0.96 | 3.25 | 1.04 |
| 120 | 107.3 | 87.1 | 77.7 | 74.0 | 86.4 | 73.3 | 0.00 | 3.42 | 1.54 | 0.96 | 3.54 | 1.00 |
| 180 | 107.3 | 99.9 | 84.2 | 80.3 | 97.3 | 76.9 | 0.00 | 3.62 | 1.67 | 0.83 | 3.54 | 1.00 |
| 240 | 107.3 | 114.7 | 89.6 | 99.4 | 111.6 | 80.4 | 0.00 | 3.83 | 1.71 | 0.25 | 3.79 | 1.00 |
| 360 | 107.3 | 152.1 | 104.0 | 107.3 | 150.9 | 87.0 | 0.00 | 4.46 | 1.96 | 0.00 | 4.58 | 0.96 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 3.04 | 4.46 | 1.42 |
| P3 (forecast-sum) | 1.54 | 1.96 | 0.42 |
| P4 (adaptive) | 0.00 | 1.00 | 1.00 |
| P5 (always-best-1h) | 3.00 | 4.58 | 1.58 |
| P6 (heuristic) | 0.96 | 1.04 | 0.08 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## AECI -> PACE

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 3.3 min (interpolated between 0 and 5 min).
- P1 vs P4: P1 beats P4 at overhead >= 0.3 min (interpolated between 0 and 5 min).
- P1 vs P5: P1 beats P5 at overhead >= 4.0 min (interpolated between 0 and 5 min).
- P1 vs P6: P1 beats P6 at overhead >= 62.8 min (interpolated between 60 and 90 min).
- P2 vs P3: P3 beats P2 at overhead >= 91.0 min (interpolated between 90 and 120 min).
- P2 vs P4: P4 beats P2 at overhead >= 3.6 min (interpolated between 0 and 5 min).
- P2 vs P6: P6 beats P2 at overhead >= 3.1 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 93.6 min (interpolated between 90 and 120 min).
- P4 vs P5: P4 beats P5 at overhead >= 4.4 min (interpolated between 0 and 5 min).
- P4 vs P6: P4 beats P6 at overhead >= 62.8 min (interpolated between 60 and 90 min).
- P5 vs P6: P6 beats P5 at overhead >= 3.9 min (interpolated between 0 and 5 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P3, P2-vs-P5, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 178.2 | 175.8 | 188.5 | 178.2 | 175.3 | 177.8 | 0.00 | 2.83 | 1.62 | 0.08 | 2.83 | 0.08 |
| 5 | 178.2 | 179.5 | 191.5 | 178.5 | 178.9 | 178.2 | 0.00 | 2.83 | 1.75 | 0.08 | 2.88 | 0.08 |
| 10 | 178.2 | 180.8 | 192.1 | 178.2 | 180.2 | 178.2 | 0.00 | 2.83 | 1.75 | 0.00 | 2.88 | 0.08 |
| 15 | 178.2 | 182.2 | 192.8 | 178.2 | 181.6 | 178.2 | 0.00 | 2.83 | 1.75 | 0.00 | 2.88 | 0.08 |
| 20 | 178.2 | 184.1 | 194.0 | 178.2 | 183.6 | 178.2 | 0.00 | 2.83 | 1.79 | 0.00 | 2.88 | 0.08 |
| 30 | 178.2 | 187.2 | 196.4 | 178.2 | 186.5 | 178.2 | 0.00 | 2.88 | 1.92 | 0.00 | 2.92 | 0.08 |
| 45 | 178.2 | 193.7 | 200.1 | 178.2 | 193.1 | 178.2 | 0.00 | 2.92 | 1.79 | 0.00 | 3.00 | 0.04 |
| 60 | 178.2 | 199.3 | 202.9 | 178.2 | 198.7 | 178.2 | 0.00 | 3.00 | 1.79 | 0.00 | 3.08 | 0.04 |
| 90 | 178.2 | 210.3 | 210.6 | 178.2 | 209.7 | 178.4 | 0.00 | 2.92 | 1.75 | 0.00 | 3.00 | 0.04 |
| 120 | 178.2 | 224.2 | 215.6 | 178.2 | 222.2 | 178.2 | 0.00 | 3.08 | 1.67 | 0.00 | 3.08 | 0.00 |
| 180 | 178.2 | 252.0 | 231.7 | 178.2 | 249.2 | 178.2 | 0.00 | 3.21 | 1.79 | 0.00 | 3.21 | 0.00 |
| 240 | 178.2 | 272.3 | 253.5 | 178.2 | 270.3 | 178.2 | 0.00 | 3.04 | 2.00 | 0.00 | 3.08 | 0.00 |
| 360 | 178.2 | 339.7 | 299.1 | 178.2 | 335.3 | 178.2 | 0.00 | 3.38 | 2.29 | 0.00 | 3.38 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 2.83 | 3.38 | 0.54 |
| P3 (forecast-sum) | 1.62 | 2.29 | 0.67 |
| P4 (adaptive) | 0.00 | 0.08 | 0.08 |
| P5 (always-best-1h) | 2.83 | 3.38 | 0.54 |
| P6 (heuristic) | 0.00 | 0.08 | 0.08 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## PACE -> AECI

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 93.8 min (interpolated between 90 and 120 min).
- P1 vs P3: P1 beats P3 at overhead >= 137.9 min (interpolated between 120 and 180 min).
- P1 vs P4: P1 beats P4 at overhead >= 240.0 min (interpolated between 180 and 240 min).
- P1 vs P5: P1 beats P5 at overhead >= 100.7 min (interpolated between 90 and 120 min).
- P2 vs P3: P3 beats P2 at overhead >= 53.3 min (interpolated between 45 and 60 min).
- P2 vs P4: P4 beats P2 at overhead >= 10.1 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 9.0 min (interpolated between 5 and 10 min).
- P3 vs P5: P3 beats P5 at overhead >= 60.8 min (interpolated between 60 and 90 min).
- P4 vs P5: P4 beats P5 at overhead >= 12.6 min (interpolated between 10 and 15 min).
- P5 vs P6: P6 beats P5 at overhead >= 11.4 min (interpolated between 10 and 15 min).
- All other 5 pairs: no crossover in [0, 360] min (P1-vs-P6, P2-vs-P5, P3-vs-P4, P3-vs-P6, P4-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 225.6 | 176.9 | 189.5 | 179.3 | 176.4 | 178.9 | 0.00 | 3.58 | 1.88 | 1.08 | 3.50 | 1.08 |
| 5 | 225.6 | 181.8 | 193.3 | 183.3 | 181.2 | 183.0 | 0.00 | 3.58 | 1.92 | 1.00 | 3.54 | 1.08 |
| 10 | 225.6 | 183.7 | 194.0 | 183.7 | 182.9 | 183.4 | 0.00 | 3.58 | 1.92 | 1.00 | 3.54 | 1.08 |
| 15 | 225.6 | 185.4 | 195.1 | 184.1 | 184.9 | 183.8 | 0.00 | 3.58 | 1.96 | 1.00 | 3.54 | 1.08 |
| 20 | 225.6 | 187.9 | 196.3 | 184.6 | 187.0 | 184.2 | 0.00 | 3.62 | 2.04 | 1.00 | 3.58 | 1.08 |
| 30 | 225.6 | 192.9 | 199.0 | 185.4 | 192.0 | 185.0 | 0.00 | 3.62 | 1.96 | 1.00 | 3.58 | 1.08 |
| 45 | 225.6 | 200.7 | 202.8 | 186.7 | 199.5 | 186.5 | 0.00 | 3.71 | 1.92 | 1.00 | 3.67 | 1.04 |
| 60 | 225.6 | 207.3 | 205.5 | 190.1 | 205.4 | 187.7 | 0.00 | 3.79 | 1.92 | 1.00 | 3.71 | 1.04 |
| 90 | 225.6 | 223.8 | 216.1 | 198.7 | 221.2 | 193.7 | 0.00 | 3.75 | 1.96 | 0.96 | 3.67 | 1.04 |
| 120 | 225.6 | 238.5 | 221.6 | 207.3 | 233.7 | 196.0 | 0.00 | 3.83 | 1.88 | 0.62 | 3.67 | 1.00 |
| 180 | 225.6 | 269.4 | 235.1 | 218.9 | 264.6 | 204.0 | 0.00 | 3.83 | 1.79 | 0.17 | 3.75 | 0.96 |
| 240 | 225.6 | 299.4 | 250.4 | 225.6 | 290.5 | 211.7 | 0.00 | 3.79 | 1.83 | 0.00 | 3.62 | 0.92 |
| 360 | 225.6 | 369.6 | 293.3 | 225.6 | 365.4 | 222.4 | 0.00 | 3.92 | 2.08 | 0.00 | 3.92 | 0.71 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 3.58 | 3.92 | 0.33 |
| P3 (forecast-sum) | 1.79 | 2.08 | 0.29 |
| P4 (adaptive) | 0.00 | 1.08 | 1.08 |
| P5 (always-best-1h) | 3.50 | 3.92 | 0.42 |
| P6 (heuristic) | 0.71 | 1.08 | 0.37 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## AECI -> TEPC

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 3.3 min (interpolated between 0 and 5 min).
- P1 vs P4: P1 beats P4 at overhead >= 0.8 min (interpolated between 0 and 5 min).
- P1 vs P5: P1 beats P5 at overhead >= 4.0 min (interpolated between 0 and 5 min).
- P1 vs P6: P1 beats P6 at overhead >= 20.0 min (interpolated between 15 and 20 min).
- P2 vs P3: P3 beats P2 at overhead >= 237.5 min (interpolated between 180 and 240 min).
- P2 vs P4: P4 beats P2 at overhead >= 3.7 min (interpolated between 0 and 5 min).
- P2 vs P6: P6 beats P2 at overhead >= 3.0 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 254.2 min (interpolated between 240 and 360 min).
- P4 vs P5: P4 beats P5 at overhead >= 4.5 min (interpolated between 0 and 5 min).
- P4 vs P6: P4 beats P6 at overhead >= 20.0 min (interpolated between 15 and 20 min).
- P5 vs P6: P6 beats P5 at overhead >= 3.8 min (interpolated between 0 and 5 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P3, P2-vs-P5, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 178.2 | 176.3 | 190.3 | 178.2 | 176.0 | 177.9 | 0.00 | 2.17 | 1.92 | 0.08 | 2.21 | 0.08 |
| 5 | 178.2 | 179.2 | 194.0 | 178.5 | 178.8 | 178.2 | 0.00 | 2.29 | 1.75 | 0.08 | 2.21 | 0.04 |
| 10 | 178.2 | 179.9 | 194.5 | 178.3 | 179.5 | 178.2 | 0.00 | 2.29 | 1.75 | 0.04 | 2.21 | 0.04 |
| 15 | 178.2 | 181.3 | 195.2 | 178.2 | 180.6 | 178.2 | 0.00 | 2.29 | 1.75 | 0.00 | 2.21 | 0.04 |
| 20 | 178.2 | 183.0 | 196.5 | 178.2 | 182.5 | 178.2 | 0.00 | 2.29 | 1.88 | 0.00 | 2.29 | 0.00 |
| 30 | 178.2 | 185.0 | 198.6 | 178.2 | 184.7 | 178.2 | 0.00 | 2.29 | 1.92 | 0.00 | 2.29 | 0.00 |
| 45 | 178.2 | 190.3 | 202.7 | 178.2 | 189.1 | 178.2 | 0.00 | 2.38 | 1.88 | 0.00 | 2.29 | 0.00 |
| 60 | 178.2 | 194.0 | 205.5 | 178.2 | 192.7 | 178.2 | 0.00 | 2.38 | 1.92 | 0.00 | 2.29 | 0.00 |
| 90 | 178.2 | 202.5 | 212.1 | 178.2 | 200.7 | 178.2 | 0.00 | 2.33 | 1.79 | 0.00 | 2.25 | 0.00 |
| 120 | 178.2 | 211.5 | 222.9 | 178.2 | 209.2 | 178.2 | 0.00 | 2.38 | 2.04 | 0.00 | 2.29 | 0.00 |
| 180 | 178.2 | 229.3 | 238.9 | 178.2 | 226.0 | 178.2 | 0.00 | 2.42 | 2.04 | 0.00 | 2.33 | 0.00 |
| 240 | 178.2 | 248.2 | 247.8 | 178.2 | 244.0 | 178.2 | 0.00 | 2.46 | 1.83 | 0.00 | 2.38 | 0.00 |
| 360 | 178.2 | 314.7 | 277.2 | 178.2 | 305.8 | 178.2 | 0.00 | 3.04 | 1.88 | 0.00 | 2.92 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 2.17 | 3.04 | 0.88 |
| P3 (forecast-sum) | 1.75 | 2.04 | 0.29 |
| P4 (adaptive) | 0.00 | 0.08 | 0.08 |
| P5 (always-best-1h) | 2.21 | 2.92 | 0.71 |
| P6 (heuristic) | 0.00 | 0.08 | 0.08 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## TEPC -> AECI

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 110.6 min (interpolated between 90 and 120 min).
- P1 vs P3: P1 beats P3 at overhead >= 160.2 min (interpolated between 120 and 180 min).
- P1 vs P4: P1 beats P4 at overhead >= 240.0 min (interpolated between 180 and 240 min).
- P1 vs P5: P1 beats P5 at overhead >= 111.8 min (interpolated between 90 and 120 min).
- P2 vs P3: P3 beats P2 at overhead >= 76.8 min (interpolated between 60 and 90 min).
- P2 vs P4: P4 beats P2 at overhead >= 10.1 min (interpolated between 10 and 15 min).
- P2 vs P5: P2 beats P5 at overhead >= 141.2 min (interpolated between 120 and 180 min).
- P2 vs P6: P6 beats P2 at overhead >= 9.0 min (interpolated between 5 and 10 min).
- P3 vs P5: P3 beats P5 at overhead >= 79.7 min (interpolated between 60 and 90 min).
- P4 vs P5: P4 beats P5 at overhead >= 11.1 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 20.0 min (interpolated between 15 and 20 min).
- P5 vs P6: P6 beats P5 at overhead >= 10.6 min (interpolated between 10 and 15 min).
- All other 3 pairs: no crossover in [0, 360] min (P1-vs-P6, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 221.9 | 177.1 | 191.0 | 178.9 | 176.7 | 178.3 | 0.00 | 2.92 | 1.67 | 1.00 | 3.04 | 1.08 |
| 5 | 221.9 | 181.8 | 194.7 | 182.7 | 181.4 | 182.5 | 0.00 | 3.04 | 1.42 | 1.00 | 3.04 | 1.04 |
| 10 | 221.9 | 183.0 | 195.2 | 183.0 | 182.6 | 182.8 | 0.00 | 3.04 | 1.42 | 0.96 | 3.04 | 1.00 |
| 15 | 221.9 | 185.2 | 195.6 | 183.4 | 184.9 | 183.2 | 0.00 | 3.04 | 1.42 | 0.96 | 3.12 | 1.00 |
| 20 | 221.9 | 186.6 | 196.6 | 183.8 | 186.3 | 183.8 | 0.00 | 3.04 | 1.42 | 0.96 | 3.12 | 0.96 |
| 30 | 221.9 | 190.8 | 198.7 | 184.7 | 190.3 | 184.5 | 0.00 | 3.12 | 1.54 | 0.96 | 3.12 | 0.96 |
| 45 | 221.9 | 196.5 | 201.4 | 185.9 | 195.9 | 185.6 | 0.00 | 3.12 | 1.58 | 0.96 | 3.12 | 0.96 |
| 60 | 221.9 | 201.1 | 203.7 | 187.0 | 200.4 | 186.7 | 0.00 | 3.12 | 1.58 | 0.96 | 3.12 | 0.96 |
| 90 | 221.9 | 214.0 | 212.0 | 199.2 | 213.7 | 192.3 | 0.00 | 3.08 | 1.67 | 0.83 | 3.12 | 0.96 |
| 120 | 221.9 | 225.6 | 216.9 | 207.9 | 225.0 | 194.5 | 0.00 | 3.17 | 1.62 | 0.50 | 3.21 | 0.96 |
| 180 | 221.9 | 249.3 | 224.4 | 219.6 | 250.3 | 202.3 | 0.00 | 3.17 | 1.38 | 0.04 | 3.25 | 0.96 |
| 240 | 221.9 | 281.9 | 242.2 | 221.9 | 283.7 | 210.1 | 0.00 | 3.42 | 1.54 | 0.00 | 3.54 | 0.96 |
| 360 | 221.9 | 364.0 | 273.9 | 221.9 | 360.4 | 221.7 | 0.00 | 4.00 | 1.71 | 0.00 | 4.00 | 0.75 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 2.92 | 4.00 | 1.08 |
| P3 (forecast-sum) | 1.38 | 1.71 | 0.33 |
| P4 (adaptive) | 0.00 | 1.00 | 1.00 |
| P5 (always-best-1h) | 3.04 | 4.00 | 0.96 |
| P6 (heuristic) | 0.75 | 1.08 | 0.33 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## EPE -> AECI

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 41.6 min (interpolated between 30 and 45 min).
- P1 vs P3: P1 beats P3 at overhead >= 62.9 min (interpolated between 60 and 90 min).
- P1 vs P4: P1 beats P4 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P1 vs P5: P1 beats P5 at overhead >= 41.1 min (interpolated between 30 and 45 min).
- P1 vs P6: P1 beats P6 at overhead >= 244.6 min (interpolated between 240 and 360 min).
- P2 vs P3: P3 beats P2 at overhead >= 34.7 min (interpolated between 30 and 45 min).
- P2 vs P4: P4 beats P2 at overhead >= 9.3 min (interpolated between 5 and 10 min).
- P2 vs P5: P2 beats P5 at overhead >= 37.5 min (interpolated between 30 and 45 min).
- P2 vs P6: P6 beats P2 at overhead >= 7.9 min (interpolated between 5 and 10 min).
- P3 vs P5: P3 beats P5 at overhead >= 35.2 min (interpolated between 30 and 45 min).
- P4 vs P5: P4 beats P5 at overhead >= 10.4 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 244.6 min (interpolated between 240 and 360 min).
- P5 vs P6: P6 beats P5 at overhead >= 9.6 min (interpolated between 5 and 10 min).
- All other 2 pairs: no crossover in [0, 360] min (P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 199.2 | 174.9 | 189.8 | 177.4 | 174.4 | 177.2 | 0.00 | 4.04 | 1.00 | 1.12 | 4.17 | 0.88 |
| 5 | 199.2 | 179.9 | 192.6 | 181.5 | 179.4 | 180.8 | 0.00 | 4.17 | 1.04 | 1.04 | 4.25 | 0.88 |
| 10 | 199.2 | 181.7 | 192.9 | 181.4 | 181.2 | 181.0 | 0.00 | 4.17 | 1.04 | 1.00 | 4.25 | 0.88 |
| 15 | 199.2 | 185.1 | 193.2 | 181.7 | 184.8 | 181.3 | 0.00 | 4.17 | 1.04 | 1.00 | 4.25 | 0.88 |
| 20 | 199.2 | 186.9 | 193.7 | 182.1 | 186.3 | 181.6 | 0.00 | 4.21 | 1.04 | 1.00 | 4.25 | 0.88 |
| 30 | 199.2 | 193.0 | 194.6 | 182.9 | 192.4 | 182.1 | 0.00 | 4.21 | 1.04 | 1.00 | 4.29 | 0.88 |
| 45 | 199.2 | 201.0 | 197.4 | 183.8 | 201.6 | 182.8 | 0.00 | 4.25 | 1.08 | 0.88 | 4.46 | 0.83 |
| 60 | 199.2 | 209.2 | 198.6 | 185.6 | 208.8 | 183.7 | 0.00 | 4.42 | 1.08 | 0.79 | 4.50 | 0.79 |
| 90 | 199.2 | 226.9 | 205.1 | 192.5 | 226.5 | 188.0 | 0.00 | 4.33 | 1.25 | 0.38 | 4.42 | 0.79 |
| 120 | 199.2 | 244.7 | 208.7 | 198.9 | 243.7 | 189.6 | 0.00 | 4.50 | 1.21 | 0.08 | 4.54 | 0.79 |
| 180 | 199.2 | 281.2 | 219.5 | 199.2 | 282.7 | 194.4 | 0.00 | 4.54 | 1.25 | 0.00 | 4.71 | 0.67 |
| 240 | 199.2 | 324.4 | 229.0 | 199.2 | 318.4 | 199.1 | 0.00 | 4.79 | 1.21 | 0.00 | 4.71 | 0.62 |
| 360 | 199.2 | 442.8 | 257.6 | 199.2 | 440.5 | 202.3 | 0.00 | 5.71 | 1.42 | 0.00 | 5.75 | 0.33 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 4.04 | 5.71 | 1.67 |
| P3 (forecast-sum) | 1.00 | 1.42 | 0.42 |
| P4 (adaptive) | 0.00 | 1.12 | 1.12 |
| P5 (always-best-1h) | 4.17 | 5.75 | 1.58 |
| P6 (heuristic) | 0.33 | 0.88 | 0.54 |

Expected pattern: Policy 5's range is near zero (its decision ignores the overhead knob — it only compares the current grid against the partner grid one hour ahead). Policy 2's range is also small (always-best with no overhead model), but may drop slightly at very high overhead as the source-side minute-granular cost in the sim core renders some marginal migrations no longer worth it. Policy 6's range is larger (the linked knob bites: at high overhead its heuristic refuses migrations it would have made at low overhead).

## AECI -> EPE

**Pairwise crossover analysis:**

- P1 vs P2: P1 beats P2 at overhead >= 4.3 min (interpolated between 0 and 5 min).
- P1 vs P4: P1 beats P4 at overhead >= 4.6 min (interpolated between 0 and 5 min).
- P1 vs P5: P1 beats P5 at overhead >= 4.9 min (interpolated between 0 and 5 min).
- P1 vs P6: P1 beats P6 at overhead >= 93.3 min (interpolated between 90 and 120 min).
- P2 vs P3: P3 beats P2 at overhead >= 54.4 min (interpolated between 45 and 60 min).
- P2 vs P4: P4 beats P2 at overhead >= 4.1 min (interpolated between 0 and 5 min).
- P2 vs P6: P6 beats P2 at overhead >= 3.5 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 57.7 min (interpolated between 45 and 60 min).
- P4 vs P5: P4 beats P5 at overhead >= 5.1 min (interpolated between 5 and 10 min).
- P4 vs P6: P4 beats P6 at overhead >= 93.3 min (interpolated between 90 and 120 min).
- P5 vs P6: P6 beats P5 at overhead >= 4.3 min (interpolated between 0 and 5 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P3, P2-vs-P5, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 178.2 | 174.5 | 189.4 | 177.0 | 174.0 | 176.9 | 0.00 | 3.46 | 1.67 | 0.62 | 3.42 | 0.21 |
| 5 | 178.2 | 178.9 | 193.6 | 178.3 | 178.3 | 177.8 | 0.00 | 3.58 | 1.50 | 0.54 | 3.46 | 0.12 |
| 10 | 178.2 | 180.4 | 194.1 | 178.1 | 179.7 | 177.8 | 0.00 | 3.58 | 1.50 | 0.42 | 3.46 | 0.12 |
| 15 | 178.2 | 181.9 | 194.6 | 178.2 | 181.0 | 177.8 | 0.00 | 3.58 | 1.50 | 0.38 | 3.46 | 0.12 |
| 20 | 178.2 | 185.2 | 195.2 | 178.2 | 184.5 | 177.8 | 0.00 | 3.58 | 1.50 | 0.29 | 3.46 | 0.12 |
| 30 | 178.2 | 188.5 | 196.4 | 178.3 | 187.2 | 177.9 | 0.00 | 3.62 | 1.50 | 0.29 | 3.46 | 0.12 |
| 45 | 178.2 | 196.1 | 199.4 | 178.2 | 194.7 | 177.9 | 0.00 | 3.67 | 1.54 | 0.04 | 3.54 | 0.08 |
| 60 | 178.2 | 203.0 | 201.0 | 178.2 | 201.9 | 178.0 | 0.00 | 3.71 | 1.54 | 0.00 | 3.67 | 0.08 |
| 90 | 178.2 | 217.8 | 210.8 | 178.2 | 214.8 | 178.2 | 0.00 | 3.71 | 1.75 | 0.00 | 3.54 | 0.04 |
| 120 | 178.2 | 232.4 | 218.8 | 178.2 | 229.7 | 178.3 | 0.00 | 3.75 | 1.88 | 0.00 | 3.67 | 0.04 |
| 180 | 178.2 | 267.0 | 237.7 | 178.2 | 260.0 | 178.2 | 0.00 | 3.96 | 2.04 | 0.00 | 3.75 | 0.00 |
| 240 | 178.2 | 302.8 | 254.0 | 178.2 | 294.0 | 178.2 | 0.00 | 4.12 | 2.08 | 0.00 | 3.92 | 0.00 |
| 360 | 178.2 | 407.5 | 293.7 | 178.2 | 393.6 | 178.2 | 0.00 | 4.92 | 2.25 | 0.00 | 4.71 | 0.00 |

**Sanity checks (migration-count range across overhead grid):**

| Policy | min mig_count | max mig_count | range |
| --- | --- | --- | --- |
| P1 (no-migration) | 0.00 | 0.00 | 0.00 |
| P2 (always-best) | 3.46 | 4.92 | 1.46 |
| P3 (forecast-sum) | 1.50 | 2.25 | 0.75 |
| P4 (adaptive) | 0.00 | 0.62 | 0.62 |
| P5 (always-best-1h) | 3.42 | 4.71 | 1.29 |
| P6 (heuristic) | 0.00 | 0.21 | 0.21 |

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
| 0 | 199.2 | 181.8 | 186.3 | 186.7 | 181.1 | 186.3 | 0.00 | 4.33 | 1.17 | 1.08 | 4.38 | 0.62 |
| 5 | 199.2 | 186.9 | 189.4 | 189.7 | 186.2 | 188.9 | 0.00 | 4.46 | 1.17 | 1.00 | 4.50 | 0.62 |
| 10 | 199.2 | 188.9 | 189.8 | 189.8 | 188.3 | 189.1 | 0.00 | 4.46 | 1.17 | 0.92 | 4.50 | 0.62 |
| 15 | 199.2 | 192.4 | 190.3 | 190.0 | 191.4 | 189.2 | 0.00 | 4.54 | 1.17 | 0.83 | 4.50 | 0.62 |
| 20 | 199.2 | 194.9 | 190.8 | 190.1 | 193.9 | 189.4 | 0.00 | 4.54 | 1.17 | 0.83 | 4.50 | 0.62 |
| 30 | 199.2 | 200.8 | 192.0 | 190.5 | 199.4 | 189.7 | 0.00 | 4.62 | 1.17 | 0.83 | 4.54 | 0.62 |
| 45 | 199.2 | 210.2 | 194.2 | 192.0 | 209.4 | 190.2 | 0.00 | 4.62 | 1.17 | 0.75 | 4.67 | 0.58 |
| 60 | 199.2 | 218.8 | 195.6 | 192.1 | 216.9 | 190.9 | 0.00 | 4.71 | 1.17 | 0.42 | 4.67 | 0.58 |
| 90 | 199.2 | 238.3 | 201.0 | 195.3 | 236.4 | 193.6 | 0.00 | 4.62 | 1.17 | 0.21 | 4.62 | 0.50 |
| 120 | 199.2 | 261.4 | 205.5 | 196.2 | 258.2 | 194.7 | 0.00 | 4.92 | 1.21 | 0.17 | 4.88 | 0.50 |
| 180 | 199.2 | 304.9 | 219.3 | 199.2 | 297.4 | 197.4 | 0.00 | 5.08 | 1.38 | 0.00 | 4.92 | 0.38 |
| 240 | 199.2 | 360.8 | 222.1 | 199.2 | 352.4 | 199.0 | 0.00 | 5.50 | 1.12 | 0.00 | 5.38 | 0.29 |
| 360 | 199.2 | 484.0 | 244.6 | 199.2 | 471.3 | 201.1 | 0.00 | 6.17 | 1.21 | 0.00 | 6.04 | 0.21 |

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
| 0 | 194.6 | 181.6 | 186.1 | 186.6 | 181.0 | 186.5 | 0.00 | 4.00 | 0.92 | 1.08 | 4.12 | 0.38 |
| 5 | 194.6 | 186.5 | 188.9 | 189.4 | 185.8 | 188.1 | 0.00 | 4.12 | 0.96 | 1.00 | 4.25 | 0.38 |
| 10 | 194.6 | 188.2 | 189.2 | 189.2 | 187.6 | 188.2 | 0.00 | 4.12 | 0.96 | 0.92 | 4.25 | 0.38 |
| 15 | 194.6 | 191.0 | 189.5 | 189.2 | 190.2 | 188.3 | 0.00 | 4.21 | 0.96 | 0.83 | 4.25 | 0.38 |
| 20 | 194.6 | 193.9 | 190.0 | 189.2 | 193.0 | 188.4 | 0.00 | 4.21 | 0.96 | 0.75 | 4.25 | 0.38 |
| 30 | 194.6 | 198.9 | 190.9 | 189.6 | 198.3 | 188.6 | 0.00 | 4.21 | 0.96 | 0.67 | 4.29 | 0.38 |
| 45 | 194.6 | 208.1 | 192.6 | 190.3 | 206.9 | 189.0 | 0.00 | 4.29 | 0.92 | 0.46 | 4.29 | 0.38 |
| 60 | 194.6 | 215.4 | 193.5 | 189.8 | 214.7 | 189.3 | 0.00 | 4.29 | 0.92 | 0.25 | 4.38 | 0.33 |
| 90 | 194.6 | 232.5 | 200.0 | 192.2 | 232.4 | 191.1 | 0.00 | 4.17 | 1.08 | 0.12 | 4.29 | 0.29 |
| 120 | 194.6 | 252.6 | 205.0 | 194.6 | 251.6 | 191.7 | 0.00 | 4.38 | 1.17 | 0.00 | 4.46 | 0.29 |
| 180 | 194.6 | 292.2 | 213.3 | 194.6 | 292.3 | 192.9 | 0.00 | 4.54 | 1.12 | 0.00 | 4.67 | 0.21 |
| 240 | 194.6 | 347.2 | 221.9 | 194.6 | 340.2 | 194.6 | 0.00 | 5.08 | 1.12 | 0.00 | 5.00 | 0.21 |
| 360 | 194.6 | 450.5 | 243.9 | 194.6 | 443.9 | 196.8 | 0.00 | 5.50 | 1.21 | 0.00 | 5.50 | 0.17 |

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
| 0 | 225.6 | 189.7 | 193.6 | 195.2 | 188.9 | 193.4 | 0.00 | 4.50 | 1.42 | 1.67 | 4.54 | 1.08 |
| 5 | 225.6 | 195.1 | 198.0 | 199.2 | 194.3 | 197.7 | 0.00 | 4.54 | 1.46 | 1.33 | 4.62 | 1.00 |
| 10 | 225.6 | 197.4 | 198.5 | 199.2 | 196.9 | 198.0 | 0.00 | 4.54 | 1.46 | 1.33 | 4.62 | 1.00 |
| 15 | 225.6 | 201.1 | 199.1 | 199.6 | 200.2 | 198.4 | 0.00 | 4.62 | 1.46 | 1.25 | 4.67 | 1.00 |
| 20 | 225.6 | 203.6 | 199.8 | 199.5 | 202.7 | 198.8 | 0.00 | 4.62 | 1.46 | 1.12 | 4.67 | 1.00 |
| 30 | 225.6 | 210.6 | 201.3 | 200.1 | 209.9 | 199.5 | 0.00 | 4.67 | 1.46 | 1.04 | 4.75 | 1.00 |
| 45 | 225.6 | 222.1 | 204.3 | 201.6 | 221.3 | 200.9 | 0.00 | 4.83 | 1.46 | 0.88 | 4.96 | 0.92 |
| 60 | 225.6 | 231.2 | 205.9 | 203.9 | 230.2 | 202.0 | 0.00 | 4.92 | 1.46 | 0.83 | 5.00 | 0.92 |
| 90 | 225.6 | 255.0 | 212.7 | 212.0 | 252.7 | 207.1 | 0.00 | 5.04 | 1.38 | 0.67 | 5.04 | 0.88 |
| 120 | 225.6 | 275.4 | 217.7 | 213.1 | 275.6 | 208.5 | 0.00 | 5.08 | 1.42 | 0.38 | 5.25 | 0.75 |
| 180 | 225.6 | 332.8 | 234.8 | 221.3 | 331.2 | 214.0 | 0.00 | 5.58 | 1.62 | 0.08 | 5.67 | 0.67 |
| 240 | 225.6 | 397.6 | 250.8 | 225.6 | 395.7 | 219.0 | 0.00 | 6.04 | 1.71 | 0.00 | 6.12 | 0.62 |
| 360 | 225.6 | 550.3 | 302.2 | 225.6 | 544.2 | 225.5 | 0.00 | 6.92 | 2.08 | 0.00 | 6.96 | 0.46 |

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
| 0 | 194.6 | 188.9 | 192.8 | 194.4 | 188.1 | 192.6 | 0.00 | 3.83 | 0.58 | 0.92 | 3.71 | 0.25 |
| 5 | 194.6 | 193.4 | 194.6 | 195.5 | 192.6 | 193.7 | 0.00 | 3.88 | 0.62 | 0.58 | 3.79 | 0.25 |
| 10 | 194.6 | 195.4 | 194.8 | 195.0 | 194.4 | 193.7 | 0.00 | 3.88 | 0.62 | 0.50 | 3.79 | 0.25 |
| 15 | 194.6 | 198.1 | 195.0 | 194.8 | 196.5 | 193.7 | 0.00 | 3.96 | 0.62 | 0.42 | 3.79 | 0.25 |
| 20 | 194.6 | 200.7 | 195.2 | 194.5 | 199.5 | 193.8 | 0.00 | 3.96 | 0.62 | 0.29 | 3.83 | 0.25 |
| 30 | 194.6 | 205.7 | 195.7 | 194.1 | 203.9 | 193.8 | 0.00 | 4.00 | 0.62 | 0.21 | 3.88 | 0.25 |
| 45 | 194.6 | 216.1 | 197.2 | 194.0 | 213.9 | 194.1 | 0.00 | 4.17 | 0.62 | 0.12 | 4.08 | 0.17 |
| 60 | 194.6 | 224.5 | 197.8 | 194.0 | 222.2 | 194.3 | 0.00 | 4.25 | 0.62 | 0.12 | 4.17 | 0.17 |
| 90 | 194.6 | 242.5 | 200.6 | 194.6 | 240.1 | 194.8 | 0.00 | 4.21 | 0.62 | 0.00 | 4.21 | 0.08 |
| 120 | 194.6 | 264.5 | 202.8 | 194.6 | 260.0 | 194.9 | 0.00 | 4.50 | 0.62 | 0.00 | 4.38 | 0.08 |
| 180 | 194.6 | 308.0 | 211.2 | 194.6 | 303.3 | 194.6 | 0.00 | 4.67 | 0.75 | 0.00 | 4.62 | 0.00 |
| 240 | 194.6 | 366.6 | 218.6 | 194.6 | 358.2 | 194.6 | 0.00 | 5.17 | 0.79 | 0.00 | 5.08 | 0.00 |
| 360 | 194.6 | 484.3 | 246.9 | 194.6 | 480.4 | 194.6 | 0.00 | 5.71 | 1.12 | 0.00 | 5.79 | 0.00 |

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
