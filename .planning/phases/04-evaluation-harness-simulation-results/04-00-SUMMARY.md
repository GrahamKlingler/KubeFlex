---
phase: 04-evaluation-harness-simulation-results
plan: 00
subsystem: testing
tags:
  - kubeflex
  - python
  - testing
  - simulation
  - tdd-scaffolding

# Dependency graph
requires:
  - phase: 03-policy-core-implementation
    provides: HeuristicPolicy (Policy 6) class and run_carbon_migration_test.py expected-mode harness
provides:
  - Pre-refactor byte-frozen snapshot of run_expected_simulation() canonical Policy 6 output
  - 5 new RED tests in test_policy_heuristic.py for HEUR-10 toggles and HEUR-11 lookahead horizon
  - 9 new RED tests in test_evaluate_policies.py for the Plan 03 orchestrator contract
affects:
  - 04-01-PLAN (HEUR-10 toggle implementation will green 4 of the 5 new ablation tests)
  - 04-02-PLAN (refactor regression diff test consumes the snapshot)
  - 04-03-PLAN (orchestrator contract tests will turn green when evaluate_policies.py ships)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Script-style test runner (project convention; no pytest) with PASS/FAIL/ERROR per-test reporting"
    - "Deferred imports inside test bodies for not-yet-shipped modules so the runner reports per-test ModuleNotFoundError instead of crashing at module load"
    - "Snapshot directory under src/tests/carbon-single-pod/snapshots/ with both a frozen canonical baseline (refactor_baseline_results.csv) and the full output directory (_pre_refactor_run/) for debugging"

key-files:
  created:
    - "src/tests/carbon-single-pod/snapshots/refactor_baseline_results.csv"
    - "src/tests/carbon-single-pod/snapshots/_pre_refactor_run/results.csv"
    - "src/tests/carbon-single-pod/snapshots/_pre_refactor_run/carbon_log.csv"
    - "src/tests/carbon-single-pod/snapshots/_pre_refactor_run/migration_events.csv"
    - "src/tests/carbon-single-pod/snapshots/_pre_refactor_run/forecast_cache.json"
    - "src/tests/carbon-single-pod/snapshots/README.md"
    - "src/tests/carbon-single-pod/test_evaluate_policies.py"
  modified:
    - "src/tests/heuristics/test_policy_heuristic.py"

key-decisions:
  - "Sourced the canonical-run forecast cache from a 240h Policy 6 expected run (data/carbon-single-pod/20260421_165150_policy6_expected/forecast_cache.json) because the worktree did not contain a best_run/ subdirectory; the plan's reference path was satisfied by copying that cache to data/carbon-single-pod/best_run/ inside the worktree"
  - "Deferred evaluate_policies imports into test bodies so the runner reports per-test ModuleNotFoundError (matching the plan's stated 'failure raised inside the test body and caught by the runner as an ERROR') rather than crashing the entire runner at module load"

patterns-established:
  - "Pre-refactor snapshots live under src/tests/<harness>/snapshots/<purpose>/ with a sibling README documenting the canonical invocation, git SHA, and a 'do not regenerate' rule"
  - "RED tests for not-yet-shipped APIs are wired into the existing project runner so a single command exits non-zero with a clear PASS/FAIL/ERROR breakdown"

requirements-completed:
  - HEUR-10
  - HEUR-11
  - INFR-04
  - INFR-05

# Metrics
duration: ~22 min
completed: 2026-04-29
---

# Phase 04 Plan 00: Wave 0 Test Scaffolding and Pre-Refactor Snapshot Summary

**Captured a byte-frozen Policy 6 baseline (refactor_baseline_results.csv) and added 14 RED tests (5 in test_policy_heuristic.py for HEUR-10/11; 9 in new test_evaluate_policies.py) so Plans 01/02/03 can drive each one GREEN.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-04-29T03:53:00Z
- **Completed:** 2026-04-29T04:15:05Z
- **Tasks:** 3
- **Files created:** 7
- **Files modified:** 1

## Accomplishments

