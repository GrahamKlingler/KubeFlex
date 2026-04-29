---
phase: 04-evaluation-harness-simulation-results
plan: "03"
subsystem: evaluation-orchestrator
tags:
  - kubeflex
  - python
  - evaluation
  - orchestrator
  - multiprocessing
dependency_graph:
  requires:
    - 04-00  # test contract (9 RED tests in test_evaluate_policies.py)
    - 04-01  # HEUR-10 ablation toggles on HeuristicPolicy
    - 04-02  # _simulation_core.py pure simulate_one_run function
  provides:
    - evaluate_policies.py (Phase 4 orchestrator: all sweeps, Pool, CSV writers)
    - data/evaluation/run_<ts>/{results.csv,ablation.csv,horizon.csv,metadata.json}
  affects:
    - Plan 04 (plotter has data to draw against)
tech_stack:
  added:
    - src/tests/carbon-single-pod/evaluate_policies.py (new orchestrator module)
  patterns:
    - multiprocessing.Pool with initializer for zero-copy lookup sharing
    - imap_unordered with chunksize for throughput
    - Materialized run_configs list (not generator) for tqdm total count
    - Deterministic CSV sort by (sweep_kind, policy, source_region, start_ts, ablation_id, lookahead_hours)
    - Two-layer D-23 data discipline: CSV load filter + per-cfg check_split_access
key_files:
  created:
    - src/tests/carbon-single-pod/evaluate_policies.py
  modified: []
decisions:
  - "Smoke mode also overrides expected_completion_min to 120 min (2h) — the full 48h canonical simulation takes ~43s/config vs <1s/config at 2h; this keeps smoke well under 30s while still exercising all code paths"
  - "Main sweep smoke reduces to 1 region (first of source_regions) in addition to strided timestamps — keeps main smoke at ~30 configs x 6 policies = 180 configs"
  - "Horizon baseline Policies 1-5 are suppressed in smoke mode — the key smoke assertion is the 7-horizon sweep (Policy 6 only), baselines add 35 more configs for no additional coverage benefit in smoke"
metrics:
  duration: "~20 minutes"
  completed: "2026-04-29"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 04 Plan 03: Evaluate Policies Orchestrator Summary

Multiprocessing.Pool-based evaluation orchestrator `evaluate_policies.py` delivering ~370k-run sweeps (main, ablation, horizon) for EVAL-01/02/03, HEUR-10/11, INFR-04 requirements. All 9 Plan 00 RED tests turn GREEN. Smoke mode completes in 1.2s.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create evaluate_policies.py with intensity loader, sweep generator, Pool orchestration, and CSV writers | eb1a8b3 | src/tests/carbon-single-pod/evaluate_policies.py (new, 469 lines) |

## What Was Built

### `evaluate_policies.py` (new module, 469 lines)

- `build_intensity_lookup_from_csvs(sample_data_dir, include_years=(2020, 2021))` — D-23 load-time filter; reads `{CENT,NE,TEN}.csv`, skips 2022 rows; returns `{(region, unix_ts): float}` dict with 52,632 entries for 2020-2021
- `_main_sweep_timestamps(year=2020)` — 8,784 hourly starts (leap year, D-01)
- `_monthly_horizon_timestamps(year=2020)` — 12 monthly starts (D-14)
- `generate_sweep(args)` — deterministic iterator for main (6 policies), ablation (8 cells), horizon (7 values + P1-5 baselines), and all. Calls `check_split_access` per cfg (D-23 belt-and-suspenders). Smoke mode reduces to small deterministic subset
- `_init_worker(intensity_lookup)` — Pool initializer setting module-global `_LOOKUP` (RESEARCH.md Pattern 1)
- `simulate_one_run(cfg)` — worker entry point asserting `_LOOKUP is not None`, delegating to `_core_simulate_one_run`
- `_write_csv(path, rows, schema)` — sorts deterministically by (sweep_kind, policy, source_region, start_ts, ablation_id, lookahead_hours); `extrasaction='ignore'` drops `wrapped_into_val` side-channel
- `_write_metadata_json(...)` — git SHA, timing, wrap_into_val_count, args snapshot
- `main()` — full CLI with `--sweep-kind`, `--smoke`, `--workers`, `--chunksize`, `--out-dir`, `--timestamps`, `--source-regions`, and all per-config knobs

### Sweep coverage

| Sweep | Scale (full) | Smoke |
|-------|-------------|-------|
| main | 8,784 × 3 × 6 = 158,112 | ~180 |
| ablation | 8,784 × 3 × 8 = 210,816 | 8 |
| horizon | 12 × 3 × (7+5) = 432 | 7 |

### Test results

All 9 Plan 00 RED tests pass:
```
Results: 9 passed, 0 failed, 9 total
```

### Smoke run results

```
[SWEEP] total run configs: 195
Duration: 1.2 s
Total runs: 195
Wrap into val: 0
```
All 4 output files produced. Byte-identical across re-runs (determinism verified).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Smoke mode took >90s with default expected_completion_min=2880**

- **Found during:** Task 1 smoke verification
- **Issue:** Smoke mode reduces config COUNT (32 timestamps x 3 regions x 6 = 576 + ablation + horizon) but each config runs a 48-hour simulation (2880 min / 60 = 48 loop iterations). With process pool overhead, first batch took ~43s before reaching throughput. Target is <30s (plan spec), <60s (acceptance criterion).
- **Fix:** (a) Reduced main smoke to 30 timestamps x 1 region (first source_region) x 6 policies = 180 configs. (b) Also overrode `expected_completion_min=120` (2h) in smoke mode — reduces each simulation from 48 to 2 iterations. Combined: 195 total configs completed in 1.2s.
- **Files modified:** `src/tests/carbon-single-pod/evaluate_policies.py`
- **Commit:** eb1a8b3 (same task commit)

## Known Stubs

None — all simulation results are computed from real `_simulation_core.simulate_one_run` logic with real intensity data from `src/sample_data/*.csv`.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes. `evaluate_policies.py` is a pure local batch script: reads CSVs from `src/sample_data/`, writes CSVs to `data/evaluation/run_<ts>/`. No external I/O, no HTTP, no K8s API calls.

D-23 threat (T-04-01) mitigated at both layers:
1. `build_intensity_lookup_from_csvs(include_years=(2020, 2021))` — 2022 never enters memory
2. `generate_sweep` calls `check_split_access(cfg.start_ts)` — raises RuntimeError on 2022 timestamps

T-04-03 (macOS spawn guard) mitigated: `if __name__ == "__main__":` is the sole entry point.
T-04-08 (_LOOKUP NameError under spawn) mitigated: Pool always has `initializer=_init_worker`.
T-04-09 (tqdm "?" count) mitigated: `run_configs = list(generate_sweep(args))` before pool dispatch.
T-04-10 (non-deterministic CSV) mitigated: `_write_csv` sorts before writing; verified byte-identical.

## Self-Check: PASSED

- `src/tests/carbon-single-pod/evaluate_policies.py` exists: FOUND
- Commit eb1a8b3 exists: FOUND
- 9/9 tests pass: VERIFIED
- Smoke run produces all 4 output files: VERIFIED
- 18-column D-19 header: VERIFIED
- Byte-identical re-runs: VERIFIED
- 2022 timestamp triggers RuntimeError: VERIFIED
