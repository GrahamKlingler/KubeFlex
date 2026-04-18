#!/usr/bin/env python3
"""Unit tests for heuristics.data_splits module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics.data_splits import check_split_access


def test_train_access():
    # 2020-01-01 00:00 UTC
    assert check_split_access(1577836800) == "train"


def test_val_access():
    # 2021-01-01 00:00 UTC
    assert check_split_access(1609459200) == "val"


def test_test_access_blocked():
    # 2022-01-01 00:00 UTC — should be blocked by default
    try:
        check_split_access(1640995200)
        assert False, "Expected RuntimeError was not raised"
    except RuntimeError as e:
        assert "[DATA_SPLIT]" in str(e)


def test_test_access_bypass():
    # 2022-01-01 00:00 UTC — allowed with bypass
    assert check_split_access(1640995200, bypass_test=True) == "test"


def test_out_of_range():
    # 2017-07-14 — outside all defined ranges
    try:
        check_split_access(1500000000)
        assert False, "Expected ValueError was not raised"
    except ValueError:
        pass


def test_train_end():
    # 2020-12-31 00:00 UTC
    assert check_split_access(1609372800) == "train"


def test_val_end():
    # 2021-12-31 00:00 UTC
    assert check_split_access(1640908800) == "val"


if __name__ == "__main__":
    tests = [
        test_train_access,
        test_val_access,
        test_test_access_blocked,
        test_test_access_bypass,
        test_out_of_range,
        test_train_end,
        test_val_end,
    ]
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as e:
            print(f"FAIL: {test.__name__} — {e}")
            sys.exit(1)
    print(f"\nAll {len(tests)} data_splits tests passed.")
