#!/usr/bin/env python3
"""Train / validation / test date boundaries for carbon intensity data.

The carbon dataset spans 2020-01-01 through 2022-12-31:
  - Train:  2020-01-01 to 2020-12-31
  - Val:    2021-01-01 to 2021-12-31
  - Test:   2022-01-01 to 2022-12-31 (held out by default)

Use check_split_access() to enforce data discipline. Test-period access
is blocked unless bypass_test=True is explicitly passed.
"""

from datetime import date, datetime, timezone

TRAIN_START = date(2020, 1, 1)
TRAIN_END = date(2020, 12, 31)

VAL_START = date(2021, 1, 1)
VAL_END = date(2021, 12, 31)

TEST_START = date(2022, 1, 1)
TEST_END = date(2022, 12, 31)


def check_split_access(unix_timestamp: int, bypass_test: bool = False) -> str:
    """Return the split name ('train', 'val', or 'test') for *unix_timestamp*.

    Args:
        unix_timestamp: Seconds since epoch (UTC).
        bypass_test: If True, allow access to the 2022 test period instead
            of raising.

    Returns:
        One of 'train', 'val', or 'test'.

    Raises:
        RuntimeError: If the timestamp falls in the test period and
            *bypass_test* is False.
        ValueError: If the timestamp is outside all defined ranges.
    """
    dt_date = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc).date()

    if TRAIN_START <= dt_date <= TRAIN_END:
        return "train"

    if VAL_START <= dt_date <= VAL_END:
        return "val"

    if TEST_START <= dt_date <= TEST_END:
        if not bypass_test:
            raise RuntimeError(
                f"[DATA_SPLIT] Timestamp {unix_timestamp} ({dt_date}) falls in "
                f"the held-out test period ({TEST_START} to {TEST_END}). "
                f"Pass bypass_test=True to allow access."
            )
        return "test"

    raise ValueError(
        f"[DATA_SPLIT] Timestamp {unix_timestamp} ({dt_date}) is outside the "
        f"valid data range ({TRAIN_START} to {TEST_END})."
    )
