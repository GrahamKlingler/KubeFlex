#!/usr/bin/env python3
"""Unit tests for HeuristicPolicy (Policy 6) and BasePolicy ABC enforcement.

Covers:
  - HEUR-05: forecast-based stay carbon (hardware-weighted intensity sum)
  - HEUR-06: stay-vs-migrate comparison with migration carbon cost
  - HEUR-07: hourly re-evaluation (no exceptions across multiple calls)
  - HEUR-08: deadline gate blocks migration near end of job

All tests use synthetic intensity_lookup fixtures to isolate policy logic from
database/forecast dependencies.
"""

import sys
from pathlib import Path

# Add heuristics package to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics.policy_heuristic import HeuristicPolicy
from heuristics.base import BasePolicy
from heuristics.hardware import HW_TABLE, get_hardware


# ── Fixtures ─────────────────────────────────────────────────────

BASE_TS = 1609459200  # 2021-01-01 00:00 UTC
REGIONS = ["NE", "TEN", "CENT"]


def make_uniform_intensity(ne_val, ten_val, cent_val, hours=50):
    """Create intensity_lookup with uniform values per region."""
    return {
        (r, BASE_TS + h * 3600): {"NE": ne_val, "TEN": ten_val, "CENT": cent_val}[r]
        for r in REGIONS
        for h in range(hours)
    }


# ── Test functions ────────────────────────────────────────────────

def test_base_policy_cannot_instantiate():
    """BasePolicy ABC should raise TypeError on direct instantiation."""
    raised = False
    try:
        BasePolicy()
    except TypeError:
        raised = True
    assert raised, "Expected TypeError when instantiating abstract BasePolicy"


def test_heuristic_policy_instantiates():
    """HeuristicPolicy constructor should succeed with expected default values."""
    p = HeuristicPolicy(app_size_mb=64.0, expected_total_minutes=2880)
    assert p.app_size_mb == 64.0, f"Expected app_size_mb=64.0, got {p.app_size_mb}"
    assert p.expected_total_minutes == 2880, f"Expected 2880, got {p.expected_total_minutes}"
    assert p.deadline_multiplier == 1.5, f"Expected deadline_multiplier=1.5, got {p.deadline_multiplier}"
    assert p.include_network_power is True, f"Expected include_network_power=True"
    assert p.last_skip_reason is None, f"Expected last_skip_reason=None initially"


def test_migrate_to_cheaper_region():
    """Policy should migrate from expensive region to cheapest hw-weighted region (HEUR-05, HEUR-06).

    Hardware-weighted scores:
      NE:   8.3 W/core  * 400 gCO2/kWh = 3320 per hour
      TEN:  16.25 W/core * 200 gCO2/kWh = 3250 per hour
      CENT: 3.5 W/core  * 300 gCO2/kWh = 1050 per hour  <- cheapest
    Starting in NE (score=3320), should migrate to CENT (score=1050).
    """
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=200.0, cent_val=300.0)
    p = HeuristicPolicy(app_size_mb=64.0, expected_total_minutes=2880)
    should, target = p.decide(intensity, REGIONS, "NE", BASE_TS, remaining_hours=48, elapsed_hours=0.0)
    assert should is True, "Expected migration recommendation from NE"
    # CENT has the lowest hw-weighted carbon
    assert target == "CENT", f"Expected CENT (lowest hw-weighted carbon), got {target}"


def test_stay_when_already_cheapest():
    """Policy should stay when current region is cheapest hw-weighted (HEUR-06).

    Hardware-weighted scores with all regions equal intensity (200 gCO2/kWh):
      NE:   8.3  * 200 = 1660
      TEN:  16.25 * 200 = 3250
      CENT: 3.5  * 200 = 700   <- cheapest
    Starting in CENT, should stay.
    """
    # All uniform at 200 to keep math simple; CENT (3.5 W/core) is cheapest
    intensity = make_uniform_intensity(ne_val=200.0, ten_val=200.0, cent_val=200.0)
    p = HeuristicPolicy(app_size_mb=64.0, expected_total_minutes=2880)
    should, target = p.decide(intensity, REGIONS, "CENT", BASE_TS, remaining_hours=48, elapsed_hours=0.0)
    # CENT has lowest power_per_core (3.5), so stay_carbon is already the minimum
    assert should is False, f"Expected no migration from cheapest region CENT, got should={should}, target={target}"
    assert target is None, f"Expected target=None when staying, got {target}"


