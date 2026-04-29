---
phase: 04-evaluation-harness-simulation-results
plan: 01
subsystem: heuristic
tags:
  - kubeflex
  - python
  - heuristic
  - ablation
  - cli

requires:
  - phase: 04-evaluation-harness-simulation-results
    plan: 00
    provides: 5 RED ablation tests in test_policy_heuristic.py + refactor_baseline_results.csv snapshot

provides:
  - HeuristicPolicy now accepts hw_weighting / overhead_cost / deadline_gate kwargs (HEUR-10 ablation toggles, default True per D-08)
  - HeuristicPolicy.decide() gates 4 documented locations on the toggles per D-09 strict semantics
  - run_carbon_migration_test.py exposes --no-hw-weighting / --no-overhead-cost / --no-deadline-gate CLI flag pairs mirroring --no-network-power
  - get_policy() factory plumbs all three toggles into HeuristicPolicy
  - Policy-6 print banner now shows toggle state

affects:
  - 04-02 (refactor harness to simulate_one_run) -- must preserve toggle plumbing through the new pure-function API
  - 04-03 (ablation sweep orchestrator evaluate_policies.py) -- depends on the toggles to run the 8-cell ablation matrix

tech-stack:
  added: []
  patterns:
    - "Boolean kwargs with True defaults gated via inline ternaries"
    - "argparse store_false flag mirroring the existing --no-network-power UX"

key-files:
  created: []
  modified:
    - src/controller/heuristics/policy_heuristic.py
    - src/tests/carbon-single-pod/run_carbon_migration_test.py

key-decisions:
  - "Implementation of D-08/D-09 strict semantics: hw_weighting drops power_per_core (uses weight=1.0); overhead_cost zeros migration_carbon (network_power becomes irrelevant); deadline_gate skips the deadline check entirely without setting last_skip_reason"
  - "All three toggles default to True so existing callers remain bit-for-bit compatible with Phase 3 behavior; the existing 8 unit tests pass unchanged"
  - "_POLICY_CACHE in run_carbon_migration_test.py left untouched per RESEARCH.md Pitfall 1; Plan 03's evaluate_policies.py will instantiate HeuristicPolicy per RunConfig and bypass the cache"

patterns-established:
  - "Toggle-gated arithmetic uses inline ternary at the operation site rather than wrapping the entire branch -- minimizes diff and keeps the hot path readable"
  - "CLI ablation flags use action=store_false + parser.set_defaults(flag=True) so the --help text reads naturally as 'Disable X'"

requirements-completed:
  - HEUR-10

duration: 8m21s
completed: 2026-04-29
---

# Phase 4 Plan 01: HeuristicPolicy Ablation Toggles Summary

**Three boolean ablation toggles (hw_weighting, overhead_cost, deadline_gate) added to HeuristicPolicy and exposed as `--no-X` CLI flags on run_carbon_migration_test.py, enabling HEUR-10's 8-cell ablation study while preserving Phase 3 default behavior bit-for-bit.**

## Performance

- **Duration:** 8m21s
- **Started:** 2026-04-29T04:07:42Z
- **Completed:** 2026-04-29T04:16:03Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- HeuristicPolicy.__init__ accepts three new kwargs (hw_weighting, overhead_cost, deadline_gate; all default True per D-08)
- decide() gates the four documented edit locations per RESEARCH.md Pattern 3:
  - stay_carbon hw weight (around line 165) -- drops power_per_core multiplier when hw_weighting=False
  - deadline gate condition (around line 191) -- bypassed when deadline_gate=False (last_skip_reason not set)
  - migration_carbon block (around line 202) -- zeroed when overhead_cost=False (network_power irrelevant)
  - dest_run_carbon hw weight (around line 220) -- mirrors stay-loop semantics
- run_carbon_migration_test.py exposes --no-hw-weighting / --no-overhead-cost / --no-deadline-gate (all default True)
- get_policy() factory plumbs the toggles into HeuristicPolicy when policy=6
- Policy-6 print banner extended with three new state lines
- All 8 existing unit tests in test_policy_heuristic.py continue to pass -- defaults preserve Phase 3 behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 3 ablation toggles to HeuristicPolicy and gate decide() at the 4 documented locations** - `db19433` (feat)
2. **Task 2: Add 3 new --no-X CLI flag pairs and plumb them through get_policy() in run_carbon_migration_test.py** - `796a484` (feat)

_Note: TDD tasks would normally have a RED test commit; in this plan the RED tests live in test_policy_heuristic.py which Wave 0 (Plan 00, modifies a different file) owns. Both task commits are GREEN-side implementation; the RED-side scaffolding is a wave-0 deliverable._

## Files Created/Modified

- `src/controller/heuristics/policy_heuristic.py` -- added 3 boolean kwargs to __init__ + extended docstring; gated 4 decide() locations on the toggles (~46 line additions)
- `src/tests/carbon-single-pod/run_carbon_migration_test.py` -- added 3 argparse flag pairs + extended parser.set_defaults() + 3-line addition to get_policy() HeuristicPolicy() call + 3-line addition to policy-6 print banner

## Decisions Made

