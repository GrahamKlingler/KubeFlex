#!/usr/bin/env python3
"""Unit tests for hardware-adjusted runtime estimation.

Tests estimate_remaining_hours() across same-hardware, faster/slower
destination, elapsed time handling, power_per_core fallback, and real
HW_TABLE data scenarios.
"""

import sys
from pathlib import Path

# Add heuristics package to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics.runtime import estimate_remaining_hours
from heuristics.hardware import HardwareSpec, HW_TABLE


# ── Test helper hardware specs ────────────────────────────────────

HW_FAST = HardwareSpec(
    name="Fast",
    power_per_core=10.0,
    available_cores=100,
    tdp_watts=200.0,
    physical_cores=16,
    clock_speed_ghz=4.0,
)

HW_SLOW = HardwareSpec(
    name="Slow",
    power_per_core=5.0,
    available_cores=100,
    tdp_watts=100.0,
    physical_cores=8,
    clock_speed_ghz=2.0,
)

HW_NO_CLOCK = HardwareSpec(
    name="NoClk",
    power_per_core=8.0,
    available_cores=100,
    tdp_watts=150.0,
    physical_cores=12,
    clock_speed_ghz=0.0,
)

HW_NO_CLOCK_HIGH = HardwareSpec(
    name="HiPow",
    power_per_core=16.0,
    available_cores=100,
    tdp_watts=200.0,
    physical_cores=8,
    clock_speed_ghz=0.0,
)


# ── Test functions ────────────────────────────────────────────────

def test_same_hardware_no_scaling():
    """Same source and dest hardware returns unscaled remaining hours."""
    # 600 min = 10h total, 5h elapsed -> 5h remaining, scaling=1.0
    result = estimate_remaining_hours(600, 5.0, HW_FAST, HW_FAST)
    assert result == 5.0, f"Expected 5.0, got {result}"


def test_faster_dest_reduces_time():
    """Faster destination hardware reduces remaining time."""
    # 600 min = 10h, 0h elapsed, slow(2.0GHz)->fast(4.0GHz): 10 * 2.0/4.0 = 5.0
    result = estimate_remaining_hours(600, 0.0, HW_SLOW, HW_FAST)
    assert result == 5.0, f"Expected 5.0, got {result}"


def test_slower_dest_increases_time():
    """Slower destination hardware increases remaining time."""
    # 600 min = 10h, 0h elapsed, fast(4.0GHz)->slow(2.0GHz): 10 * 4.0/2.0 = 20.0
    result = estimate_remaining_hours(600, 0.0, HW_FAST, HW_SLOW)
    assert result == 20.0, f"Expected 20.0, got {result}"


def test_elapsed_reduces_remaining():
    """Elapsed time reduces remaining hours before scaling."""
    # 600 min = 10h, 8h elapsed -> 2h remaining, same hw scaling=1.0
    result = estimate_remaining_hours(600, 8.0, HW_FAST, HW_FAST)
    assert result == 2.0, f"Expected 2.0, got {result}"


def test_elapsed_exceeds_total_returns_zero():
    """Elapsed time exceeding total returns zero (clamped by max)."""
    # 600 min = 10h, 15h elapsed -> max(0, 10-15) = 0
    result = estimate_remaining_hours(600, 15.0, HW_FAST, HW_FAST)
    assert result == 0.0, f"Expected 0.0, got {result}"


def test_fallback_to_power_per_core():
    """Falls back to power_per_core ratio when clock_speed_ghz is 0."""
    # Same no-clock hw: scaling = 8.0/8.0 = 1.0, result = 10.0
    result = estimate_remaining_hours(600, 0.0, HW_NO_CLOCK, HW_NO_CLOCK)
    assert result == 10.0, f"Expected 10.0, got {result}"

    # No-clock to high-power: scaling = 8.0/16.0 = 0.5, result = 5.0
    result = estimate_remaining_hours(600, 0.0, HW_NO_CLOCK, HW_NO_CLOCK_HIGH)
    assert result == 5.0, f"Expected 5.0, got {result}"


def test_with_real_hw_table():
    """Tests using actual HW_TABLE data from hardware.py."""
    # TEN -> TEN: same hw, scaling=1.0, 10h remaining
    result = estimate_remaining_hours(600, 0.0, HW_TABLE["TEN"], HW_TABLE["TEN"])
    assert result == 10.0, f"Expected 10.0, got {result}"

    # CENT -> NE: both clock_speed_ghz=0.0, falls back to power_per_core
    # scaling = 3.5 / 8.3 = 0.42168..., result = 10.0 * 0.42168... = 4.2168...
    result = estimate_remaining_hours(600, 0.0, HW_TABLE["CENT"], HW_TABLE["NE"])
    expected = 10.0 * (3.5 / 8.3)
    assert abs(result - expected) < 0.01, f"Expected ~{expected:.4f}, got {result}"


# ── Runner ────────────────────────────────────────────────────────

def main():
    tests = [
        test_same_hardware_no_scaling,
        test_faster_dest_reduces_time,
        test_slower_dest_increases_time,
        test_elapsed_reduces_remaining,
        test_elapsed_exceeds_total_returns_zero,
        test_fallback_to_power_per_core,
        test_with_real_hw_table,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {test.__name__}: {e}")
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
