#!/usr/bin/env python3
"""Unit tests for hardware-adjusted runtime estimation.

Covers both the clock-speed proxy (``estimate_remaining_hours``) and the
sysbench-backed empirical sibling (``estimate_remaining_hours_empirical``,
260515-jav).

History note (260502-i16): the legacy NE/TEN/CENT-keyed tests were
quarantined when HW_TABLE moved to grid keys (ISNE/CISO/TVA/SWPP/...). The
tests below replace that quarantine — they target both the original
clock-speed function (now exercised on synthetic HardwareSpec fixtures so
they don't depend on the legacy region keys) and the new empirical
estimator. No real-HW_TABLE tests are reintroduced here; that rewrite is
still a follow-up plan.
"""

import sys
from pathlib import Path

# Add controller package to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics.runtime import (  # noqa: E402
    estimate_remaining_hours,
    estimate_remaining_hours_empirical,
)
from heuristics.hardware import HardwareSpec, HW_TABLE  # noqa: E402
import heuristics.sysbench as sysbench_mod  # noqa: E402


# ── Test helper hardware specs (clock-speed proxy tests) ───────────

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


# ── Clock-speed proxy tests (unchanged semantics) ──────────────────


def test_same_hardware_no_scaling():
    """Same source and dest hardware returns unscaled remaining hours."""
    result = estimate_remaining_hours(600, 5.0, HW_FAST, HW_FAST)
    assert result == 5.0, f"Expected 5.0, got {result}"


def test_faster_dest_reduces_time():
    """Faster destination hardware reduces remaining time."""
    result = estimate_remaining_hours(600, 0.0, HW_SLOW, HW_FAST)
    assert result == 5.0, f"Expected 5.0, got {result}"


def test_slower_dest_increases_time():
    """Slower destination hardware increases remaining time."""
    result = estimate_remaining_hours(600, 0.0, HW_FAST, HW_SLOW)
    assert result == 20.0, f"Expected 20.0, got {result}"


def test_elapsed_reduces_remaining():
    """Elapsed time reduces remaining hours before scaling."""
    result = estimate_remaining_hours(600, 8.0, HW_FAST, HW_FAST)
    assert result == 2.0, f"Expected 2.0, got {result}"


def test_elapsed_exceeds_total_returns_zero():
    """Elapsed time exceeding total returns zero (clamped)."""
    result = estimate_remaining_hours(600, 15.0, HW_FAST, HW_FAST)
    assert result == 0.0, f"Expected 0.0, got {result}"


def test_fallback_to_power_per_core():
    """Falls back to power_per_core ratio when clock_speed_ghz is 0."""
    result = estimate_remaining_hours(600, 0.0, HW_NO_CLOCK, HW_NO_CLOCK)
    assert result == 10.0, f"Expected 10.0, got {result}"
    result = estimate_remaining_hours(600, 0.0, HW_NO_CLOCK, HW_NO_CLOCK_HIGH)
    assert result == 5.0, f"Expected 5.0, got {result}"


# ── Empirical sysbench-backed tests (260515-jav) ──────────────────


def test_empirical_differs_from_clock_speed_when_data_present():
    """Empirical estimate differs from clock-speed proxy when both grids have data.

    CISO and MISO both have sysbench data per CONTEXT.md (CISO has 26
    hostnames, MISO 4). The clock-speed ratio (CISO=2.8872 GHz vs MISO=3.1717
    GHz) gives a different value than the sysbench events/sec ratio, so the
    two functions must return different remaining-hours estimates.
    """
    sysbench_mod._FALLBACK_WARNED.clear()
    src_hw = HW_TABLE["CISO"]
    dst_hw = HW_TABLE["MISO"]
    a = estimate_remaining_hours(600, 0.0, src_hw, dst_hw)
    b = estimate_remaining_hours_empirical(
        600, 0.0, src_hw, dst_hw,
        source_key="CISO", dest_key="MISO", by_grid=True,
    )
    assert abs(a - b) > 1e-6, (
        f"Empirical and clock-speed estimates should differ when sysbench data "
        f"is present for both grids; both returned {a}"
    )


def test_empirical_falls_back_when_data_missing():
    """When either endpoint is absent from sysbench, empirical == clock-speed.

    BANC is absent from the sysbench census per CONTEXT.md. The empirical
    function must delegate to the clock-speed proxy and return the exact same
    value (within float tolerance).
    """
    sysbench_mod._FALLBACK_WARNED.clear()
    src_hw = HW_TABLE["BANC"]
    dst_hw = HW_TABLE["CISO"]
    a = estimate_remaining_hours(600, 0.0, src_hw, dst_hw)
    b = estimate_remaining_hours_empirical(
        600, 0.0, src_hw, dst_hw,
        source_key="BANC", dest_key="CISO", by_grid=True,
    )
    assert abs(a - b) < 1e-9, (
        f"Missing-data fallback must delegate to clock-speed proxy: "
        f"clock={a}, empirical={b}"
    )


def test_empirical_ratio_sane_range_for_real_grids():
    """For CISO->MISO, empirical remaining_hours is within (0.5x, 2x) of staying.

    Guards the "10x bug" sanity check from CONTEXT.md line 139. An AMD EPYC
    7252 (CISO) vs an Intel Xeon-style MISO box should produce a single-digit
    ratio.
    """
    sysbench_mod._FALLBACK_WARNED.clear()
    src_hw = HW_TABLE["CISO"]
    dst_hw = HW_TABLE["MISO"]
    staying = estimate_remaining_hours(600, 0.0, src_hw, src_hw)  # 10.0 h
    migrating = estimate_remaining_hours_empirical(
        600, 0.0, src_hw, dst_hw,
        source_key="CISO", dest_key="MISO", by_grid=True,
    )
    assert 0.5 * staying < migrating < 2.0 * staying, (
        f"CISO->MISO empirical remaining_hours={migrating} outside sane band "
        f"(0.5x, 2x) of staying={staying}; possible 10x bug in sysbench data"
    )


# ── Runner ────────────────────────────────────────────────────────


def main():
    tests = [
        # Clock-speed proxy
        test_same_hardware_no_scaling,
        test_faster_dest_reduces_time,
        test_slower_dest_increases_time,
        test_elapsed_reduces_remaining,
        test_elapsed_exceeds_total_returns_zero,
        test_fallback_to_power_per_core,
        # Empirical sibling (260515-jav)
        test_empirical_differs_from_clock_speed_when_data_present,
        test_empirical_falls_back_when_data_missing,
        test_empirical_ratio_sane_range_for_real_grids,
    ]
    passed = 0
    failed = 0
    print(f"Running {len(tests)} runtime tests...")
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ERROR: {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
