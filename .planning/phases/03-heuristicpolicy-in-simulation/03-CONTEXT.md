# Phase 3: HeuristicPolicy in Simulation - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement overhead estimation functions (checkpoint, transfer, restore) calibrated from Phase 2 empirical data, and a complete HeuristicPolicy class (Policy 6) that runs in expected-simulation mode with stay-vs-migrate comparison, deadline gate, and forecast-based destination evaluation. Additionally, refactor all existing policies (1-5) into separate classes with a shared abstract base, centralizing all policy logic in the heuristics package.

</domain>

<decisions>
## Implementation Decisions

### Overhead Estimation Calibration
- **D-01:** Size-based model — overhead estimation functions are parameterized by `app_size` (matching heuristic.txt signatures `ckpt_overhead(app_size, src_hw)`, `send_overhead(src, dest, app_size)`, `restore_overhead(app_size, dst_hw)`)
- **D-02:** Linear fit from Phase 2 data — fit checkpoint/transfer/restore as linear functions of app_size from the 3 workload data points. Coefficients stored as constants in `overhead.py`
- **D-03:** App size provided via `--app-size-mb` CLI argument in simulation mode. Phase 5 will replace this with real container memory queries (e.g., `crictl stats` or `/proc/<pid>/status`)
- **D-04:** Include hardware scaling — scale baseline overhead estimates by hardware capability ratio (clock_speed_ghz from HW_TABLE). Matches heuristic.txt signatures that pass `src_hw`/`dst_hw`
- **D-05:** Document 3-data-point limitation of linear fit as known limitation / future work. Sufficient for thesis prototype

