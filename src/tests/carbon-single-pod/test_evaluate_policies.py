#!/usr/bin/env python3
"""Unit tests for evaluate_policies.py orchestrator (Phase 4).

Covers:
  - RunConfig is frozen (RESEARCH.md Pattern 2)
  - _ablation_id format per D-11 (HW{1|0}_OH{1|0}_DL{1|0})
  - simulate_one_run returns D-19 schema dict
  - Policy 1 baseline: zero migrations, zero savings
  - Ablation enumeration: exactly 8 cells per (timestamp, region) for sweep_kind=ablation
  - Horizon enumeration: exactly 7 lookahead_hours values per (timestamp, region) for sweep_kind=horizon
  - Data discipline: 2022 timestamps hard-blocked (D-23, RESEARCH.md Pitfall 5)
  - intensity_lookup filters 2022 rows at CSV-load time (D-23 belt+suspenders)

Mirrors src/tests/heuristics/test_policy_heuristic.py runner pattern (project convention,
no pytest).

Plan 03 has not yet shipped src/tests/carbon-single-pod/evaluate_policies.py, so every
test below imports from it inside the test body — that way ModuleNotFoundError surfaces
as a per-test ERROR (caught by the runner) rather than a top-level import failure that
prevents the runner from executing.
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
SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "sample_data"


def make_small_lookup(hours: int = 60):
    """Build a tiny intensity lookup for smoke testing (3 regions, `hours` hourly entries)."""
    lookup = {}
    for h in range(hours):
        ts = BASE_TS_2020 + h * 3600
        lookup[("NE", ts)] = 200.0 + (h % 24) * 5.0
        lookup[("TEN", ts)] = 300.0 - (h % 24) * 4.0
        lookup[("CENT", ts)] = 250.0 + (h % 12) * 3.0
    return lookup


def make_default_run_config(**overrides):
    """Build a RunConfig with sensible defaults for smoke tests.

    Imports RunConfig lazily because evaluate_policies.py ships in Plan 03.
    """
    from evaluate_policies import RunConfig  # noqa: WPS433
    base = dict(
        start_ts=BASE_TS_2020,
        source_region="NE",
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
        "policy", "source_region", "start_ts", "start_datetime",
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
    """generate_sweep(sweep_kind='ablation', single ts × single region) yields exactly 8 distinct cells (D-10, D-11)."""
    import argparse
    from evaluate_policies import generate_sweep, _ablation_id  # noqa: WPS433
    args = argparse.Namespace(
        sweep_kind="ablation",
        smoke=True,
        scheduler_time=BASE_TS_2020,
        source_regions=["NE"],
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
        f"Expected 8 ablation cells for 1 ts × 1 region, got {len(configs)}"
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
    """generate_sweep(sweep_kind='horizon', single ts × single region) yields exactly 7 lookahead_hours values (D-13)."""
    import argparse
    from evaluate_policies import generate_sweep  # noqa: WPS433
    args = argparse.Namespace(
        sweep_kind="horizon",
        smoke=True,
        scheduler_time=BASE_TS_2020,
        source_regions=["NE"],
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
        f"Expected 7 horizon configs for 1 ts × 1 region, got {len(configs)}"
    )
    horizons = {c.lookahead_hours for c in configs}
    assert horizons == {1, 2, 4, 8, 12, 24, 48}, (
        f"Expected D-13 horizons, got {horizons}"
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
    """Write a minimal sample-data-style CSV with (datetime, timestamp, carbon_intensity_direct_avg)."""
    import csv as _csv
    with open(path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["datetime", "timestamp", "carbon_intensity_direct_avg"])
        for row in rows:
            w.writerow(row)


def test_intensity_lookup_filters_2022():
    """build_intensity_lookup_from_csvs(include_years=(2020,2021)) must skip all 2022 entries.

    Builds a synthetic 3-region fixture in a tmp dir so the test does not depend
    on the real src/sample_data CSVs being present (WR-11). This both makes the
    test runnable from a sparse checkout and asserts that the 999.0 sentinel
    written for 2022 never makes it into the loaded lookup.
    """
    import tempfile
    from evaluate_policies import build_intensity_lookup_from_csvs  # noqa: WPS433

    with tempfile.TemporaryDirectory() as tmp:
        fake_dir = Path(tmp) / "sample_data"
        fake_dir.mkdir()
        # Sentinel 999.0 marks 2022 rows that MUST be filtered. 200.0 is the
        # canonical 2020 value; 250.0 is the canonical 2021 value.
        for region in ("CENT", "NE", "TEN"):
            _write_fake_intensity_csv(fake_dir / f"{region}.csv", [
                ("2020-01-01 00:00:00", 1577836800.0, 200.0),
                ("2021-06-15 12:00:00", 1623758400.0, 250.0),
                ("2022-06-01 00:00:00", 1654041600.0, 999.0),  # must be filtered out
            ])
        lookup = build_intensity_lookup_from_csvs(fake_dir, include_years=(2020, 2021))
        # Lookup must contain 2020+2021 entries but NOT 2022.
        assert lookup, "Expected non-empty lookup from fixture"
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
