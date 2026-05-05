#!/usr/bin/env python3
"""Unit tests for evaluate_policies.py orchestrator (Phase 4).

Covers:
  - RunConfig is frozen (RESEARCH.md Pattern 2)
  - _ablation_id format per D-11 (HW{1|0}_OH{1|0}_DL{1|0})
  - simulate_one_run returns D-19 schema dict
  - Policy 1 baseline: zero migrations, zero savings
  - Ablation enumeration: exactly 8 cells per (timestamp, grid) for sweep_kind=ablation
  - Horizon enumeration: exactly 7 lookahead_hours values per (timestamp, grid) for sweep_kind=horizon
  - Data discipline: 2022 timestamps hard-blocked (D-23, RESEARCH.md Pitfall 5)
  - intensity_lookup filters 2022 rows at CSV-load time (D-23 belt+suspenders)

Mirrors src/tests/heuristics/test_policy_heuristic.py runner pattern (project convention,
no pytest).

Quick task 260502-i16: fixtures updated from region keys (NE/TEN/CENT) to grid keys
(ISNE/TVA/SWPP) to match the new grid-keyed expected-simulation path. The grids chosen
have HW_TABLE entries, so simulate_one_run() can hardware-cost them without KeyError.
"""

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

# Add controller package to import path (for heuristics)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
# Add carbon-single-pod directory to import path (for evaluate_policies)
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Note: imports of evaluate_policies are deferred into test bodies because that
# module ships in Plan 03; doing the import here would crash the entire runner.
from heuristics.data_splits import check_split_access  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────

BASE_TS_2020 = 1577836800  # 2020-01-01 00:00 UTC (train period)
BASE_TS_2022 = 1640995200  # 2022-01-01 00:00 UTC (test period — hard-blocked)

# 260502-i16: grids picked from data/hardware/hw_avg.csv (must have HW_TABLE entries
# so simulate_one_run() can compute hardware-weighted carbon without KeyError).
FIXTURE_GRIDS = ("ISNE", "TVA", "SWPP")
DEFAULT_SOURCE_GRID = "ISNE"


def make_small_lookup(hours: int = 60):
    """Build a tiny intensity lookup for smoke testing (3 grids, `hours` hourly entries).

    Uses grid identifiers (ISNE/TVA/SWPP) per quick task 260502-i16. The values are
    designed so the time-of-day pattern produces non-trivial migration decisions.
    """
    lookup = {}
    for h in range(hours):
        ts = BASE_TS_2020 + h * 3600
        lookup[("ISNE", ts)] = 200.0 + (h % 24) * 5.0
        lookup[("TVA", ts)] = 300.0 - (h % 24) * 4.0
        lookup[("SWPP", ts)] = 250.0 + (h % 12) * 3.0
    return lookup


def make_default_run_config(**overrides):
    """Build a RunConfig with sensible defaults for smoke tests.

    Imports RunConfig lazily because evaluate_policies.py ships in Plan 03.
    """
    from evaluate_policies import RunConfig  # noqa: WPS433
    base = dict(
        start_ts=BASE_TS_2020,
        source_grid=DEFAULT_SOURCE_GRID,
        policy_id=6,
    )
    base.update(overrides)
    return RunConfig(**base)


# ── Test functions ────────────────────────────────────────────────

def test_run_config_is_frozen():
    """RunConfig must be a frozen dataclass — mutation raises FrozenInstanceError (RESEARCH.md Pattern 2)."""
    cfg = make_default_run_config()
    raised = False
    try:
        cfg.policy_id = 99  # type: ignore[misc]
    except FrozenInstanceError:
        raised = True
    assert raised, "RunConfig must be @dataclass(frozen=True)"


def test_ablation_id_format_default():
    """_ablation_id of an all-True RunConfig must be 'HW1_OH1_DL1' (D-11)."""
    from evaluate_policies import _ablation_id  # noqa: WPS433
    cfg = make_default_run_config()
    got = _ablation_id(cfg)
    assert got == "HW1_OH1_DL1", f"Expected 'HW1_OH1_DL1', got {got!r}"


def test_ablation_id_format_all_off():
    """_ablation_id of an all-False RunConfig must be 'HW0_OH0_DL0' (D-11)."""
    from evaluate_policies import _ablation_id  # noqa: WPS433
    cfg = make_default_run_config(
        hw_weighting=False, overhead_cost=False, deadline_gate=False
    )
    got = _ablation_id(cfg)
    assert got == "HW0_OH0_DL0", f"Expected 'HW0_OH0_DL0', got {got!r}"


def test_simulate_one_run_returns_d19_schema():
    """simulate_one_run must return a dict with every D-19 schema key."""
    from evaluate_policies import simulate_one_run, _init_worker  # noqa: WPS433
    expected_keys = {
        "policy", "source_grid", "start_ts", "start_datetime",
        "hw_weighting", "overhead_cost", "deadline_gate", "ablation_id", "lookahead_hours",
        "app_size_mb", "expected_completion_min", "deadline_multiplier",
        "total_carbon_gco2", "baseline_carbon_gco2", "savings_pct",
        "migration_count", "completed_hours", "sweep_kind",
    }
    lookup = make_small_lookup(hours=60)
    _init_worker(lookup)
    cfg = make_default_run_config(expected_completion_min=120)  # 2-hour run for speed
    result = simulate_one_run(cfg)
    missing = expected_keys - set(result.keys())
    assert not missing, f"Missing D-19 schema keys: {missing}"


