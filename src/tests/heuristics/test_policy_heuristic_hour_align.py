#!/usr/bin/env python3
"""Regression tests for HEUR-FVU: hour-aligned lookup_intensity calls in
HeuristicPolicy.decide().

Background: the destination-evaluation loop in policy_heuristic.py used to
build its per-destination time offset as ``int(mig_time_h * 3600)``, which
for typical sub-hour migrations produced a 4-300 s sub-hour offset. Because
those timestamps were not on the hourly grid, every lookup_intensity call
missed the dict's exact-key fast path (~0.15 us) and fell through to the
O(N) full-scan fuzzy fallback (~15.9 ms). On 1000-hour horizons with 25
destination grids and lookahead=48, the bug cost ~5 hours per cell.

These tests pin the contract that the destination loop only ever calls
lookup_intensity with hour-aligned timestamps. They do NOT touch
lookup_intensity itself (its fuzzy fallback is intentional for legitimate
clock-skew tolerance).

Test approach: monkey-patch ``heuristics.policy_heuristic.lookup_intensity``
with a recording wrapper. ``policy_heuristic`` does ``from heuristics.policies
import lookup_intensity`` so the bound name to patch is the one rebound on
``policy_heuristic`` itself, not the original on ``heuristics.policies``.

See quick task 260505-fvu for the one-line fix in the destination loop.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics import policy_heuristic as ph_module
from heuristics.hardware import HW_TABLE
from heuristics.policy_heuristic import HeuristicPolicy


# 2021-01-01 00:00 UTC -- in the val split (test_data_splits.test_val_access).
BASE_TS = 1609459200


def _pick_three_grids():
    """Return three grid identifiers from HW_TABLE with finite power_per_core
    and clock_speed_ghz. Avoids hard-coding -- uses whatever real grids the
    CSV provides."""
    picked = []
    for g, hw in HW_TABLE.items():
        if hw.power_per_core > 0 and hw.clock_speed_ghz > 0:
            picked.append(g)
        if len(picked) >= 3:
            break
    if len(picked) < 3:
        raise RuntimeError(
            f"need at least 3 grids in HW_TABLE; only got {picked}"
        )
    return picked


def _build_intensity_lookup(grids, hours=60):
    """Build a synthetic intensity_lookup keyed on hour-aligned timestamps.

    Per-grid intensity values are deterministic but distinct across grids so
    that the destination loop has a non-trivial choice (otherwise stay vs
    migrate is degenerate)."""
    lookup = {}
    for i, g in enumerate(grids):
        # Different baselines per grid + small hourly variation. The exact
        # values don't matter for the regression assertions; we only need
        # the dict's keys to cover every hour-aligned timestamp the policy
        # might query so the fast path actually returns something non-None.
        baseline = 100.0 + 50.0 * i
        for h in range(hours):
            ts = BASE_TS + h * 3600
            lookup[(g, ts)] = baseline + (h % 5) * 1.5
    return lookup


def _install_recording_lookup():
    """Replace ``ph_module.lookup_intensity`` with a recorder. Returns
    ``(records, restore)``: ``records`` is a list of (grid, ts) tuples,
    ``restore`` is a zero-arg callable that puts the original back."""
    original = ph_module.lookup_intensity
    records = []

    def recorder(intensity_lookup, grid, sim_timestamp, strict=False):
        records.append((grid, sim_timestamp))
        return original(intensity_lookup, grid, sim_timestamp, strict=strict)

    ph_module.lookup_intensity = recorder

    def restore():
        ph_module.lookup_intensity = original

    return records, restore


def test_destination_loop_uses_hour_aligned_timestamps_short_migration():
    """For sub-hour migrations (mig_time_h < 0.5), the destination-loop
    offset must be exactly 0 -- every lookup_intensity call must land on
    BASE_TS + N * 3600 with N integer.

    With the bug present (offset_s = int(mig_time_h * 3600)), the offset is
    a few seconds and (ts - BASE_TS) % 3600 != 0 for every dest-loop call.
    With the fix (offset_s = int(round(mig_time_h)) * 3600), the offset is
    exactly 0 for sub-hour migrations.
    """
    grids = _pick_three_grids()
    current_grid = grids[0]
    intensity_lookup = _build_intensity_lookup(grids, hours=60)

    # Small app -- mig_time_h ~ 0.001 h (< 0.5), so round(mig_time_h) == 0.
    policy = HeuristicPolicy(
        app_size_mb=64.0,
        expected_total_minutes=2880,  # 48 h workload
        lookahead_hours=48,
    )

    records, restore = _install_recording_lookup()
    try:
        policy.decide(
            intensity_lookup,
            grids,
            current_grid,
            BASE_TS,
            remaining_hours=48,
            elapsed_hours=0.0,
        )
    finally:
        restore()

    assert records, "expected lookup_intensity to be called at least once"

    bad = [(g, ts) for (g, ts) in records if (ts - BASE_TS) % 3600 != 0]
    assert not bad, (
        f"lookup_intensity called with non-hour-aligned timestamps: "
        f"{bad[:5]} (total {len(bad)} of {len(records)})"
    )


def test_destination_loop_advances_one_hour_for_long_migration():
    """For migrations where mig_time_h >= 0.5 h, the destination-loop offset
    must advance by exactly 1 whole hour (3600 s) -- i.e. the smallest
    sim_timestamp passed for any destination grid is BASE_TS + 3600, NOT
    BASE_TS itself.

    Uses app_size_mb=200000.0 (200 GB) which yields mig_time_h ~ 0.7 h on
    the calibrated overhead model, regardless of which 3 grids are picked.
    If the chosen 3-grid combo somehow gives mig_time_h < 0.5 for ALL pairs,
    we skip with a soft message rather than fail (per the plan note).
    """
    grids = _pick_three_grids()
    current_grid = grids[0]
    intensity_lookup = _build_intensity_lookup(grids, hours=60)

    policy = HeuristicPolicy(
        app_size_mb=200000.0,
        expected_total_minutes=2880,
        lookahead_hours=48,
    )

    # Sanity-precondition: confirm at least one destination's mig_time_h
    # rounds to >= 1 h. If not, skip (soft per plan).
    from heuristics.hardware import get_hardware
    from heuristics.overhead import total_migration_time_h

    src_hw = get_hardware(current_grid)
    rounds_to_one_or_more = False
    for d in grids:
        if d == current_grid:
            continue
        if int(round(total_migration_time_h(200000.0, src_hw, get_hardware(d)))) >= 1:
            rounds_to_one_or_more = True
            break
    if not rounds_to_one_or_more:
        print(
            "SKIP: chosen grids do not produce a destination with "
            "round(mig_time_h) >= 1; soft-skip per plan note."
        )
        return

    records, restore = _install_recording_lookup()
    try:
        policy.decide(
            intensity_lookup,
            grids,
            current_grid,
            BASE_TS,
            remaining_hours=48,
            elapsed_hours=0.0,
        )
    finally:
        restore()

    assert records, "expected lookup_intensity to be called at least once"

    # Per-destination timestamps recorded during the destination loop.
    # The stay loop (current_grid) and the src/dst "now" lookups also feed
    # records, so filter to candidate-destination records only.
    dest_records = [
        (g, ts) for (g, ts) in records
        if g != current_grid and ts != BASE_TS
    ]
    assert dest_records, (
        "expected at least one destination-loop lookup with ts != BASE_TS"
    )

    # All recorded timestamps still must be hour-aligned regardless.
    bad = [(g, ts) for (g, ts) in records if (ts - BASE_TS) % 3600 != 0]
    assert not bad, f"non-hour-aligned timestamps leaked through: {bad[:5]}"

    # And specifically: at least one dest-loop record must land on
    # BASE_TS + 3600 (proving the offset is 3600, not 0 or some sub-hour
    # value). With offset = 1 h the very first iteration h=0 produces
    # BASE_TS + 3600.
    expected_first_offset_ts = BASE_TS + 3600
    found = any(ts == expected_first_offset_ts for (g, ts) in dest_records)
    assert found, (
        f"expected at least one destination-loop lookup at "
        f"BASE_TS + 3600 = {expected_first_offset_ts}; got "
        f"{sorted({ts for (_, ts) in dest_records})[:8]}"
    )


def test_all_lookup_timestamps_on_hourly_grid_for_full_simulation_window():
    """Strong property: across BOTH the stay loop and the destination loop,
    every lookup_intensity call from a Policy 6 decide() must hit the
    hourly grid. This is the must-have truth from the plan -- it directly
    drives the 107000x performance regression fix.
    """
    grids = _pick_three_grids()
    current_grid = grids[0]
    intensity_lookup = _build_intensity_lookup(grids, hours=60)

    policy = HeuristicPolicy(
        app_size_mb=64.0,
        expected_total_minutes=2880,
        lookahead_hours=48,
    )

    records, restore = _install_recording_lookup()
    try:
        policy.decide(
            intensity_lookup,
            grids,
            current_grid,
            BASE_TS,
            remaining_hours=48,
            elapsed_hours=0.0,
        )
    finally:
        restore()

    assert records, "expected lookup_intensity to be called at least once"
    assert all((ts - BASE_TS) % 3600 == 0 for (_, ts) in records), (
        "every (grid, ts) passed to lookup_intensity in a Policy 6 "
        "decide() call must be hour-aligned -- otherwise the dict fast "
        "path is missed and the O(N) fuzzy fallback is hit."
    )


if __name__ == "__main__":
    tests = [
        test_destination_loop_uses_hour_aligned_timestamps_short_migration,
        test_destination_loop_advances_one_hour_for_long_migration,
        test_all_lookup_timestamps_on_hourly_grid_for_full_simulation_window,
    ]
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as e:
            print(f"FAIL: {test.__name__} -- {e}")
            sys.exit(1)
    print(f"\nAll {len(tests)} hour-align regression tests passed.")