def test_deadline_gate_blocks_near_completion():
    """Deadline gate should block all migrations when nearly at deadline (HEUR-08, D-17).

    Setup: expected_total_minutes=60, deadline_multiplier=1.0 -> deadline=1h.
    elapsed_hours=0.99 -> deadline_remaining = max(0, 1.0 - 0.99) = 0.01h.
    time_left_h = estimate_remaining_hours(60, 0.99, src_hw, src_hw) ~ 0.01h.
    Any positive mig_time_h > 0 will push time_left_h + mig_time_h > 0.01h,
    so all destinations should be blocked by the deadline gate.
    """
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=100.0, cent_val=50.0, hours=5)
    p = HeuristicPolicy(
        app_size_mb=64.0,
        expected_total_minutes=60,
        deadline_multiplier=1.0,
    )
    should, target = p.decide(
        intensity, REGIONS, "NE", BASE_TS, remaining_hours=1, elapsed_hours=0.99
    )
    assert should is False, f"Expected migration blocked by deadline gate, got should={should}, target={target}"
    assert p.last_skip_reason == "deadline_gate", (
        f"Expected last_skip_reason='deadline_gate', got '{p.last_skip_reason}'"
    )


def test_deadline_gate_allows_early_migration():
    """Deadline gate should allow migration when plenty of time remains (HEUR-08).

    Setup: expected_total_minutes=2880 (48h), deadline_multiplier=2.0 -> deadline=96h.
    elapsed_hours=0.0 -> deadline_remaining=96h. Migration time is seconds, well within budget.
    With NE at 400 gCO2/kWh vs CENT at 50 gCO2/kWh, migration should be allowed.
    """
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=200.0, cent_val=50.0)
    p = HeuristicPolicy(
        app_size_mb=64.0,
        expected_total_minutes=2880,
        deadline_multiplier=2.0,
    )
    should, target = p.decide(
        intensity, REGIONS, "NE", BASE_TS, remaining_hours=48, elapsed_hours=0.0
    )
    # With ample deadline and CENT much cheaper (50 vs 400), should migrate
    assert should is True, "Expected migration allowed with ample deadline and cheaper region available"


def test_network_power_toggle():
    """Both include_network_power=True and False should produce valid results (D-08)."""
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=200.0, cent_val=300.0)

    p_with_net = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, include_network_power=True
    )
    p_without_net = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, include_network_power=False
    )

    result_with = p_with_net.decide(intensity, REGIONS, "NE", BASE_TS, remaining_hours=48, elapsed_hours=0.0)
    result_without = p_without_net.decide(intensity, REGIONS, "NE", BASE_TS, remaining_hours=48, elapsed_hours=0.0)

    # Both should return valid (bool, str|None) tuples without crashing
    assert isinstance(result_with[0], bool), f"Expected bool for should_migrate, got {type(result_with[0])}"
    assert isinstance(result_without[0], bool), f"Expected bool for should_migrate, got {type(result_without[0])}"
    if result_with[1] is not None:
        assert result_with[1] in REGIONS, f"Expected valid region, got {result_with[1]}"
    if result_without[1] is not None:
        assert result_without[1] in REGIONS, f"Expected valid region, got {result_without[1]}"


