---
phase: 04-evaluation-harness-simulation-results
plan: "02"
subsystem: simulation-harness
tags:
  - kubeflex
  - python
  - refactor
  - simulation
  - pure-function
dependency_graph:
  requires:
    - 04-00  # snapshot baseline
    - 04-01  # HEUR-10 ablation toggles on HeuristicPolicy
  provides:
    - _simulation_core.py (pure simulate_one_run() importable by Plan 03 orchestrator)
    - RunConfig dataclass (importable by evaluate_policies.py)
  affects:
    - run_carbon_migration_test.py (thin CLI wrapper delegates to _simulation_core)
    - evaluate_policies.py (Plan 03 can now call simulate_one_run in-process)
tech_stack:
  added:
    - src/tests/carbon-single-pod/_simulation_core.py (new module)
  patterns:
    - Pure function extraction (no I/O, no prints on hot path)
    - Frozen dataclass for immutable configuration (RunConfig)
    - Cache-free policy factory to prevent stale instance reuse across multiprocessing workers
    - Region derivation from intensity_lookup keys (matches forecast data, not HW_TABLE)
key_files:
  created:
    - src/tests/carbon-single-pod/_simulation_core.py
  modified:
    - src/tests/carbon-single-pod/run_carbon_migration_test.py
decisions:
  - "Derive regions from intensity_lookup.keys() rather than HW_TABLE.keys() in simulate_one_run() — regions absent from forecast have no data so the heuristic treats them as 0-carbon destinations, causing divergent migration decisions vs the CLI"
  - "RunConfig is built AFTER region validation in run_expected_simulation() to capture any corrected source_region value"
  - "Snapshot diff checks columns 1+ (skipping wall-clock timestamp column 0 which is inherently non-deterministic)"
metrics:
  duration: "~30 minutes"
  completed: "2026-04-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Phase 04 Plan 02: Simulation Core Extraction Summary

Pure-function refactor of `run_expected_simulation()` into `_simulation_core.simulate_one_run(intensity_lookup, cfg)` — a zero-I/O, zero-print function importable by Plan 03's multiprocessing orchestrator for ~370k parallel simulation runs.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create _simulation_core.py with RunConfig + simulate_one_run() | 545ea78 | src/tests/carbon-single-pod/_simulation_core.py (new) |
| 2 | Refactor run_carbon_migration_test.py to delegate to _simulation_core | fd5bd15 | src/tests/carbon-single-pod/run_carbon_migration_test.py, _simulation_core.py (fix) |

## What Was Built

### `_simulation_core.py` (new module)

- `RunConfig` — frozen dataclass with 14 fields covering all per-run knobs: `start_ts`, `source_region`, `policy_id`, `app_size_mb`, `expected_completion_min`, `expected_migration_min`, `deadline_multiplier`, `lookahead_hours`, `hw_weighting`, `overhead_cost`, `deadline_gate`, `include_network_power`, `use_hw`, `sweep_kind`
- `_ablation_id(cfg)` — D-11 formatter: `f"HW{int(cfg.hw_weighting)}_OH{int(cfg.overhead_cost)}_DL{int(cfg.deadline_gate)}"`
- `_get_policy_for_config(cfg)` — cache-free factory (no module-level `_POLICY_CACHE`); directly instantiates Policy1..Policy5 or HeuristicPolicy with all ablation toggles
- `_simulate_policy_decision()` — 5-line trampoline calling `policy_obj.decide()`; mirrored from CLI wrapper to avoid reverse dependency
- `simulate_one_run(intensity_lookup, cfg) -> dict` — pure function: zero `print()`, zero `open()`, zero `subprocess`, zero HTTP. Returns D-19 schema dict plus `wrapped_into_val` side-channel (D-22)

### `run_carbon_migration_test.py` changes

