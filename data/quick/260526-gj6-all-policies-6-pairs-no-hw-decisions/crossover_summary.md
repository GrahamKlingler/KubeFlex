# Policies 1, 2, 3, 4, 5, 6 -- Pairwise Overhead Crossover (260511-kqo)

**Quick task:** 260511-kqo (extends 260511-k7l / 260511-jce)
**Comparison:** Policy 1 vs Policy 2 vs Policy 3 vs Policy 4 vs Policy 5 vs Policy 6
**Policy legend:** P1=no-migration, P2=always-best, P3=forecast-sum, P4=adaptive, P5=always-best-1h, P6=heuristic
**Generated:** 2026-06-02T18:58:39+00:00
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
- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True, hw_weighting=False, policy_use_hw_override=False.
- **Regime:** HW-blind decisions, HW x CI accounting (`--no-hw-decisions`, 260526-gj6).

## BANC -> CISO

**Pairwise crossover analysis:**

- P1 vs P4: P4 beats P1 at overhead >= 90.0 min (interpolated between 60 and 90 min).
- P2 vs P3: P3 beats P2 at overhead >= 1.2 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 4.9 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 3.0 min (interpolated between 0 and 5 min).
- P4 vs P6: P4 beats P6 at overhead >= 8.2 min (interpolated between 5 and 10 min).
- P5 vs P6: P6 beats P5 at overhead >= 2.6 min (interpolated between 0 and 5 min).
- All other 9 pairs: no crossover in [0, 360] min (P1-vs-P2, P1-vs-P3, P1-vs-P5, P1-vs-P6, P2-vs-P4, P2-vs-P5, P2-vs-P6, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 65.3 | 67.5 | 67.8 | 67.5 | 66.7 | 67.5 | 0.00 | 4.21 | 0.96 | 0.50 | 4.12 | 0.33 |
| 5 | 65.3 | 69.6 | 68.6 | 68.1 | 68.7 | 67.9 | 0.00 | 4.29 | 1.12 | 0.33 | 4.17 | 0.25 |
| 10 | 65.3 | 70.5 | 68.8 | 67.8 | 69.6 | 67.9 | 0.00 | 4.29 | 1.12 | 0.29 | 4.21 | 0.25 |
| 15 | 65.3 | 71.4 | 68.9 | 67.3 | 70.2 | 67.9 | 0.00 | 4.33 | 1.12 | 0.21 | 4.25 | 0.25 |
| 20 | 65.3 | 73.1 | 69.1 | 67.4 | 71.8 | 67.7 | 0.00 | 4.38 | 1.12 | 0.21 | 4.29 | 0.21 |
| 30 | 65.3 | 75.1 | 69.7 | 67.3 | 73.6 | 67.9 | 0.00 | 4.46 | 1.25 | 0.21 | 4.29 | 0.17 |
| 45 | 65.3 | 78.9 | 70.5 | 67.5 | 77.3 | 67.8 | 0.00 | 4.50 | 1.25 | 0.21 | 4.42 | 0.17 |
| 60 | 65.3 | 82.6 | 71.7 | 67.2 | 80.6 | 67.9 | 0.00 | 4.58 | 1.38 | 0.21 | 4.50 | 0.17 |
| 90 | 65.3 | 92.1 | 72.9 | 65.3 | 88.2 | 68.0 | 0.00 | 4.88 | 1.21 | 0.00 | 4.62 | 0.12 |
| 120 | 65.3 | 101.0 | 74.8 | 65.3 | 97.5 | 68.1 | 0.00 | 5.00 | 1.25 | 0.00 | 4.96 | 0.12 |
| 180 | 65.3 | 123.9 | 79.2 | 65.3 | 118.3 | 68.3 | 0.00 | 5.62 | 1.25 | 0.00 | 5.42 | 0.12 |
| 240 | 65.3 | 152.0 | 80.4 | 65.3 | 144.4 | 66.7 | 0.00 | 6.21 | 1.12 | 0.00 | 6.04 | 0.04 |
| 360 | 65.3 | 230.2 | 86.9 | 65.3 | 222.7 | 66.9 | 0.00 | 7.79 | 1.17 | 0.00 | 7.83 | 0.04 |

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

- P1 vs P2: P1 beats P2 at overhead >= 121.1 min (interpolated between 120 and 180 min).
- P1 vs P4: P1 beats P4 at overhead >= 240.0 min (interpolated between 180 and 240 min).
- P1 vs P5: P1 beats P5 at overhead >= 125.8 min (interpolated between 120 and 180 min).
- P2 vs P3: P3 beats P2 at overhead >= 1.7 min (interpolated between 0 and 5 min).
- P2 vs P6: P6 beats P2 at overhead >= 1.9 min (interpolated between 0 and 5 min).
- P3 vs P4: P3 beats P4 at overhead >= 4.7 min (interpolated between 0 and 5 min).
- P3 vs P5: P3 beats P5 at overhead >= 7.8 min (interpolated between 5 and 10 min).
- P3 vs P6: P3 beats P6 at overhead >= 8.3 min (interpolated between 5 and 10 min).
- P4 vs P5: P4 beats P5 at overhead >= 7.3 min (interpolated between 5 and 10 min).
- P4 vs P6: P4 beats P6 at overhead >= 6.9 min (interpolated between 5 and 10 min).
- P5 vs P6: P6 beats P5 at overhead >= 7.7 min (interpolated between 5 and 10 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P3, P1-vs-P6, P2-vs-P4, P2-vs-P5).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 107.3 | 68.4 | 68.7 | 68.4 | 67.6 | 68.8 | 0.00 | 4.62 | 1.62 | 1.25 | 4.62 | 1.08 |
| 5 | 107.3 | 70.6 | 70.0 | 70.0 | 69.7 | 69.9 | 0.00 | 4.71 | 1.62 | 1.08 | 4.67 | 1.00 |
| 10 | 107.3 | 71.5 | 70.2 | 70.1 | 70.5 | 70.3 | 0.00 | 4.71 | 1.62 | 1.04 | 4.67 | 1.00 |
| 15 | 107.3 | 73.1 | 70.5 | 70.2 | 72.1 | 70.4 | 0.00 | 4.71 | 1.62 | 1.04 | 4.75 | 1.00 |
| 20 | 107.3 | 74.3 | 70.7 | 70.4 | 73.2 | 70.5 | 0.00 | 4.75 | 1.62 | 1.04 | 4.79 | 0.96 |
| 30 | 107.3 | 77.2 | 71.4 | 71.2 | 75.8 | 71.0 | 0.00 | 4.88 | 1.62 | 1.04 | 4.88 | 0.92 |
| 45 | 107.3 | 81.6 | 72.8 | 72.1 | 79.9 | 71.5 | 0.00 | 5.00 | 1.79 | 1.00 | 4.96 | 0.92 |
| 60 | 107.3 | 85.5 | 73.7 | 74.2 | 83.9 | 72.0 | 0.00 | 5.04 | 1.79 | 0.88 | 5.04 | 0.92 |
| 90 | 107.3 | 95.4 | 75.8 | 80.6 | 94.1 | 73.9 | 0.00 | 5.21 | 1.54 | 0.83 | 5.42 | 0.88 |
| 120 | 107.3 | 106.8 | 77.7 | 87.2 | 104.9 | 74.9 | 0.00 | 5.58 | 1.54 | 0.50 | 5.71 | 0.88 |
| 180 | 107.3 | 133.3 | 84.2 | 100.7 | 129.8 | 78.1 | 0.00 | 6.29 | 1.67 | 0.21 | 6.33 | 0.88 |
| 240 | 107.3 | 165.7 | 89.6 | 107.3 | 160.1 | 81.9 | 0.00 | 7.00 | 1.71 | 0.00 | 7.00 | 0.83 |
| 360 | 107.3 | 253.4 | 104.0 | 107.3 | 242.1 | 88.3 | 0.00 | 8.71 | 1.96 | 0.00 | 8.62 | 0.75 |

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

- P1 vs P4: P4 beats P1 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P2 vs P3: P3 beats P2 at overhead >= 15.9 min (interpolated between 15 and 20 min).
- P2 vs P4: P4 beats P2 at overhead >= 10.5 min (interpolated between 10 and 15 min).
- P2 vs P5: P2 beats P5 at overhead >= 108.9 min (interpolated between 90 and 120 min).
- P2 vs P6: P6 beats P2 at overhead >= 9.2 min (interpolated between 5 and 10 min).
- P3 vs P5: P3 beats P5 at overhead >= 17.0 min (interpolated between 15 and 20 min).
- P4 vs P5: P4 beats P5 at overhead >= 11.7 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 16.3 min (interpolated between 15 and 20 min).
- P5 vs P6: P6 beats P5 at overhead >= 10.8 min (interpolated between 10 and 15 min).
- All other 6 pairs: no crossover in [0, 360] min (P1-vs-P2, P1-vs-P3, P1-vs-P5, P1-vs-P6, P3-vs-P4, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 178.2 | 182.6 | 188.5 | 187.4 | 181.8 | 188.3 | 0.00 | 4.21 | 1.62 | 1.25 | 4.25 | 0.62 |
| 5 | 178.2 | 187.7 | 191.5 | 190.0 | 186.9 | 189.8 | 0.00 | 4.25 | 1.75 | 1.08 | 4.46 | 0.62 |
| 10 | 178.2 | 189.8 | 192.1 | 190.0 | 188.9 | 189.4 | 0.00 | 4.29 | 1.75 | 1.04 | 4.46 | 0.50 |
| 15 | 178.2 | 192.5 | 192.8 | 189.8 | 192.0 | 189.6 | 0.00 | 4.33 | 1.75 | 0.96 | 4.54 | 0.50 |
| 20 | 178.2 | 195.8 | 194.0 | 188.9 | 195.2 | 189.7 | 0.00 | 4.42 | 1.79 | 0.88 | 4.54 | 0.50 |
| 30 | 178.2 | 201.8 | 196.4 | 188.6 | 200.9 | 189.1 | 0.00 | 4.54 | 1.92 | 0.58 | 4.62 | 0.42 |
| 45 | 178.2 | 212.2 | 200.1 | 188.7 | 211.3 | 189.5 | 0.00 | 4.62 | 1.79 | 0.50 | 4.75 | 0.42 |
| 60 | 178.2 | 221.4 | 202.9 | 184.6 | 220.8 | 189.7 | 0.00 | 4.71 | 1.79 | 0.33 | 4.83 | 0.42 |
| 90 | 178.2 | 243.2 | 210.6 | 179.2 | 241.6 | 192.0 | 0.00 | 4.83 | 1.75 | 0.04 | 4.88 | 0.38 |
| 120 | 178.2 | 266.9 | 215.6 | 178.2 | 267.9 | 188.7 | 0.00 | 5.08 | 1.67 | 0.00 | 5.29 | 0.29 |
| 180 | 178.2 | 334.6 | 231.7 | 178.2 | 330.5 | 186.0 | 0.00 | 6.08 | 1.79 | 0.00 | 6.08 | 0.21 |
| 240 | 178.2 | 387.4 | 253.5 | 178.2 | 385.2 | 182.0 | 0.00 | 6.17 | 2.00 | 0.00 | 6.25 | 0.08 |
| 360 | 178.2 | 588.6 | 299.1 | 178.2 | 584.3 | 180.2 | 0.00 | 8.00 | 2.29 | 0.00 | 8.08 | 0.04 |

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

- P1 vs P2: P1 beats P2 at overhead >= 60.6 min (interpolated between 60 and 90 min).
- P1 vs P3: P1 beats P3 at overhead >= 137.9 min (interpolated between 120 and 180 min).
- P1 vs P4: P1 beats P4 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P1 vs P5: P1 beats P5 at overhead >= 62.6 min (interpolated between 60 and 90 min).
- P2 vs P3: P3 beats P2 at overhead >= 17.1 min (interpolated between 15 and 20 min).
- P2 vs P4: P4 beats P2 at overhead >= 12.8 min (interpolated between 10 and 15 min).
- P2 vs P5: P2 beats P5 at overhead >= 158.6 min (interpolated between 120 and 180 min).
- P2 vs P6: P6 beats P2 at overhead >= 13.4 min (interpolated between 10 and 15 min).
- P3 vs P4: P3 beats P4 at overhead >= 50.2 min (interpolated between 45 and 60 min).
- P3 vs P5: P3 beats P5 at overhead >= 18.4 min (interpolated between 15 and 20 min).
- P3 vs P6: P6 beats P3 at overhead >= 4.6 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 14.1 min (interpolated between 10 and 15 min).
- P4 vs P6: P6 beats P4 at overhead >= 18.1 min (interpolated between 15 and 20 min).
- P5 vs P6: P6 beats P5 at overhead >= 14.6 min (interpolated between 10 and 15 min).
- All other 1 pairs: no crossover in [0, 360] min (P1-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 225.6 | 183.7 | 189.5 | 188.5 | 182.9 | 191.2 | 0.00 | 4.38 | 1.88 | 1.50 | 4.42 | 0.83 |
| 5 | 225.6 | 189.1 | 193.3 | 192.5 | 188.3 | 193.2 | 0.00 | 4.42 | 1.92 | 1.33 | 4.62 | 0.83 |
| 10 | 225.6 | 191.6 | 194.0 | 192.7 | 190.7 | 193.1 | 0.00 | 4.46 | 1.92 | 1.29 | 4.67 | 0.71 |
| 15 | 225.6 | 194.1 | 195.1 | 193.2 | 193.6 | 193.3 | 0.00 | 4.50 | 1.96 | 1.21 | 4.67 | 0.71 |
| 20 | 225.6 | 197.8 | 196.3 | 193.7 | 197.0 | 193.5 | 0.00 | 4.62 | 2.04 | 1.04 | 4.75 | 0.71 |
| 30 | 225.6 | 204.3 | 199.0 | 197.3 | 203.6 | 196.8 | 0.00 | 4.71 | 1.96 | 0.79 | 4.79 | 0.62 |
| 45 | 225.6 | 215.1 | 202.8 | 202.2 | 214.6 | 201.1 | 0.00 | 4.79 | 1.92 | 0.62 | 4.96 | 0.46 |
| 60 | 225.6 | 225.1 | 205.5 | 206.8 | 223.4 | 201.7 | 0.00 | 4.96 | 1.92 | 0.42 | 4.96 | 0.46 |
| 90 | 225.6 | 249.5 | 216.1 | 214.7 | 249.0 | 204.6 | 0.00 | 5.17 | 1.96 | 0.25 | 5.29 | 0.42 |
| 120 | 225.6 | 273.8 | 221.6 | 218.0 | 272.5 | 208.3 | 0.00 | 5.38 | 1.88 | 0.17 | 5.46 | 0.33 |
| 180 | 225.6 | 339.3 | 235.1 | 225.6 | 340.0 | 214.4 | 0.00 | 6.17 | 1.79 | 0.00 | 6.38 | 0.25 |
| 240 | 225.6 | 395.8 | 250.4 | 225.6 | 389.2 | 217.4 | 0.00 | 6.33 | 1.83 | 0.00 | 6.29 | 0.21 |
| 360 | 225.6 | 591.2 | 293.3 | 225.6 | 581.7 | 220.8 | 0.00 | 8.00 | 2.08 | 0.00 | 8.00 | 0.17 |

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

- P1 vs P4: P4 beats P1 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P2 vs P3: P3 beats P2 at overhead >= 12.8 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 12.9 min (interpolated between 10 and 15 min).
- P2 vs P6: P6 beats P2 at overhead >= 7.5 min (interpolated between 5 and 10 min).
- P3 vs P4: P4 beats P3 at overhead >= 13.1 min (interpolated between 10 and 15 min).
- P3 vs P5: P3 beats P5 at overhead >= 14.6 min (interpolated between 10 and 15 min).
- P4 vs P5: P4 beats P5 at overhead >= 14.1 min (interpolated between 10 and 15 min).
- P4 vs P6: P4 beats P6 at overhead >= 23.1 min (interpolated between 20 and 30 min).
- P5 vs P6: P6 beats P5 at overhead >= 8.4 min (interpolated between 5 and 10 min).
- All other 6 pairs: no crossover in [0, 360] min (P1-vs-P2, P1-vs-P3, P1-vs-P5, P1-vs-P6, P2-vs-P5, P3-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 178.2 | 184.7 | 190.3 | 191.8 | 183.8 | 189.5 | 0.00 | 4.92 | 1.92 | 1.50 | 4.83 | 0.62 |
| 5 | 178.2 | 190.2 | 194.0 | 195.6 | 189.4 | 191.9 | 0.00 | 5.00 | 1.75 | 1.25 | 5.00 | 0.58 |
| 10 | 178.2 | 192.8 | 194.5 | 195.3 | 192.2 | 191.0 | 0.00 | 5.04 | 1.75 | 1.17 | 5.08 | 0.42 |
| 15 | 178.2 | 196.6 | 195.2 | 194.7 | 195.4 | 191.1 | 0.00 | 5.17 | 1.75 | 1.04 | 5.12 | 0.42 |
| 20 | 178.2 | 200.3 | 196.5 | 193.6 | 199.0 | 191.1 | 0.00 | 5.25 | 1.88 | 0.96 | 5.21 | 0.42 |
| 30 | 178.2 | 207.4 | 198.6 | 185.5 | 205.7 | 191.0 | 0.00 | 5.42 | 1.92 | 0.62 | 5.38 | 0.42 |
| 45 | 178.2 | 219.8 | 202.7 | 181.3 | 217.1 | 187.7 | 0.00 | 5.62 | 1.88 | 0.29 | 5.46 | 0.33 |
| 60 | 178.2 | 230.0 | 205.5 | 180.8 | 227.4 | 186.4 | 0.00 | 5.71 | 1.92 | 0.21 | 5.58 | 0.29 |
| 90 | 178.2 | 253.2 | 212.1 | 179.3 | 250.7 | 186.1 | 0.00 | 5.67 | 1.79 | 0.08 | 5.62 | 0.25 |
| 120 | 178.2 | 282.1 | 222.9 | 178.2 | 276.4 | 184.2 | 0.00 | 6.08 | 2.04 | 0.00 | 5.88 | 0.21 |
| 180 | 178.2 | 331.5 | 238.9 | 178.2 | 325.3 | 181.0 | 0.00 | 6.12 | 2.04 | 0.00 | 6.00 | 0.08 |
| 240 | 178.2 | 398.7 | 247.8 | 178.2 | 393.0 | 179.4 | 0.00 | 6.67 | 1.83 | 0.00 | 6.62 | 0.04 |
| 360 | 178.2 | 592.5 | 277.2 | 178.2 | 583.2 | 180.0 | 0.00 | 8.38 | 1.88 | 0.00 | 8.33 | 0.04 |

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

- P1 vs P2: P1 beats P2 at overhead >= 49.1 min (interpolated between 45 and 60 min).
- P1 vs P3: P1 beats P3 at overhead >= 160.2 min (interpolated between 120 and 180 min).
- P1 vs P4: P1 beats P4 at overhead >= 120.0 min (interpolated between 90 and 120 min).
- P1 vs P5: P1 beats P5 at overhead >= 52.9 min (interpolated between 45 and 60 min).
- P2 vs P3: P3 beats P2 at overhead >= 13.6 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 20.2 min (interpolated between 20 and 30 min).
- P2 vs P6: P6 beats P2 at overhead >= 19.2 min (interpolated between 15 and 20 min).
- P3 vs P4: P4 beats P3 at overhead >= 160.2 min (interpolated between 120 and 180 min).
- P3 vs P5: P3 beats P5 at overhead >= 15.8 min (interpolated between 15 and 20 min).
- P3 vs P6: P6 beats P3 at overhead >= 44.9 min (interpolated between 30 and 45 min).
- P4 vs P5: P4 beats P5 at overhead >= 22.6 min (interpolated between 20 and 30 min).
- P4 vs P6: P4 beats P6 at overhead >= 5.8 min (interpolated between 5 and 10 min).
- P5 vs P6: P6 beats P5 at overhead >= 21.2 min (interpolated between 20 and 30 min).
- All other 2 pairs: no crossover in [0, 360] min (P1-vs-P6, P2-vs-P5).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 221.9 | 185.4 | 191.0 | 192.5 | 184.6 | 193.1 | 0.00 | 4.75 | 1.67 | 1.50 | 4.58 | 0.67 |
| 5 | 221.9 | 190.7 | 194.7 | 196.4 | 189.7 | 195.9 | 0.00 | 4.83 | 1.42 | 1.17 | 4.75 | 0.62 |
| 10 | 221.9 | 193.3 | 195.2 | 197.0 | 192.1 | 199.3 | 0.00 | 4.96 | 1.42 | 1.17 | 4.79 | 0.42 |
| 15 | 221.9 | 196.4 | 195.6 | 197.9 | 195.2 | 199.5 | 0.00 | 5.00 | 1.42 | 1.00 | 4.83 | 0.42 |
| 20 | 221.9 | 200.2 | 196.6 | 200.3 | 199.0 | 199.6 | 0.00 | 5.08 | 1.42 | 0.83 | 4.96 | 0.42 |
| 30 | 221.9 | 207.3 | 198.7 | 201.8 | 205.6 | 200.9 | 0.00 | 5.17 | 1.54 | 0.71 | 5.00 | 0.38 |
| 45 | 221.9 | 219.1 | 201.4 | 205.6 | 217.0 | 201.4 | 0.00 | 5.29 | 1.58 | 0.50 | 5.21 | 0.38 |
| 60 | 221.9 | 229.5 | 203.7 | 207.6 | 226.4 | 201.8 | 0.00 | 5.46 | 1.58 | 0.33 | 5.29 | 0.38 |
| 90 | 221.9 | 254.3 | 212.0 | 215.8 | 249.1 | 205.6 | 0.00 | 5.62 | 1.67 | 0.12 | 5.33 | 0.33 |
| 120 | 221.9 | 280.6 | 216.9 | 221.9 | 274.2 | 207.1 | 0.00 | 5.88 | 1.62 | 0.00 | 5.62 | 0.29 |
| 180 | 221.9 | 324.1 | 224.4 | 221.9 | 318.0 | 210.8 | 0.00 | 5.75 | 1.38 | 0.00 | 5.62 | 0.25 |
| 240 | 221.9 | 395.4 | 242.2 | 221.9 | 375.0 | 214.0 | 0.00 | 6.46 | 1.54 | 0.00 | 6.00 | 0.21 |
| 360 | 221.9 | 573.1 | 273.9 | 221.9 | 553.8 | 218.0 | 0.00 | 7.96 | 1.71 | 0.00 | 7.71 | 0.17 |

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

- P1 vs P2: P1 beats P2 at overhead >= 23.7 min (interpolated between 20 and 30 min).
- P1 vs P3: P1 beats P3 at overhead >= 62.9 min (interpolated between 60 and 90 min).
- P1 vs P4: P1 beats P4 at overhead >= 60.0 min (interpolated between 45 and 60 min).
- P1 vs P5: P1 beats P5 at overhead >= 25.6 min (interpolated between 20 and 30 min).
- P1 vs P6: P1 beats P6 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P2 vs P3: P3 beats P2 at overhead >= 13.4 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 15.6 min (interpolated between 15 and 20 min).
- P2 vs P6: P6 beats P2 at overhead >= 11.4 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 62.9 min (interpolated between 60 and 90 min).
- P3 vs P5: P3 beats P5 at overhead >= 14.3 min (interpolated between 10 and 15 min).
- P3 vs P6: P6 beats P3 at overhead >= 4.2 min (interpolated between 0 and 5 min).
- P4 vs P5: P4 beats P5 at overhead >= 16.4 min (interpolated between 15 and 20 min).
- P4 vs P6: P4 beats P6 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P5 vs P6: P6 beats P5 at overhead >= 12.6 min (interpolated between 10 and 15 min).
- All other 1 pairs: no crossover in [0, 360] min (P2-vs-P5).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 199.2 | 184.8 | 189.8 | 191.4 | 184.2 | 191.3 | 0.00 | 4.00 | 1.00 | 0.75 | 3.92 | 0.25 |
| 5 | 199.2 | 189.7 | 192.6 | 192.9 | 189.2 | 192.2 | 0.00 | 4.04 | 1.04 | 0.62 | 4.08 | 0.25 |
| 10 | 199.2 | 191.9 | 192.9 | 193.4 | 191.2 | 192.3 | 0.00 | 4.08 | 1.04 | 0.62 | 4.12 | 0.25 |
| 15 | 199.2 | 193.7 | 193.2 | 194.0 | 193.5 | 192.5 | 0.00 | 4.12 | 1.04 | 0.46 | 4.21 | 0.25 |
| 20 | 199.2 | 197.4 | 193.7 | 195.6 | 196.8 | 192.9 | 0.00 | 4.25 | 1.04 | 0.33 | 4.21 | 0.21 |
| 30 | 199.2 | 202.3 | 194.6 | 197.3 | 201.1 | 193.1 | 0.00 | 4.33 | 1.04 | 0.17 | 4.25 | 0.21 |
| 45 | 199.2 | 211.6 | 197.4 | 198.7 | 210.9 | 194.5 | 0.00 | 4.42 | 1.08 | 0.08 | 4.46 | 0.17 |
| 60 | 199.2 | 221.1 | 198.6 | 199.2 | 219.6 | 195.7 | 0.00 | 4.62 | 1.08 | 0.00 | 4.58 | 0.12 |
| 90 | 199.2 | 241.9 | 205.1 | 199.2 | 240.4 | 197.7 | 0.00 | 4.79 | 1.25 | 0.00 | 4.79 | 0.08 |
| 120 | 199.2 | 262.6 | 208.7 | 199.2 | 258.2 | 198.1 | 0.00 | 4.96 | 1.21 | 0.00 | 4.79 | 0.04 |
| 180 | 199.2 | 305.2 | 219.5 | 199.2 | 298.9 | 199.2 | 0.00 | 5.17 | 1.25 | 0.00 | 5.00 | 0.00 |
| 240 | 199.2 | 351.1 | 229.0 | 199.2 | 344.4 | 199.2 | 0.00 | 5.33 | 1.21 | 0.00 | 5.21 | 0.00 |
| 360 | 199.2 | 467.6 | 257.6 | 199.2 | 456.1 | 199.2 | 0.00 | 6.04 | 1.42 | 0.00 | 5.88 | 0.00 |

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

- P1 vs P4: P4 beats P1 at overhead >= 180.0 min (interpolated between 120 and 180 min).
- P2 vs P3: P3 beats P2 at overhead >= 13.4 min (interpolated between 10 and 15 min).
- P2 vs P4: P4 beats P2 at overhead >= 15.4 min (interpolated between 15 and 20 min).
- P2 vs P5: P2 beats P5 at overhead >= 44.3 min (interpolated between 30 and 45 min).
- P2 vs P6: P6 beats P2 at overhead >= 12.8 min (interpolated between 10 and 15 min).
- P3 vs P4: P4 beats P3 at overhead >= 17.7 min (interpolated between 15 and 20 min).
- P3 vs P5: P3 beats P5 at overhead >= 14.6 min (interpolated between 10 and 15 min).
- P3 vs P6: P6 beats P3 at overhead >= 5.7 min (interpolated between 5 and 10 min).
- P4 vs P5: P4 beats P5 at overhead >= 16.4 min (interpolated between 15 and 20 min).
- P4 vs P6: P4 beats P6 at overhead >= 18.8 min (interpolated between 15 and 20 min).
- P5 vs P6: P6 beats P5 at overhead >= 13.8 min (interpolated between 10 and 15 min).
- All other 4 pairs: no crossover in [0, 360] min (P1-vs-P2, P1-vs-P3, P1-vs-P5, P1-vs-P6).

| overhead_min | P1 kgCO2eq | P2 kgCO2eq | P3 kgCO2eq | P4 kgCO2eq | P5 kgCO2eq | P6 kgCO2eq | P1 mig_count | P2 mig_count | P3 mig_count | P4 mig_count | P5 mig_count | P6 mig_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 178.2 | 184.4 | 189.4 | 191.0 | 183.8 | 190.7 | 0.00 | 4.50 | 1.67 | 1.33 | 4.50 | 0.92 |
| 5 | 178.2 | 189.8 | 193.6 | 195.4 | 189.1 | 193.7 | 0.00 | 4.58 | 1.50 | 1.21 | 4.67 | 0.83 |
| 10 | 178.2 | 191.8 | 194.1 | 195.4 | 191.4 | 193.8 | 0.00 | 4.58 | 1.50 | 1.21 | 4.75 | 0.83 |
| 15 | 178.2 | 195.6 | 194.6 | 196.0 | 194.8 | 194.0 | 0.00 | 4.75 | 1.50 | 1.12 | 4.79 | 0.83 |
| 20 | 178.2 | 198.1 | 195.2 | 194.0 | 197.0 | 194.6 | 0.00 | 4.88 | 1.50 | 1.00 | 4.79 | 0.79 |
| 30 | 178.2 | 204.8 | 196.4 | 192.0 | 203.5 | 192.0 | 0.00 | 4.88 | 1.50 | 0.88 | 4.79 | 0.71 |
| 45 | 178.2 | 215.5 | 199.4 | 187.9 | 215.6 | 192.5 | 0.00 | 5.00 | 1.54 | 0.62 | 5.21 | 0.71 |
| 60 | 178.2 | 225.0 | 201.0 | 181.5 | 224.9 | 192.9 | 0.00 | 5.21 | 1.54 | 0.38 | 5.33 | 0.71 |
| 90 | 178.2 | 248.4 | 210.8 | 181.7 | 246.4 | 196.6 | 0.00 | 5.38 | 1.75 | 0.29 | 5.33 | 0.71 |
| 120 | 178.2 | 271.0 | 218.8 | 180.1 | 266.9 | 193.3 | 0.00 | 5.58 | 1.88 | 0.17 | 5.42 | 0.58 |
| 180 | 178.2 | 320.3 | 237.7 | 178.2 | 316.7 | 188.6 | 0.00 | 5.83 | 2.04 | 0.00 | 5.79 | 0.38 |
| 240 | 178.2 | 376.4 | 254.0 | 178.2 | 369.1 | 191.2 | 0.00 | 6.17 | 2.08 | 0.00 | 6.04 | 0.38 |
| 360 | 178.2 | 508.7 | 293.7 | 178.2 | 506.1 | 190.0 | 0.00 | 6.92 | 2.25 | 0.00 | 6.96 | 0.25 |

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