### Migration Carbon Cost
- **D-06:** Include migration carbon in stay-vs-migrate comparison. Three components: checkpoint carbon (src_hw.wattage * src_intensity), transfer carbon (network_power * avg(src_intensity, dst_intensity)), restore carbon (dst_hw.wattage * dst_intensity)
- **D-07:** Checkpoint uses source hardware wattage, restore uses destination hardware wattage. Current-hour carbon intensity for all phases (migration is seconds-long, intensity won't change mid-migration)
- **D-08:** Network power included by default but togglable. `include_network_power` parameter on HeuristicPolicy constructor AND `--include-network-power` CLI flag feeding into it. Enables clean ablation in Phase 4 (HEUR-10)
- **D-09:** Default network power: 15W (NETWORK_POWER_WATTS constant in overhead module)

### Simulation Integration
- **D-10:** Refactor ALL policies (1-6) into separate classes in the heuristics package — not just Policy 6. Goes beyond INFR-01 scope but provides cleaner foundation for Phase 4 evaluation harness
- **D-11:** Abstract base class `BasePolicy` with abstract `decide(intensity_lookup, regions, current_region, sim_timestamp, ...) -> (should_migrate, target_region)`. All 6 policies implement it
- **D-12:** File layout: `heuristics/base.py` (abstract base), `heuristics/policies.py` (Policies 1-5), `heuristics/policy_heuristic.py` (Policy 6). All centralized in heuristics package
- **D-13:** `simulate_policy_decision()` in run_carbon_migration_test.py becomes a thin dispatcher that instantiates the appropriate policy class and calls `decide()`
- **D-14:** New CLI args (`--app-size-mb`, `--deadline-multiplier`, `--include-network-power`) are Policy-6-only flags — other policies ignore them

### Re-evaluation & Deadline
- **D-15:** Re-evaluation uses the same hourly check as all other policies. The existing simulation loop calling `decide()` each simulated hour satisfies HEUR-07. No special adaptive frequency needed
- **D-16:** Deadline specified as a multiplier of `--expected-completion`. CLI flag: `--deadline-multiplier` with default 1.5x. E.g., expected-completion=48h * 1.5 = 72h deadline
- **D-17:** Deadline gate blocks migration when `time_left + mig_time > deadline_remaining`. Blocked migrations logged in `migration_events.csv` with event type 'skipped' and reason 'deadline_gate' for thesis analysis

### Claude's Discretion
- Linear regression fitting approach for the 3-workload data points (D-02) — Claude determines the best fitting methodology
- `BasePolicy.decide()` method signature details — exact parameter list beyond the core ones listed
- How to map Phase 2 workload names to approximate app_size values for the linear fit

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Heuristic Design
- `heuristic.txt` — Pseudocode specification for Policy 6's `migrate_decision()`, overhead functions (`ckpt_overhead`, `send_overhead`, `restore_overhead`), and hardware API. Primary design reference.

### Phase 1 Foundations (existing code)
- `src/controller/heuristics/hardware.py` — `HW_TABLE` with `HardwareSpec` dataclass, `get_hardware()`. Provides `power_per_core` and `clock_speed_ghz` used in overhead scaling and carbon calculations.
- `src/controller/heuristics/runtime.py` — `estimate_remaining_hours()` with hardware-adjusted scaling. Used by Policy 6 for `prog_time_left`.
- `src/controller/heuristics/data_splits.py` — `check_split_access()` for train/val/test enforcement.

### Phase 2 Empirical Data
- `data/overhead-benchmark/run_20260420_030700/summary_stats.csv` — Per-workload and aggregate overhead statistics (mean, median, std for checkpoint/transfer/restore). Calibration source for linear fit.
- `data/overhead-benchmark/run_20260420_030700/overhead_raw.csv` — Raw per-migration timing data for fitting.

### Simulation Harness
- `src/tests/carbon-single-pod/run_carbon_migration_test.py` — `simulate_policy_decision()` (lines 341-428), `run_expected_simulation()` (line 431+). Integration point — Policy 6 branch and policy refactor target.

### Requirements
- `.planning/REQUIREMENTS.md` — HEUR-02 through HEUR-08 (overhead estimation, forecast evaluation, stay-vs-migrate, re-evaluation, deadline gate), INFR-01 (separate module), INFR-03 (simulation integration).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `HW_TABLE` and `get_hardware()` in `hardware.py` — hardware specs for all 3 regions, ready for overhead scaling
- `estimate_remaining_hours()` in `runtime.py` — hardware-adjusted time-left calculation, usable as `prog_time_left` equivalent
- `check_split_access()` in `data_splits.py` — data discipline enforcement for simulation timestamps
- `simulate_policy_decision()` in `run_carbon_migration_test.py` — existing policy decision logic for Policies 1-5, to be refactored into classes
- `lookup_intensity()` and `get_min_region_at()` helper functions in simulation harness — shared forecast lookup utilities

### Established Patterns
- `sys.path.insert()` for inter-module imports (no proper package installation)
- `dataclass(frozen=True)` for immutable data structures (HardwareSpec)
- Argparse with `choices=` for policy selection
- CSV output via manual f-string formatting (carbon_log.csv, migration_events.csv)

### Integration Points
- `run_carbon_migration_test.py` argparse: add `--policy 6` choice, `--app-size-mb`, `--deadline-multiplier`, `--include-network-power` flags
- `simulate_policy_decision()` refactored to thin dispatcher calling policy classes from heuristics package
- `migration_events.csv` schema: add 'skipped' event type with 'reason' column for deadline gate logging
- `heuristics/__init__.py` — needs to export new modules (overhead, policies, policy_heuristic, base)

</code_context>

<specifics>
## Specific Ideas

- User wants network power included in migration carbon but togglable for ablation — this aligns perfectly with HEUR-10's ablation study in Phase 4
- User explicitly chose to refactor all policies into separate classes now (Phase 3) rather than deferring — prioritizes clean architecture for the evaluation harness
- Checkpoint carbon uses source HW, restore carbon uses destination HW — directly matches the heuristic.txt pseudocode structure
- Phase 5 will query actual container memory for app_size dynamically — simulation uses CLI arg as a stand-in

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-heuristicpolicy-in-simulation*
*Context gathered: 2026-04-19*