- Imports `RunConfig, simulate_one_run, _ablation_id` from `_simulation_core` at module load
- Builds `RunConfig` from `args` after region validation
- Adds parity assertion before derived-metrics block: `_result = simulate_one_run(intensity_lookup, cfg)` must agree with CLI loop on `migration_count` and `total_carbon_gco2` (within 0.5)
- All existing CLI behavior (hour-by-hour print loop, file writes, summary banner) is unchanged

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed regions derivation in simulate_one_run()**

- **Found during:** Task 1 smoke test + Task 2 parity check
- **Issue:** `_simulation_core.py` originally used `regions = list(HW_TABLE.keys())` (all 3 regions: CENT, NE, TEN), but the CLI uses `regions = get_all_regions(forecast_data)` which only returns regions present in the forecast data. When the forecast cache lacks CENT data, `lookup_intensity(..., 'CENT', ts)` returns `None`, and `HeuristicPolicy` treats the `None or 0.0` fallback as near-zero carbon, causing it to incorrectly migrate to CENT. This triggered the parity assertion: `pure migration_count=1 vs CLI loop migration_count=0`.
- **Fix:** Changed `regions = list(HW_TABLE.keys())` to `regions = sorted(set(r for r, _ts in intensity_lookup.keys()))` in `simulate_one_run()`. Now the pure function uses exactly the same region set as the CLI.
- **Files modified:** `src/tests/carbon-single-pod/_simulation_core.py`
- **Commit:** fd5bd15 (bundled with Task 2)

**2. [Rule 3 - Blocking] Canonical forecast cache missing CENT data**

- **Found during:** Task 2 snapshot diff verification
- **Issue:** `data/carbon-single-pod/best_run/forecast_cache.json` only has NE and TEN (not CENT). The plan's `--forecast-cache ../data/carbon-single-pod/best_run/forecast_cache.json` cannot reproduce the snapshot (which was generated with a 3-region cache). README.md in the snapshots directory documents this: the original generation used `20260421_165150_policy6_expected/forecast_cache.json` (all 3 regions).
- **Fix:** Used `tests/carbon-single-pod/snapshots/_pre_refactor_run/forecast_cache.json` for the regression diff verification (that cache has CENT, NE, TEN). The substantive columns (columns 1+) match the snapshot exactly; only the wall-clock timestamp column 0 (`ts = datetime.now()`) differs, which is inherently non-deterministic and cannot be byte-identical across runs.
- **Files modified:** None (verified via comparison script, not a code change)
- **Tracking:** `data/carbon-single-pod/best_run/` is untracked; left as-is to avoid scope creep

## Snapshot Regression Result

Verification using `_pre_refactor_run/forecast_cache.json`:
- `migration_count`: 1 (matches snapshot)
- `total_carbon_gco2`: 15955.0 (matches snapshot)
- `baseline_carbon_gco2`: 9004.0 (matches snapshot)
- `job_time_carbon_gco2`: 15927.3 (matches snapshot)
- `migration_carbon_gco2`: 27.7 (matches snapshot)
- `migration_events` field: identical target region, timestamps, intensities
- Only non-matching field: column 0 (`timestamp`) = wall-clock run time (inherently non-deterministic)

## Policy Test Results

All 13 tests in `src/tests/heuristics/test_policy_heuristic.py` pass:
```
Results: 13 passed, 0 failed, 13 total
```

## Known Stubs

None — all fields in `simulate_one_run()` return dict are computed from real simulation logic.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. `_simulation_core.py` is a pure Python module with no external I/O.

## Self-Check: PASSED

- `src/tests/carbon-single-pod/_simulation_core.py` exists: FOUND
- `src/tests/carbon-single-pod/run_carbon_migration_test.py` modified: FOUND
- Commit 545ea78 exists: FOUND
- Commit fd5bd15 exists: FOUND
- 13/13 policy tests pass: VERIFIED
- Parity assertion fires correctly on bad regions, passes on correct ones: VERIFIED
