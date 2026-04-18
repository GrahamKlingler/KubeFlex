---
phase: 01-hardware-foundation-data-split
plan: 01
subsystem: heuristics
tags: [hardware, data-splits, foundation]
dependency_graph:
  requires: []
  provides: [heuristics-package, hardware-lookup, data-split-guard]
  affects: [controller-main, simulation-harness]
tech_stack:
  added: []
  patterns: [frozen-dataclass, script-based-tests]
key_files:
  created:
    - src/controller/heuristics/__init__.py
    - src/controller/heuristics/hardware.py
    - src/controller/heuristics/data_splits.py
    - src/tests/heuristics/__init__.py
    - src/tests/heuristics/test_hardware.py
    - src/tests/heuristics/test_data_splits.py
  modified: []
decisions:
  - Used frozen dataclass for HardwareSpec to prevent runtime mutation of hardware constants
  - Clock speeds for CENT and NE set to 0.0 with TODO comments for Plan 01-03 to fill in
  - Script-based test runner (no pytest) matching project conventions
metrics:
  duration_seconds: 122
  completed: 2026-04-18T04:04:46Z
  tasks_completed: 2
  tasks_total: 2
  files_created: 6
  files_modified: 0
---

# Phase 01 Plan 01: Hardware Foundation and Data Split Summary

Frozen dataclass HW_TABLE with 3 Nautilus cluster regions (CENT/NE/TEN) and check_split_access() guard blocking 2022 test data by default.

## Task Completion

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create heuristics package with hardware.py and data_splits.py | c1829a6 | src/controller/heuristics/{__init__,hardware,data_splits}.py |
| 2 | Create unit tests for hardware and data_splits modules | 8645331 | src/tests/heuristics/{__init__,test_hardware,test_data_splits}.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed FrozenInstanceError reference in test_hardware.py**
- **Found during:** Task 2
- **Issue:** Test referenced bare `FrozenInstanceError` name which is not in scope; `dataclasses.FrozenInstanceError` is a subclass of `AttributeError`
- **Fix:** Simplified except clause to catch `AttributeError` directly
- **Files modified:** src/tests/heuristics/test_hardware.py
- **Commit:** 8645331 (included in Task 2 commit)

## Verification Results

All 4 plan-level verification checks passed:
1. HW_TABLE has 3 entries
2. check_split_access(1577836800) returns "train"
3. test_hardware.py: 6/6 PASS
4. test_data_splits.py: 7/7 PASS

## Known Stubs

- `clock_speed_ghz=0.0` for CENT and NE regions (intentional placeholder, Plan 01-03 will collect real values)

## Self-Check: PASSED
