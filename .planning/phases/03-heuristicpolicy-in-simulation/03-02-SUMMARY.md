---
phase: 03-heuristicpolicy-in-simulation
plan: "02"
subsystem: heuristics
tags: [policy-classes, heuristic-policy, deadline-gate, migration-carbon, unit-tests]
dependency_graph:
  requires:
    - src/controller/heuristics/base.py       # BasePolicy ABC
    - src/controller/heuristics/overhead.py   # ckpt/send/restore overhead functions
    - src/controller/heuristics/hardware.py   # HW_TABLE, HardwareSpec
    - src/controller/heuristics/runtime.py    # estimate_remaining_hours()
    - src/tests/carbon-single-pod/run_carbon_migration_test.py  # source policy logic
  provides:
    - src/controller/heuristics/policies.py       # Policy1-5 classes + helper functions
    - src/controller/heuristics/policy_heuristic.py  # HeuristicPolicy (Policy 6)
    - src/tests/heuristics/test_overhead.py       # overhead unit tests (9 tests)
    - src/tests/heuristics/test_policy_heuristic.py  # heuristic policy unit tests (8 tests)
  affects:
    - src/tests/carbon-single-pod/run_carbon_migration_test.py  # dispatcher target (Plan 03-03)
tech_stack:
  added: []
  patterns:
    - BasePolicy subclasses with identical decide() signature across all policies
    - _h suffix for hours, _s suffix for seconds to prevent unit mismatch bugs
    - lookup_intensity imported from policies.py to avoid duplication in policy_heuristic.py
    - Synthetic intensity_lookup fixtures using make_uniform_intensity() for deterministic tests
key_files:
  created:
    - src/controller/heuristics/policies.py
    - src/controller/heuristics/policy_heuristic.py
    - src/tests/heuristics/test_overhead.py
    - src/tests/heuristics/test_policy_heuristic.py
  modified: []
decisions:
  - "lookup_intensity imported from policies.py into policy_heuristic.py to avoid code duplication"
  - "HW_TABLE passed directly to get_min_region_at() for use_hw=True case (dict-like access via hw[region].power_per_core)"
  - "Policy4 calculate_carbon defined as inline closure to match original harness structure verbatim"
  - "time_left_int = max(1, round(time_left_h)) ensures at least one forecast hour even near completion"
  - "Deadline gate sets last_skip_reason on each blocked destination (last one wins) for logging in harness"
metrics:
  duration: ~18 minutes
  completed: "2026-04-20T23:13:00Z"
  tasks_completed: 3
  files_created: 4
  files_modified: 0
---

# Phase 3 Plan 02: Policy Classes and HeuristicPolicy Summary

**One-liner:** Policy1-5 classes extracted verbatim from simulation harness plus HeuristicPolicy (Policy 6) implementing full migrate_decision() pseudocode with deadline gate, migration carbon accounting, and hardware-weighted forecast evaluation.

## What Was Built

### policies.py — Policy1-5 Classes and Helpers

Five BasePolicy subclasses extracted from `simulate_policy_decision()` in the simulation harness, plus two shared helpers:

| Class/Function | Logic |
|---|---|
| `lookup_intensity(lookup, region, ts)` | Exact-match lookup with 2-hour fuzzy fallback |
| `get_min_region_at(lookup, regions, ts, hw)` | Min carbon region; hw-weighted when hw provided |
| `Policy1.decide()` | Always `(False, None)` — no migration |
| `Policy2.decide()` | Min-intensity region this hour (use_hw kwarg) |
| `Policy3.decide()` | Sum intensity over remaining_hours per region, pick min |
| `Policy4.decide()` | Forecast window + cost threshold with migration cost |
| `Policy5.decide()` | Always-best: min-intensity region for next hour |

### policy_heuristic.py — HeuristicPolicy (Policy 6)

Direct translation of `migrate_decision()` from heuristic.txt. Key behavioral properties:

1. **Stay carbon (HEUR-05):** Sums `power_per_core * intensity` over `time_left_int` hours for current region.
2. **Migration carbon (D-06, D-07):** Checkpoint carbon (src_hw wattage * src_intensity) + restore carbon (dst_hw wattage * dst_intensity) + optional network carbon (15W * avg_intensity, togglable D-08).
3. **Destination running carbon (HEUR-06):** Sum over `time_left_int` hours offset by migration duration.
4. **Deadline gate (HEUR-08, D-17):** Blocks migration if `time_left_h + mig_time_h > deadline_remaining_h`. Sets `last_skip_reason = "deadline_gate"` for harness logging.
5. **Hardware-adjusted time (D-04):** `estimate_remaining_hours()` scales remaining hours by clock speed ratio.

Constructor parameters:
- `app_size_mb` — checkpoint size driving overhead estimates
- `expected_total_minutes` — total expected duration
- `deadline_multiplier` — default 1.5x (D-16)
- `include_network_power` — default True (D-08)
- `network_power_watts` — default 15.0W (D-09)

### Test Files

**test_overhead.py** (9 tests):
- Reference-hw checkpoint matches linear model exactly (scaling=1.0 for TEN 4.00 GHz)
- Slower-hw checkpoint scaled up (CENT 2.47 GHz → 1.619× scale factor)
- Send overhead symmetric with respect to hardware (network-bound)
- Restore overhead on reference and faster hardware
- total_migration_time_h = total_migration_time_s / 3600 (floating point identity)
- NETWORK_POWER_WATTS == 15.0 constant check
- Zero app size returns intercept only

**test_policy_heuristic.py** (8 tests):
- BasePolicy cannot be directly instantiated (TypeError)
- HeuristicPolicy constructor defaults (deadline_multiplier=1.5, include_network_power=True)
- Migrate from NE (high intensity, high wattage) to CENT (low wattage despite moderate intensity)
- Stay in CENT when hw-weighted score is already minimum
- Deadline gate blocks when elapsed_hours=0.99 of 1h job with 1.0x multiplier
- Deadline gate allows migration with 2.0x multiplier and ample time
- Network power toggle produces valid results without crashing
- 10-hour re-evaluation loop produces valid (bool, str|None) tuples throughout

## Verification Results

```
test_overhead.py:          9 passed, 0 failed
test_policy_heuristic.py:  8 passed, 0 failed
test_runtime.py:           7 passed, 0 failed (no regressions)
policies import check:     ok
policy_heuristic import:   ok
```

## Commits

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create Policy1-5 classes and helper functions in policies.py | 6b8192c |
| 2 | Create HeuristicPolicy (Policy 6) in policy_heuristic.py | d75e7d4 |
| 3 | Add unit tests for overhead functions and HeuristicPolicy | 70c836d |

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. All four files are fully functional with no placeholders or hardcoded empty values.

## Threat Flags

None. Policy classes are pure computation on in-memory data structures with no I/O, network access, or user-facing surfaces.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/controller/heuristics/policies.py | FOUND |
| src/controller/heuristics/policy_heuristic.py | FOUND |
| src/tests/heuristics/test_overhead.py | FOUND |
| src/tests/heuristics/test_policy_heuristic.py | FOUND |
| .planning/phases/03-heuristicpolicy-in-simulation/03-02-SUMMARY.md | FOUND |
| commit 6b8192c | FOUND |
| commit d75e7d4 | FOUND |
| commit 70c836d | FOUND |