def test_policy1_baseline_zero_savings():
    """Policy 1 (no-migration baseline) must report 0 migrations and ~0% savings."""
    from evaluate_policies import simulate_one_run, _init_worker  # noqa: WPS433
    lookup = make_small_lookup(hours=60)
    _init_worker(lookup)
    cfg = make_default_run_config(policy_id=1, expected_completion_min=120)
    result = simulate_one_run(cfg)
    assert result["migration_count"] == 0, (
        f"Policy 1 must have 0 migrations, got {result['migration_count']}"
    )
    sp = float(result["savings_pct"])
    assert abs(sp) < 1e-6, f"Policy 1 baseline savings_pct must be ~0, got {sp}"


def test_ablation_cell_enumeration_eight_cells():
    """generate_sweep(sweep_kind='ablation', single ts × single grid) yields exactly 8 distinct cells (D-10, D-11)."""
    import argparse
    from evaluate_policies import generate_sweep, _ablation_id  # noqa: WPS433
    args = argparse.Namespace(
        sweep_kind="ablation",
        smoke=True,
        scheduler_time=BASE_TS_2020,
        source_grids=[DEFAULT_SOURCE_GRID],
        source_regions=None,  # deprecated alias not used here
        timestamps=[BASE_TS_2020],
        app_size_mb=64.0,
        expected_completion_min=2880,
        expected_migration_min=5,
        deadline_multiplier=1.5,
        lookahead_hours=48,
        include_network_power=True,
    )
    configs = list(generate_sweep(args))
    assert len(configs) == 8, (
        f"Expected 8 ablation cells for 1 ts × 1 grid, got {len(configs)}"
    )
    ablation_ids = {_ablation_id(c) for c in configs}
    expected = {
        f"HW{hw}_OH{oh}_DL{dl}"
        for hw in (0, 1)
        for oh in (0, 1)
        for dl in (0, 1)
    }
    assert ablation_ids == expected, f"Expected {expected}, got {ablation_ids}"


def test_horizon_sweep_seven_values():
    """generate_sweep(sweep_kind='horizon', single ts × single grid) yields exactly 7 lookahead_hours values (D-13)."""
    import argparse
    from evaluate_policies import generate_sweep  # noqa: WPS433
    args = argparse.Namespace(
        sweep_kind="horizon",
        smoke=True,
        scheduler_time=BASE_TS_2020,
        source_grids=[DEFAULT_SOURCE_GRID],
        source_regions=None,  # deprecated alias not used here
        timestamps=[BASE_TS_2020],
        app_size_mb=64.0,
        expected_completion_min=2880,
        expected_migration_min=5,
        deadline_multiplier=1.5,
        lookahead_hours=48,
        include_network_power=True,
    )
    configs = list(generate_sweep(args))
    assert len(configs) == 7, (
        f"Expected 7 horizon configs for 1 ts × 1 grid, got {len(configs)}"
    )
    horizons = {c.lookahead_hours for c in configs}
    assert horizons == {1, 2, 4, 8, 12, 24, 48}, (
        f"Expected D-13 horizons, got {horizons}"
    )


def test_main_sweep_smoke_overrides_completion_min():
    """generate_sweep(sweep_kind='main', smoke=True) must lift expected_completion_min
    to >= max(HORIZON_VALUES)*60 so policies 2-6 do not collapse over a 2-hour sim."""
    import argparse
    from evaluate_policies import generate_sweep, HORIZON_VALUES  # noqa: WPS433
    args = argparse.Namespace(
        sweep_kind="main",
        smoke=True,
        scheduler_time=BASE_TS_2020,
        source_grids=[DEFAULT_SOURCE_GRID],
        source_regions=None,
        timestamps=[BASE_TS_2020],
        app_size_mb=64.0,
        expected_completion_min=2880,
        expected_migration_min=5,
        deadline_multiplier=1.5,
        lookahead_hours=48,
        include_network_power=True,
    )
    configs = list(generate_sweep(args))
    assert configs, "Expected non-empty main smoke sweep"
    floor = max(HORIZON_VALUES) * 60  # 2880 minutes
    offending = [c.expected_completion_min for c in configs if c.expected_completion_min < floor]
    assert not offending, (
        f"main smoke cfgs must have expected_completion_min >= {floor}, "
        f"got offending values {sorted(set(offending))}"
    )