def test_re_evaluation_across_hours():
    """Calling decide() 10 times with advancing sim_timestamp should produce no exceptions (HEUR-07)."""
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=200.0, cent_val=300.0, hours=60)
    p = HeuristicPolicy(app_size_mb=64.0, expected_total_minutes=2880)

    for i in range(10):
        ts = BASE_TS + i * 3600
        elapsed = float(i)
        result = p.decide(intensity, REGIONS, "NE", ts, remaining_hours=48 - i, elapsed_hours=elapsed)
        # Result must be a (bool, str|None) tuple
        assert isinstance(result, tuple) and len(result) == 2, (
            f"Hour {i}: Expected 2-tuple, got {result}"
        )
        assert isinstance(result[0], bool), f"Hour {i}: should_migrate must be bool, got {type(result[0])}"
        assert result[1] is None or isinstance(result[1], str), (
            f"Hour {i}: target_region must be str or None, got {type(result[1])}"
        )


# ── HEUR-10 / HEUR-11 ablation toggle tests (RED until Plan 01 ships) ──

def test_all_toggles_on_matches_baseline_phase3_behavior():
    """All 3 ablation toggles default to True -> bit-for-bit identical to current Policy 6 (HEUR-10, D-08).

    Verifies the safety invariant from D-08: introducing the hw_weighting/overhead_cost/deadline_gate
    toggles must NOT change behavior when all three default to True. Plan 01 will go GREEN
    by adding the kwargs with default=True and gating the affected lines in decide().
    """
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=200.0, cent_val=300.0)
    p_default = HeuristicPolicy(app_size_mb=64.0, expected_total_minutes=2880)
    p_explicit = HeuristicPolicy(
        app_size_mb=64.0,
        expected_total_minutes=2880,
        hw_weighting=True,
        overhead_cost=True,
        deadline_gate=True,
    )
    for h in range(48):
        ts = BASE_TS + h * 3600
        old = p_default.decide(intensity, REGIONS, "NE", ts, remaining_hours=48 - h, elapsed_hours=float(h))
        new = p_explicit.decide(intensity, REGIONS, "NE", ts, remaining_hours=48 - h, elapsed_hours=float(h))
        assert old == new, f"Hour {h}: default ({old}) != explicit-True ({new})"


def test_hw_weighting_off_drops_power_per_core():
    """hw_weighting=off -> stay/migrate carbon loops sum raw forecast intensity (HEUR-10, D-09).

    Hardware-weighted vs raw rankings differ for fixture (NE=400, TEN=200, CENT=300) with HW
    power_per_core (NE=8.3, TEN=16.25, CENT=3.5):
      - hw-weighted scores: NE=3320, TEN=3250, CENT=1050  -> CENT cheapest
      - raw scores:         NE=400,  TEN=200,  CENT=300   -> TEN cheapest
    Starting in NE: hw_weighting=True -> migrate to CENT; hw_weighting=False -> migrate to TEN.
    Asserts the chosen target_region differs between the two policies.
    """
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=200.0, cent_val=300.0)
    p_with_hw = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, hw_weighting=True
    )
    p_without_hw = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, hw_weighting=False
    )
    should_with, target_with = p_with_hw.decide(
        intensity, REGIONS, "NE", BASE_TS, remaining_hours=48, elapsed_hours=0.0
    )
    should_without, target_without = p_without_hw.decide(
        intensity, REGIONS, "NE", BASE_TS, remaining_hours=48, elapsed_hours=0.0
    )
    assert (should_with, target_with) != (should_without, target_without), (
        f"hw_weighting toggle should change the migration decision for this fixture; "
        f"with_hw=({should_with},{target_with}) without_hw=({should_without},{target_without})"
    )


