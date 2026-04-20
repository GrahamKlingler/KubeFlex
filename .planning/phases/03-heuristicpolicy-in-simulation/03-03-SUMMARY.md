---
phase: 03-heuristicpolicy-in-simulation
plan: "03"
subsystem: simulation-harness
tags: [simulation, policy-dispatch, policy6, csv-schema, cli-args]
dependency_graph:
  requires: [03-01, 03-02]
  provides: [policy-6-simulation, extended-csv-schema, policy-class-dispatcher]
  affects: [src/tests/carbon-single-pod/run_carbon_migration_test.py]
tech_stack:
  added: []
  patterns:
    - "Policy class dispatcher via policy_obj.decide() thin wrapper"
    - "Factory function with module-level cache (_POLICY_CACHE) for policy instances"
    - "kwargs.pop() to avoid duplicate keyword argument when forwarding elapsed_hours"
key_files:
  modified:
    - path: src/tests/carbon-single-pod/run_carbon_migration_test.py
      role: "Simulation harness — refactored to dispatch to policy class objects, extended CSV schema, Policy 6 CLI args"
decisions:
  - "Use kwargs.pop('elapsed_hours') in dispatcher to avoid TypeError when forwarding to policy.decide() (elapsed_hours is explicit positional-keyword arg in BasePolicy ABC)"
  - "Policy cache (_POLICY_CACHE) is module-level dict keyed by policy number; safe for single-run script context"
  - "deadline_gate skipped events are logged with event_type=skipped, reason=deadline_gate but no target_region (empty string in CSV)"
  - "Live test CSV writer updated to include event_type/reason header columns for schema consistency"
metrics:
  duration: "~25 minutes"
  completed_date: "2026-04-20"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
---

# Phase 03 Plan 03: Simulation Harness Refactor — Policy Class Dispatcher Summary

**One-liner:** Refactored run_carbon_migration_test.py to dispatch through Policy1-6 class objects via a thin simulate_policy_decision() wrapper, extended migration_events.csv with event_type/reason columns, and wired --policy 6 end-to-end with new --app-size-mb, --deadline-multiplier, --no-network-power CLI flags.

## What Was Built

Task 1 (complete): Surgical refactor of `src/tests/carbon-single-pod/run_carbon_migration_test.py`:

1. **Imports**: Added `from heuristics.policies import Policy1, Policy2, Policy3, Policy4, Policy5, lookup_intensity, get_min_region_at` and `from heuristics.policy_heuristic import HeuristicPolicy`.

2. **Removed local duplicates**: `lookup_intensity()` and `get_min_region_at()` local definitions removed (now imported from heuristics.policies).

3. **Thin dispatcher**: `simulate_policy_decision()` body replaced with `policy_obj.decide(...)` call. Uses `kwargs.pop("elapsed_hours", 0.0)` to avoid duplicate keyword argument error.

4. **Factory function**: `get_policy(args)` with `_POLICY_CACHE` instantiates Policy1-5 or HeuristicPolicy based on `args.policy`.

5. **Call site update**: Main simulation loop now calls `get_policy(args)` before the loop and passes `policy_obj` + `elapsed_hours=float(hour)` to the dispatcher.

6. **Deadline gate logging**: `elif` block after `if should_migrate` records `event_type=skipped, reason=deadline_gate` events for Policy 6.

7. **Extended CSV schema**: `migration_events.csv` header now includes `event_type` and `reason` as final two columns; both expected-simulation and live-test writers updated.

8. **Argparse**: `choices=[1,2,3,4,5,6]`; new args `--app-size-mb` (float, default 64.0), `--deadline-multiplier` (float, default 1.5), `--no-network-power` (store_false → `include_network_power`).

9. **Print summary**: Policy 6 run prints App size, Deadline multiplier, Network power status in header block.

## Verification Results

- Policy 5 regression: exits 0, 0 migrations from NE (correct — NE is always lower carbon than TEN in this forecast window)
- Policy 2 from TEN: migrates to NE in hour 1 (confirms dispatcher logic is correct)
- Policy 6 end-to-end: exits 0, produces carbon_log.csv and migration_events.csv, header block shows Policy 6 info
- migration_events.csv header: `event_num,timestamp,sim_time,pod_name,source_node,source_region,target_node,target_region,intensity_before,intensity_after,migration_duration_ms,event_type,reason`
- Policy 1: 0 migrations as expected

## Acceptance Criteria Check

- [x] run_carbon_migration_test.py contains `choices=[1, 2, 3, 4, 5, 6]`
- [x] run_carbon_migration_test.py contains `from heuristics.policies import Policy1`
- [x] run_carbon_migration_test.py contains `from heuristics.policy_heuristic import HeuristicPolicy`
- [x] run_carbon_migration_test.py contains `def get_policy(args)`
- [x] run_carbon_migration_test.py contains `--app-size-mb`
- [x] run_carbon_migration_test.py contains `--deadline-multiplier`
- [x] run_carbon_migration_test.py contains `--no-network-power`
- [x] run_carbon_migration_test.py contains `set_defaults(include_network_power=True)`
- [x] run_carbon_migration_test.py contains `elapsed_hours=float(hour)`
- [x] run_carbon_migration_test.py contains `"event_type"` in CSV header
- [x] run_carbon_migration_test.py contains `"deadline_gate"` string for skipped events
- [x] Policy 5 simulation exits 0 and produces output files

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] kwargs.pop() fix for elapsed_hours double-passing**
- **Found during:** Task 1 verification run
- **Issue:** `simulate_policy_decision()` extracted `elapsed_hours` from kwargs via `kwargs.get()` but also passed `**kwargs` — since the caller passed `elapsed_hours=float(hour)` as an explicit kwarg, it ended up in `**kwargs` AND as the named arg, causing `TypeError: got multiple values for keyword argument 'elapsed_hours'`
- **Fix:** Changed `kwargs.get("elapsed_hours", 0.0)` to `kwargs.pop("elapsed_hours", 0.0)` so it is removed from kwargs before `**kwargs` expansion
- **Files modified:** `src/tests/carbon-single-pod/run_carbon_migration_test.py`
- **Commit:** 9e520cb (included in Task 1 commit)

## Checkpoint Status

Task 2 (`checkpoint:human-verify`) was approved by the user. All verification criteria confirmed:
1. Policy 6 runs end-to-end — APPROVED
2. Policy 5 regression passes — APPROVED
3. migration_events.csv has event_type/reason columns — APPROVED
4. Unit tests pass — APPROVED

**Plan complete: all 2 tasks finished.**

## Known Stubs

None — all policy dispatch is fully wired to real policy class implementations.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. The forecast_cache.json trust model is unchanged (user-provided file via --forecast-cache, same as pre-refactor).

## Self-Check: PASSED

- [x] src/tests/carbon-single-pod/run_carbon_migration_test.py exists and was modified
- [x] Commit 9e520cb exists: `feat(03-03): refactor harness to use policy class dispatcher with Policy 6 support`
- [x] Policy 5 verification run completed successfully
- [x] Policy 6 verification run completed successfully
- [x] migration_events.csv header includes event_type and reason columns
