---
phase: 03-heuristicpolicy-in-simulation
plan: "01"
subsystem: heuristics
tags: [overhead-estimation, abstract-base, linear-fit, calibration]
dependency_graph:
  requires:
    - src/controller/heuristics/hardware.py  # HardwareSpec dataclass, HW_TABLE
    - data/overhead-benchmark/run_20260420_030700/summary_stats.csv  # calibration source
  provides:
    - src/controller/heuristics/overhead.py   # ckpt_overhead, send_overhead, restore_overhead
    - src/controller/heuristics/base.py       # BasePolicy ABC
  affects:
    - src/controller/heuristics/__init__.py   # updated submodule documentation
tech_stack:
  added: []
  patterns:
    - Linear regression coefficients stored as typed module-level constants (UPPER_CASE)
    - Hardware scaling via clock_speed_ghz ratio relative to TEN reference node
    - ABC + abstractmethod for policy interface enforcement
key_files:
  created:
    - src/controller/heuristics/overhead.py
    - src/controller/heuristics/base.py
  modified:
    - src/controller/heuristics/__init__.py
decisions:
  - "REFERENCE_CLOCK_GHZ=4.00 (TEN region) as empirical calibration baseline — all Phase 2 benchmarks collected on TEN node"
  - "send_overhead accepts src_hw/dst_hw but ignores them (network-bound) — preserves heuristic.txt signature compatibility"
  - "Linear fit on 3 data points: sysbench_cpu=10MB, sysbench_memory=64MB, memcount=256MB — documented as known limitation (D-05)"
metrics:
  duration: ~12 minutes
  completed: "2026-04-20T23:06:54Z"
  tasks_completed: 2
  files_created: 2
  files_modified: 1
---

# Phase 3 Plan 01: Overhead Estimation and BasePolicy ABC Summary

**One-liner:** Calibrated linear-fit overhead functions (ckpt/send/restore) from Phase 2 empirical means plus BasePolicy ABC enforcing the decide() interface across all 6 policies.

## What Was Built

### overhead.py
Linear-fit overhead estimation functions calibrated from Phase 2 benchmark data (3-workload, 18-run each):

| Function | Formula | R² |
|----------|---------|-----|
| `ckpt_overhead(app_size_mb, src_hw)` | `(0.001635*MB + 0.7561) * hw_scale(src)` | 0.97 |
| `send_overhead(src_hw, dst_hw, app_size_mb)` | `0.008085*MB + 0.5341` | 0.99 |
| `restore_overhead(app_size_mb, dst_hw)` | `(0.001681*MB + 0.4560) * hw_scale(dst)` | 0.88 |

Hardware scaling: `clock_speed_ghz(reference=4.00) / hw.clock_speed_ghz`. TEN node (4.00 GHz) scales at 1.0×; NE (4.15 GHz) at 0.964×; CENT (2.47 GHz) at 1.619×.

### base.py
`BasePolicy(ABC)` with abstract `decide()` method. The decide() signature supports all 6 policies via:
- `intensity_lookup`, `regions`, `current_region`, `sim_timestamp`, `remaining_hours`, `elapsed_hours` (core parameters)
- `**kwargs` for policy-specific params (`app_size_mb`, `deadline_multiplier`, `include_network_power` for Policy 6)

### __init__.py
Updated from `# Heuristics module` placeholder to full submodule documentation block listing all 7 submodules (hardware, data_splits, runtime, overhead, base, policies, policy_heuristic).

## Verification Results

```
ckpt_overhead(10.0, TEN) = 0.7724 s  ✓ expected ~0.772
send_overhead(NE, TEN, 256.0) = 2.6039 s  ✓ expected ~2.604
restore_overhead(256.0, TEN) = 0.8863 s  ✓ expected ~0.887
total_migration_time_h(256, TEN, TEN) = 0.001296 h  ✓ < 0.01 h
BasePolicy ABC enforcement: TypeError on direct instantiation  ✓
Incomplete subclass: TypeError on instantiation  ✓
Valid subclass: decide() callable  ✓
Existing runtime tests: 7 passed, 0 failed  ✓
```

## Commits

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create overhead.py with calibrated linear-fit functions | bf42c70 |
| 2 | Create base.py BasePolicy ABC and update __init__.py | 23156b5 |

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. Both modules are fully functional with no placeholders.

## Threat Flags

None. Pure computational modules with no I/O, network access, or user-facing surfaces.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/controller/heuristics/overhead.py | FOUND |
| src/controller/heuristics/base.py | FOUND |
| .planning/phases/03-heuristicpolicy-in-simulation/03-01-SUMMARY.md | FOUND |
| commit bf42c70 | FOUND |
| commit 23156b5 | FOUND |
