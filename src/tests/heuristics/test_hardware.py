#!/usr/bin/env python3
"""Unit tests for heuristics.hardware module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics.hardware import HW_TABLE, HardwareSpec, get_hardware


def test_hw_table_has_three_regions():
    assert set(HW_TABLE.keys()) == {"CENT", "NE", "TEN"}


def test_get_hardware_ten():
    hw = get_hardware("TEN")
    assert hw.power_per_core == 16.25
    assert hw.clock_speed_ghz == 3.20
    assert hw.tdp_watts == 130.0
    assert hw.physical_cores == 8
    assert hw.available_cores == 128


def test_get_hardware_cent():
    hw = get_hardware("CENT")
    assert hw.power_per_core == 3.5
    assert hw.available_cores == 8192
    assert hw.tdp_watts == 225.0
    assert hw.physical_cores == 64


def test_get_hardware_ne():
    hw = get_hardware("NE")
    assert hw.power_per_core == 8.3
    assert hw.available_cores == 1152


def test_get_hardware_unknown_raises():
    try:
        get_hardware("UNKNOWN")
        assert False, "Expected KeyError was not raised"
    except KeyError:
        pass


def test_hardware_spec_frozen():
    hw = get_hardware("TEN")
    try:
        hw.power_per_core = 999
        assert False, "Expected FrozenInstanceError was not raised"
    except AttributeError:
        pass  # dataclasses.FrozenInstanceError is a subclass of AttributeError


if __name__ == "__main__":
    tests = [
        test_hw_table_has_three_regions,
        test_get_hardware_ten,
        test_get_hardware_cent,
        test_get_hardware_ne,
        test_get_hardware_unknown_raises,
        test_hardware_spec_frozen,
    ]
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as e:
            print(f"FAIL: {test.__name__} — {e}")
            sys.exit(1)
    print(f"\nAll {len(tests)} hardware tests passed.")