def test_ablation_sweep_smoke_overrides_completion_min():
    """generate_sweep(sweep_kind='ablation', smoke=True) must lift
    expected_completion_min to >= max(HORIZON_VALUES)*60 so the 8 ablation cells
    differ over a long-enough sim horizon."""
    import argparse
    from evaluate_policies import generate_sweep, HORIZON_VALUES  # noqa: WPS433
    args = argparse.Namespace(
        sweep_kind="ablation",
        smoke=True,
        scheduler_time=BASE_TS_2020,
        source_grids=[DEFAULT_SOURCE_GRID],
        source_regions=None,
        timestamps=[BASE_TS_2020],
        app_size_mb=64.0,
        expected_completion_min=2880,
        expected_migration_min=5,
        deadline_multiplier=1.5,
        lookahead_hours=48,
        include_network_power=True,
    )
    configs = list(generate_sweep(args))
    assert len(configs) == 8, (
        f"Expected 8 ablation cells in smoke mode, got {len(configs)}"
    )
    floor = max(HORIZON_VALUES) * 60
    offending = [c.expected_completion_min for c in configs if c.expected_completion_min < floor]
    assert not offending, (
        f"ablation smoke cfgs must have expected_completion_min >= {floor}, "
        f"got offending values {sorted(set(offending))}"
    )


def test_2022_timestamp_hard_block():
    """check_split_access on a 2022 timestamp must raise RuntimeError (D-23)."""
    raised = False
    try:
        check_split_access(BASE_TS_2022)
    except RuntimeError:
        raised = True
    assert raised, f"Expected RuntimeError for 2022 timestamp {BASE_TS_2022}"


def _write_fake_intensity_csv(path, rows):
    """Write a minimal regions-tree-style CSV with (datetime, timestamp, carbon_intensity_direct_avg)."""
    import csv as _csv
    with open(path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["datetime", "timestamp", "carbon_intensity_direct_avg"])
        for row in rows:
            w.writerow(row)


def test_intensity_lookup_filters_2022():
    """build_intensity_lookup_from_regions_tree(include_years=(2020,2021)) must skip all 2022 entries.

    Builds a synthetic regions-tree fixture in a tmp dir so the test does not depend
    on the real data/regions/ CSVs being present (WR-11). The fixture mirrors the
    on-disk layout: tmp/regions/{REGION}/US-{REGION}-{GRID}.csv. The 999.0 sentinel
    written for 2022 must never appear in the loaded lookup.
    """
    import tempfile
    from evaluate_policies import build_intensity_lookup_from_regions_tree  # noqa: WPS433

    # 260502-i16: grid stems are derived as the trailing dash-separated segment
    # of the file stem, so US-NE-ISNE.csv -> grid "ISNE". The (region, grid) pairs
    # below are real KubeFlex grids with HW_TABLE entries.
    region_grid_pairs = [
        ("NE", "ISNE"),
        ("TEN", "TVA"),
        ("CENT", "SWPP"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        regions_root = Path(tmp) / "regions"
        for region, grid in region_grid_pairs:
            region_dir = regions_root / region
            region_dir.mkdir(parents=True)
            # Sentinel 999.0 marks 2022 rows that MUST be filtered. 200.0 is the
            # canonical 2020 value; 250.0 is the canonical 2021 value.
            _write_fake_intensity_csv(region_dir / f"US-{region}-{grid}.csv", [
                ("2020-01-01 00:00:00", 1577836800.0, 200.0),
                ("2021-06-15 12:00:00", 1623758400.0, 250.0),
                ("2022-06-01 00:00:00", 1654041600.0, 999.0),  # must be filtered out
            ])
        lookup = build_intensity_lookup_from_regions_tree(
            regions_root, include_years=(2020, 2021),
        )
        # Lookup must contain 2020+2021 entries but NOT 2022.
        assert lookup, "Expected non-empty lookup from fixture"
        # Keys must be (grid, ts) tuples with grid identifiers, not regions.
        loaded_grids = {g for (g, _ts) in lookup.keys()}
        assert loaded_grids == {"ISNE", "TVA", "SWPP"}, (
            f"Expected grid keys {{ISNE, TVA, SWPP}}, got {loaded_grids}"
        )
        max_ts = max(ts for (_, ts) in lookup.keys())
        assert max_ts < BASE_TS_2022, (
            f"Lookup contains 2022 data: max_ts={max_ts} >= {BASE_TS_2022}"
        )
        assert not any(v == 999.0 for v in lookup.values()), (
            "2022 sentinel value 999.0 leaked into lookup despite include_years=(2020, 2021)"
        )


# ── Runner ────────────────────────────────────────────────────────

def main():
    tests = [
        test_run_config_is_frozen,
        test_ablation_id_format_default,
        test_ablation_id_format_all_off,
        test_simulate_one_run_returns_d19_schema,
        test_policy1_baseline_zero_savings,
        test_ablation_cell_enumeration_eight_cells,
        test_horizon_sweep_seven_values,
        test_main_sweep_smoke_overrides_completion_min,
        test_ablation_sweep_smoke_overrides_completion_min,
        test_2022_timestamp_hard_block,
        test_intensity_lookup_filters_2022,
    ]
    passed = 0
    failed = 0
    print(f"Running {len(tests)} evaluate_policies tests...")
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