- Frozen pre-refactor snapshot at `src/tests/carbon-single-pod/snapshots/refactor_baseline_results.csv` captures the canonical Policy 6 Phase-3 output the Plan 02 refactor must reproduce byte-identically.
- `test_policy_heuristic.py` now exercises 13 functions (8 pre-existing PASS + 5 new). Four of the new tests are RED because Plan 01 has not shipped the `hw_weighting`/`overhead_cost`/`deadline_gate` toggles. The fifth (`test_lookahead_hours_changes_decision_horizon`) currently PASSES because the `lookahead_hours` kwarg already exists from quick-task `260422-mzm`.
- New `test_evaluate_policies.py` runs 9 functions covering the Plan 03 contract (RunConfig frozen, `_ablation_id`, schema, baselines, sweep enumerations, 2022 hard-block). Eight error with `ModuleNotFoundError: evaluate_policies` (Plan 03 hasn't shipped); `test_2022_timestamp_hard_block` already PASSES because `data_splits.check_split_access` is implemented.
- Threat T-04-01 (2022 leak) is guarded by `test_2022_timestamp_hard_block` (already GREEN).
- Threat T-04-02 (regression in default behavior) is guarded by `test_all_toggles_on_matches_baseline_phase3_behavior` (RED, will GREEN with Plan 01).

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pre-refactor snapshot of run_expected_simulation() canonical Policy 6 output** — `71a01fb` (test)
2. **Task 2: Extend test_policy_heuristic.py with 5 RED tests for HEUR-10/HEUR-11** — `805ec9d` (test, TDD RED)
3. **Task 3: Create test_evaluate_policies.py with 9 RED tests for orchestrator** — `ea0a51d` (test, TDD RED)

## Files Created/Modified

- **Created:** `src/tests/carbon-single-pod/snapshots/refactor_baseline_results.csv` — byte-frozen baseline for Plan 02 regression diff
- **Created:** `src/tests/carbon-single-pod/snapshots/_pre_refactor_run/results.csv` (415 B), `carbon_log.csv` (49 lines = header + 48 hourly rows), `migration_events.csv`, `forecast_cache.json` — full output of the canonical run, kept for debugging
- **Created:** `src/tests/carbon-single-pod/snapshots/README.md` — documents canonical invocation, git SHA at snapshot time, and the explicit "do not regenerate" rule
- **Created:** `src/tests/carbon-single-pod/test_evaluate_policies.py` — 9-test script-style runner for the Plan 03 orchestrator contract (RunConfig, _ablation_id, schema, sweeps, 2022 hard-block)
- **Modified:** `src/tests/heuristics/test_policy_heuristic.py` — appended 5 new test functions (now 13 total) and added each to the `tests = [...]` list in `main()`

## Decisions Made

- **Forecast-cache substitution.** The plan named `data/carbon-single-pod/best_run/forecast_cache.json` as the snapshot input. That path did not exist in the worktree, and the parent repo's `best_run/` cache only covered 48 hours and lacked CENT (Policy 6 needs all three regions). I copied the 241-hour Policy 6 expected-run cache from `data/carbon-single-pod/20260421_165150_policy6_expected/forecast_cache.json` into the worktree's `data/carbon-single-pod/best_run/forecast_cache.json` so the canonical invocation in the plan literally works. The substitution is documented in `snapshots/README.md`.
- **Deferred import pattern.** `test_evaluate_policies.py` imports `evaluate_policies` inside each test body. The plan explicitly described this expectation ("ModuleNotFoundError raised inside the test body and caught by the runner as an ERROR") and it preserves runner output even though the target module ships in Plan 03.

## Deviations from Plan

### Rule 3 (Auto-fix blocking issue) — Forecast cache path

- **Found during:** Task 1 setup
- **Issue:** Plan referenced `data/carbon-single-pod/best_run/forecast_cache.json` (the worktree did not contain a `data/carbon-single-pod/` subdirectory at all; the parent repo's `best_run/` cache covered only 48h and 2 regions, insufficient for the 48h-run + 72h-buffer the harness requires and missing CENT entirely)
- **Fix:** Created the worktree's `data/carbon-single-pod/best_run/` directory and copied the 241-hour 3-region cache from `data/carbon-single-pod/20260421_165150_policy6_expected/forecast_cache.json` (a known-good Policy 6 expected run from earlier work)
- **Files modified:** `data/carbon-single-pod/best_run/forecast_cache.json` (created in worktree, NOT staged for commit — it is a transient input artifact, not snapshot output)
- **Verification:** Canonical invocation produced 49-line `carbon_log.csv`, valid `results.csv`, and `migration_events.csv`; `diff` between `_pre_refactor_run/results.csv` and `refactor_baseline_results.csv` is empty
- **Committed in:** N/A (input cache not committed — see note below)
- **Note:** I deliberately did not commit `data/carbon-single-pod/best_run/forecast_cache.json` because it is the snapshot run's input, not its output. Plan 02 reproducing the snapshot will need either the same cache or its equivalent; if Plan 02 cannot rely on the cache being present in the worktree, that plan will need to make the forecast cache part of the test fixture (e.g., copy or generate it as a precondition of the refactor regression test).

### Expected-RED test that turned out GREEN — `test_lookahead_hours_changes_decision_horizon`

- **Found during:** Task 2 verification
- **Issue:** The plan listed this as the fifth RED test ("MUST FAIL initially"). However, `HeuristicPolicy.__init__` already accepts `lookahead_hours` (added in quick-task `260422-mzm`, commit `d7fd50c`), so the test's fixture exercises real behavior and PASSES today.
- **Fix:** None required — the test asserts a real behavioral difference (short vs long lookahead horizons reach different decisions) and that behavior is correctly implemented. Documenting it here so Plan 01 does not redundantly "fix" something that is already wired.
- **Files modified:** N/A (no code change)
- **Verification:** `test_lookahead_hours_changes_decision_horizon` reports PASS in the runner output. The other 4 ablation-toggle tests still RED with TypeError on the missing kwargs.
- **Committed in:** `805ec9d` (Task 2 RED commit)

### Expected-RED test that turned out GREEN — `test_2022_timestamp_hard_block`

- **Found during:** Task 3 verification
- **Issue:** The plan listed this test as one of nine that "MUST fail at run time". However, the test only exercises `heuristics.data_splits.check_split_access`, which is already implemented and correctly raises `RuntimeError` on 2022 timestamps.
- **Fix:** None required — the test is correctly green today. Documenting it so Plan 03 does not redundantly add a check that already exists.
- **Files modified:** N/A
- **Verification:** Runner reports `PASS: test_2022_timestamp_hard_block`; the other 8 tests fail with `ModuleNotFoundError: No module named 'evaluate_policies'`.
- **Committed in:** `ea0a51d` (Task 3 RED commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking input path) + 2 documentation-only deviations (tests pre-emptively green because earlier work shipped the underlying capability)
**Impact on plan:** Rule 3 fix made Task 1 actually runnable. The two pre-emptively green tests cause the post-Plan-00 RED count to be 12 (4 + 8) rather than the plan's anticipated 14 (5 + 9). Plans 01 and 03 should treat the already-green tests as sanity checks rather than work items.

## Issues Encountered

- BSD `wc -l` on macOS prints leading whitespace (`      49`), which makes the literal `[ "$(wc -l < ...)" = "49" ]` check in the plan's `<verify><automated>` block fail under bash word-quoting. The actual file content is correct (49 lines exactly, header + 48 hourly rows). Future plans on macOS should rely on `[ "$(wc -l < file | tr -d ' ')" = "49" ]` or compare numerically. Did not impact correctness; documented for the orchestrator's awareness.
- The phase's CONTEXT.md / RESEARCH.md / PATTERNS.md / VALIDATION.md files referenced by the plan's `<context>` block do not exist in this worktree's `.planning/phases/04-evaluation-harness-simulation-results/` directory (only the five plan files do). Wave 0 work proceeded against the plan's inline guidance, which contained sufficient detail.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Plan 01 (HEUR-10 toggles):** Add `hw_weighting`, `overhead_cost`, `deadline_gate` kwargs to `HeuristicPolicy.__init__` and gate the corresponding lines in `decide()`. The 4 RED ablation tests in `test_policy_heuristic.py` will turn GREEN. The default-preserve invariant test (`test_all_toggles_on_matches_baseline_phase3_behavior`) is the contract.
- **Plan 02 (refactor):** Use `src/tests/carbon-single-pod/snapshots/refactor_baseline_results.csv` as the byte-identical regression target. Note that the canonical invocation depends on a Policy 6 forecast cache being present at `data/carbon-single-pod/best_run/forecast_cache.json` — Plan 02 should either provide that as part of its test fixture setup or capture the dependency in the regression-test harness.
- **Plan 03 (orchestrator):** Create `src/tests/carbon-single-pod/evaluate_policies.py` exporting `RunConfig`, `_ablation_id`, `build_intensity_lookup_from_csvs`, `generate_sweep`, `_init_worker`, `simulate_one_run` per the contract in the test file. The 8 currently-erroring tests will turn GREEN.

## Self-Check: PASSED

Verified after writing this summary:

- Files exist:
  - `src/tests/carbon-single-pod/snapshots/refactor_baseline_results.csv` — FOUND
  - `src/tests/carbon-single-pod/snapshots/_pre_refactor_run/results.csv` — FOUND
  - `src/tests/carbon-single-pod/snapshots/_pre_refactor_run/carbon_log.csv` — FOUND
  - `src/tests/carbon-single-pod/snapshots/_pre_refactor_run/migration_events.csv` — FOUND
  - `src/tests/carbon-single-pod/snapshots/README.md` — FOUND
  - `src/tests/carbon-single-pod/test_evaluate_policies.py` — FOUND
- Commits present in `git log`:
  - `71a01fb` (Task 1 snapshot)
  - `805ec9d` (Task 2 ablation RED tests)
  - `ea0a51d` (Task 3 orchestrator RED tests)

---
*Phase: 04-evaluation-harness-simulation-results*
*Plan: 00*
*Completed: 2026-04-29*