def test_overhead_cost_off_zeros_migration_carbon():
    """overhead_cost=off -> migration_carbon = 0 (HEUR-10, D-09).

    With migration treated as free, any destination cheaper than the current region should
    cause a migration. Fixture: NE=200, TEN=199, CENT=199 (close margins). With overhead_cost=True
    the migration overhead may outweigh the tiny per-hour savings; with overhead_cost=False it
    cannot, so the two outcomes differ.
    """
    intensity = make_uniform_intensity(ne_val=200.0, ten_val=199.0, cent_val=199.0)
    p_with_overhead = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, overhead_cost=True
    )
    p_without_overhead = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, overhead_cost=False
    )
    result_with = p_with_overhead.decide(
        intensity, REGIONS, "CENT", BASE_TS, remaining_hours=48, elapsed_hours=0.0
    )
    result_without = p_without_overhead.decide(
        intensity, REGIONS, "CENT", BASE_TS, remaining_hours=48, elapsed_hours=0.0
    )
    assert result_with != result_without, (
        f"overhead_cost toggle should change behavior on close-margin fixture; "
        f"with_overhead={result_with} without_overhead={result_without}"
    )


def test_deadline_gate_off_skips_check():
    """deadline_gate=off -> last_skip_reason is never set to 'deadline_gate' (HEUR-10, D-09).

    Mirrors test_deadline_gate_blocks_near_completion fixture (expected_total_minutes=60,
    deadline_multiplier=1.0, elapsed_hours=0.99) but disables the deadline gate. The decide()
    call may still return (False, None) for other reasons, but it must NOT have set
    last_skip_reason to 'deadline_gate'.
    """
    intensity = make_uniform_intensity(ne_val=400.0, ten_val=100.0, cent_val=50.0, hours=5)
    p = HeuristicPolicy(
        app_size_mb=64.0,
        expected_total_minutes=60,
        deadline_multiplier=1.0,
        deadline_gate=False,
    )
    p.decide(intensity, REGIONS, "NE", BASE_TS, remaining_hours=1, elapsed_hours=0.99)
    assert p.last_skip_reason != "deadline_gate", (
        f"deadline_gate=False must skip the deadline check; "
        f"last_skip_reason={p.last_skip_reason!r}"
    )


def test_lookahead_hours_changes_decision_horizon():
    """lookahead_hours bound changes the cheap-destination decision (HEUR-11).

    Construct a 200h intensity profile where:
      - hours 0..3: NE cheap (100), TEN/CENT expensive (400)
      - hours 4..199: NE/TEN expensive (400), CENT cheap (100)
    Two policies with lookahead_hours=2 (only sees the early cheap-NE window) vs
    lookahead_hours=48 (sees the long cheap-CENT window). Starting in TEN, the two
    policies should reach different (should, target) outcomes.
    """
    intensity = {}
    for h in range(200):
        if h < 4:
            values = {"NE": 100.0, "TEN": 400.0, "CENT": 400.0}
        else:
            values = {"NE": 400.0, "TEN": 400.0, "CENT": 100.0}
        for r in REGIONS:
            intensity[(r, BASE_TS + h * 3600)] = values[r]

    p_short = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, lookahead_hours=2
    )
    p_long = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, lookahead_hours=48
    )
    short_result = p_short.decide(
        intensity, REGIONS, "TEN", BASE_TS, remaining_hours=48, elapsed_hours=0.0
    )
    long_result = p_long.decide(
        intensity, REGIONS, "TEN", BASE_TS, remaining_hours=48, elapsed_hours=0.0
    )
    assert short_result != long_result, (
        f"lookahead_hours bound should change the migration decision; "
        f"short(2h)={short_result} long(48h)={long_result}"
    )


# ── Runner ────────────────────────────────────────────────────────

def main():
    tests = [
        test_base_policy_cannot_instantiate,
        test_heuristic_policy_instantiates,
        test_migrate_to_cheaper_region,
        test_stay_when_already_cheapest,
        test_deadline_gate_blocks_near_completion,
        test_deadline_gate_allows_early_migration,
        test_network_power_toggle,
        test_re_evaluation_across_hours,
        test_all_toggles_on_matches_baseline_phase3_behavior,
        test_hw_weighting_off_drops_power_per_core,
        test_overhead_cost_off_zeros_migration_carbon,
        test_deadline_gate_off_skips_check,
        test_lookahead_hours_changes_decision_horizon,
    ]
    passed = 0
    failed = 0
    print(f"Running {len(tests)} HeuristicPolicy tests...")
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
