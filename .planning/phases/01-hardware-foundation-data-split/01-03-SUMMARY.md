---
phase: 01-hardware-foundation-data-split
plan: 03
status: complete
started: 2026-04-17
completed: 2026-04-17
---

# Plan 01-03 Summary: Real Clock Speed Collection

## What was built

Updated `hardware.py` with real clock speed values collected from Nautilus cluster `/proc/cpuinfo`:

- **CENT** (AMD EPYC 64 Core): 2.47 GHz (was 0.0 placeholder)
- **NE** (AMD EPYC 24 Core): 4.15 GHz (was 0.0 placeholder)
- **TEN** (Intel Xeon Silver 4215R): 4.00 GHz (was 3.20 from spec sheet, updated to match /proc/cpuinfo for consistency)

Updated `test_hardware.py` with clock speed assertions for CENT and NE, plus a new `test_all_regions_have_clock_speed` test ensuring no zero placeholders remain.

## Key files

### Modified

- `src/controller/heuristics/hardware.py` — Real clock_speed_ghz values for all 3 regions
- `src/tests/heuristics/test_hardware.py` — Clock speed assertions + no-zero-placeholder test

## Self-Check: PASSED

- All 7 hardware tests pass
- No `clock_speed_ghz=0.0` placeholders remain
- No TODO(D-04) comments remain
- Runtime estimation now uses clock speed ratio (primary path) for all region pairs

## Deviations

1. **TEN clock speed updated from 3.20 to 4.00** (Rule 1 auto-fix): User provided /proc/cpuinfo data for all three regions. Updated TEN from spec-sheet base clock (3.20 GHz) to measured value (4.00 GHz) for consistency — all values now from the same source.
