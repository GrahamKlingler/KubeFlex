---
phase: 01-hardware-foundation-data-split
plan: 02
status: complete
started: 2026-04-17
completed: 2026-04-17
---

# Plan 01-02 Summary: Hardware-Adjusted Runtime Estimation

## What was built

1. **`src/controller/heuristics/runtime.py`** — `estimate_remaining_hours()` function that adjusts remaining execution time based on hardware capabilities. Uses clock speed ratio as primary scaling factor; falls back to power_per_core ratio when clock_speed_ghz is 0.

2. **`src/tests/heuristics/test_runtime.py`** — 7 unit tests covering same-hardware no-scaling, faster/slower destination, elapsed time reduction, zero remaining, power_per_core fallback, and real HW_TABLE data.

3. **`src/tests/carbon-single-pod/run_carbon_migration_test.py`** — Removed inline `HW_VALS` dict and replaced with `from heuristics.hardware import HW_TABLE, get_hardware`. All dict-style `["power_per_core"]` access replaced with `.power_per_core` attribute access.

## Key files

### Created

- `src/controller/heuristics/runtime.py` — Hardware-adjusted runtime estimation
- `src/tests/heuristics/test_runtime.py` — 7 unit tests for runtime module

### Modified

- `src/tests/carbon-single-pod/run_carbon_migration_test.py` — HW_VALS → HW_TABLE import swap

## Self-Check: PASSED

- All 7 runtime tests pass
- Zero `HW_VALS` references remain in simulation harness
- Zero dict-style `["power_per_core"]` access remains
- `from heuristics.hardware import HW_TABLE` present

## Deviations

None.