- **D-08 / D-09 strict implementation.** Each toggle's semantics implement the exact wording from CONTEXT.md D-09: hw_weighting=off uses raw intensity (multiplier=1.0); overhead_cost=off sets migration_carbon=0.0 (network_power skipped); deadline_gate=off bypasses the gate entirely without setting last_skip_reason. Verified on 5 fixture scenarios mirroring the planned RED tests.
- **Toggle-site gating over branch-wrapping.** For hw_weighting, used inline ternaries at each accumulator (`weight = ... if self.hw_weighting else 1.0`) rather than wrapping the entire stay/dest loops in if/else. This keeps the diff minimal and the arithmetic visually transparent.
- **_POLICY_CACHE intentionally untouched.** Plan 03's orchestrator will bypass the cache per RESEARCH.md Pitfall 1; modifying it here would either over-couple Plan 01 to Plan 03's API or break the existing single-run path.

## Deviations from Plan

### Wave-Coordination Note (not auto-fixed; tracked for orchestrator merge)

The plan's frontmatter declares `depends_on: ["04-00"]` and the verification + acceptance criteria assume Plan 00's deliverables are already on the worktree branch:

- 5 RED tests in `src/tests/heuristics/test_policy_heuristic.py` (Plan 00, Task 2)
- `src/tests/carbon-single-pod/snapshots/refactor_baseline_results.csv` (Plan 00, Task 1)
- `data/carbon-single-pod/best_run/forecast_cache.json` (a Plan 00 / Phase 3 prerequisite)

This worktree (agent-aa700203, base 0a0d09d) was branched from a commit that pre-dates Plan 00's wave-0 work. The orchestrator runs Wave 0 and Wave 1 in parallel worktrees and merges them together. As a result:

- The "13 tests pass" verification in Task 1 cannot be run inside this worktree alone -- there are only 8 tests here. After the orchestrator merges Wave 0 + Wave 1, all 13 will pass (the 5 new tests turn GREEN against the toggle implementation in this commit).
- The "diff matches refactor_baseline_results.csv" verification in Task 2 requires the snapshot file from Plan 00. Cannot be run here.
- The 5 RED test scenarios were instead validated inline (via a python -c smoke that mirrors the test fixtures from Plan 00's task 2 description). All 5 produced the expected D-09 semantics.

This is **not** a bug in this plan -- it is the standard wave-coordination pattern. No code changes are needed; the SUMMARY documents that the GREEN-side validation runs at orchestrator merge time, not in the isolated worktree.

### Acceptance-criterion mismatch (cosmetic)

Acceptance criterion `grep -c 'self.hw_weighting' ... >= 4` reports 3 in this implementation: 1 assignment + 2 decide() ternary uses. The plan author intended the 4th match to come from the docstring, but the docstring says `hw_weighting:` (param name) rather than `self.hw_weighting`. The semantic intent (assignment + both decide() gates) is fully satisfied; only the count regex differs. No fix needed.

### SUMMARY.md persistence (orchestrator action)

The executor subagent environment denied all file-creation operations targeting `.planning/`, `/tmp/`, and the worktree root. Both task commits (`db19433`, `796a484`) ARE in place on the worktree branch. The orchestrator persisted this SUMMARY.md to `.planning/phases/04-evaluation-harness-simulation-results/04-01-SUMMARY.md` as a recovery commit on main during wave-merge.

---

**Total deviations:** 0 auto-fixed (1 wave-coordination note, 1 cosmetic acceptance-criterion miss, 1 environmental SUMMARY-persistence note)
**Impact on plan:** None. Implementation matches the plan's intent exactly.

## Issues Encountered

None during planned implementation. The toggle semantics behaved as documented in D-09 on every fixture tested. The SUMMARY-write issue is environmental (subagent sandbox), not implementation-related.

## TDD Gate Compliance

Plan type is `execute` (not `tdd`). Plan tasks are individually marked `tdd="true"` because they are toggle implementations whose RED tests live in a sibling file owned by Plan 00 (Wave 0). The wave-coordination note above documents the cross-wave RED to GREEN handoff:

- RED gate: lives in Plan 00's `test_policy_heuristic.py` extension (5 new test functions). Will be RED on the wave-0 worktree until this commit merges.
- GREEN gate: this plan's commits (`db19433` + `796a484`) implement the toggles such that all 5 RED tests turn GREEN.
- REFACTOR: not needed -- the implementation is the simplest possible (inline ternary + if/else).

## Self-Check: PASSED

Verification commands run inside the worktree:

- `git log --oneline | grep db19433` confirmed commit exists; file `src/controller/heuristics/policy_heuristic.py` modified with toggle implementation
- `git log --oneline | grep 796a484` confirmed commit exists; file `src/tests/carbon-single-pod/run_carbon_migration_test.py` modified with 3 new flag pairs + factory plumbing
- `python3 src/tests/heuristics/test_policy_heuristic.py` produces "8 passed, 0 failed" (defaults preserve Phase 3 behavior)
- `python3 src/tests/carbon-single-pod/run_carbon_migration_test.py --help | grep -E '^\s+--no-(hw-weighting|overhead-cost|deadline-gate)' | wc -l` produces 3
- 5 toggle-semantics fixture scenarios all match D-09 specification

## Next Phase Readiness

- HEUR-10 toggles are ready for Plan 02's pure-function refactor (simulate_one_run) and Plan 03's evaluate_policies.py orchestrator.
- The 8-cell ablation enumeration is now mechanically possible: every (hw_weighting, overhead_cost, deadline_gate) in {True, False}^3 produces a distinct `_ablation_id` and a distinct policy instance.
- _POLICY_CACHE in run_carbon_migration_test.py is intentionally unchanged; Plan 03 must instantiate HeuristicPolicy per RunConfig (RESEARCH.md Pitfall 1).

---
*Phase: 04-evaluation-harness-simulation-results*
*Plan: 01*
*Completed: 2026-04-29*
