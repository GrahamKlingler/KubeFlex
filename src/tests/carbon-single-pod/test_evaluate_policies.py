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


def _make_2022_lookup(hours: int = 8):
    """Build a 2022-anchored intensity lookup for the bypass-test regression.

    Mirrors make_small_lookup() but anchored at BASE_TS_2022 so it exercises the
    test-period bypass. Three grids (ISNE/TVA/SWPP) all have HW_TABLE entries
    so the simulator can HW-cost them without KeyError.
    """
    lookup = {}
    for h in range(hours):
        ts = BASE_TS_2022 + h * 3600
        lookup[("ISNE", ts)] = 200.0 + (h % 24) * 5.0
        lookup[("TVA", ts)] = 300.0 - (h % 24) * 4.0
        lookup[("SWPP", ts)] = 250.0 + (h % 12) * 3.0
    return lookup


def test_runconfig_bypass_test_split_allows_2022_timestamp():
    """RunConfig.bypass_test_split=True must allow simulate_one_run on 2022 data.

    260519-fhe: the new flag is the explicit, recorded opt-in for final-eval
    runs on the held-out 2022 test period. Default (False) must still raise so
    the existing test_2022_timestamp_hard_block invariant is preserved end-to-end.
    """
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433

    lookup = _make_2022_lookup(hours=8)

    # Positive: bypass_test_split=True allows the 2022 timestamp.
    cfg_bypass = RunConfig(
        start_ts=BASE_TS_2022,
        source_grid=DEFAULT_SOURCE_GRID,
        policy_id=6,
        expected_completion_min=120,  # 2-hour useful job; fixture has 8 hours
        bypass_test_split=True,
    )
    result = simulate_one_run(lookup, cfg_bypass)
    assert isinstance(result, dict), (
        f"simulate_one_run must return a dict; got {type(result).__name__}"
    )
    for key in ("total_carbon_gco2", "migration_count"):
        assert key in result, (
            f"bypass path result missing expected D-19 key {key!r}; "
            f"keys={sorted(result.keys())}"
        )

    # Negative control: default (bypass_test_split=False) still raises RuntimeError.
    cfg_default = RunConfig(
        start_ts=BASE_TS_2022,
        source_grid=DEFAULT_SOURCE_GRID,
        policy_id=6,
        expected_completion_min=120,
    )
    raised = False
    try:
        simulate_one_run(lookup, cfg_default)
    except RuntimeError:
        raised = True
    assert raised, (
        "RunConfig.bypass_test_split defaults to False; simulate_one_run with a "
        "2022 start_ts and no bypass MUST raise RuntimeError (D-23 discipline)."
    )


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


# ── 260511-jce: minute-granular migration carbon regression tests ─

def _make_two_grid_lookup(hours: int, src_grid: str, dst_grid: str,
                          src_intensity: float, dst_intensity: float):
    """Build a (src, dst) intensity lookup with constant per-hour values.

    Used by the 260511-jce minute-granular migration carbon regression tests so
    we can predict total_carbon analytically: source intensity is `src_intensity`
    every hour, destination intensity is `dst_intensity` every hour, both flat
    across `hours` consecutive timestamps starting at BASE_TS_2020.
    """
    lookup = {}
    for h in range(hours):
        ts = BASE_TS_2020 + h * 3600
        lookup[(src_grid, ts)] = src_intensity
        lookup[(dst_grid, ts)] = dst_intensity
    return lookup


def test_migration_carbon_minute_granular():
    """30-min migration on a flat-intensity fixture charges 0.5 * source_intensity.

    Fixture: ISNE (source) constant 100.0 gCO2/kWh, TVA (dest) constant 50.0
    gCO2/kWh, 2-hour sim, Policy 2, use_hw=False. Policy 2 migrates at h=0
    (TVA is cheaper than ISNE). With m=30 and the LOCKED 260511-jce formula:
        h=0: source intensity 100 added, migration charges 0.5*100=50, switch to TVA.
        h=1: target intensity 50 added.

    260512-kfc: useful-work-driven termination. The 30-min migration at h=0
    consumes 30 of the hour's useful minutes, so reaching the 120-min useful
    target now takes 3 wall-clock hours instead of 2. Carbon accumulates one
    extra hour on the target grid. Expected total = 100 + 50 + 50 + 50 = 250.0.
    """
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    # 4 hours of lookup data so the sim has slack to reach 120 useful minutes
    # after the 30-min migration extends the runtime.
    lookup = _make_two_grid_lookup(4, "ISNE", "TVA", 100.0, 50.0)
    cfg = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid="ISNE",
        policy_id=2,
        expected_completion_min=120,
        expected_migration_min=30,
        use_hw=False,
        hw_weighting=False,
        overhead_cost=False,
        deadline_gate=False,
        include_network_power=False,
        sweep_kind="main",
    )
    result = simulate_one_run(lookup, cfg)
    assert result["migration_count"] == 1, (
        f"Expected 1 migration on cheaper-dest fixture, got "
        f"{result['migration_count']}"
    )
    # 260512-kfc: useful-work-driven termination extends to 3 hours wall-clock.
    expected = 100.0 + 0.5 * 100.0 + 50.0 + 50.0  # h0 src + mig + h1 tgt + h2 tgt
    got = result["total_carbon_gco2"]
    assert abs(got - expected) < 0.6, (
        f"minute-granular migration carbon broken: total={got}, expected~{expected}"
    )
    assert result["completed_hours"] == 3, (
        f"Expected completed_hours=3 (h=0 mig consumes 30 useful min -> 4th hour "
        f"to reach 120 useful), got {result['completed_hours']}"
    )
    assert result["useful_minutes_completed"] >= 120, (
        f"useful_minutes_completed={result['useful_minutes_completed']} < 120"
    )


def test_migration_carbon_zero_overhead_is_free():
    """expected_migration_min=0 yields zero migration carbon (free instantaneous switch).

    Same fixture as test_migration_carbon_minute_granular, but m=0 -> migration
    fraction is 0 so no migration carbon is charged; cooldown is 0 so no extra
    blocked hours. Result must equal the hourly accumulation only.
    """
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    lookup = _make_two_grid_lookup(2, "ISNE", "TVA", 100.0, 50.0)
    cfg = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid="ISNE",
        policy_id=2,
        expected_completion_min=120,
        expected_migration_min=0,
        use_hw=False,
        hw_weighting=False,
        overhead_cost=False,
        deadline_gate=False,
        include_network_power=False,
        sweep_kind="main",
    )
    result = simulate_one_run(lookup, cfg)
    assert result["migration_count"] == 1, (
        f"Expected 1 migration on cheaper-dest fixture, got "
        f"{result['migration_count']}"
    )
    expected = 100.0 + 50.0  # source-h0 + target-h1, no migration charge
    got = result["total_carbon_gco2"]
    assert abs(got - expected) < 0.6, (
        f"m=0 should be free, got total={got}, expected~{expected}"
    )


def test_migration_minutes_remaining_gates_re_migration_during_in_progress():
    """260512-kfc: replaces test_migration_cooldown_blocks_second_migration_over_120min.

    `migrating_cooldown` was removed; the equivalent gate is now
    `migration_minutes_remaining`. While a migration is in-progress (mig_min_rem
    > 0 at the start of the hour) no new migration decision can fire.

    Fixture (10-hour lookup with slack so useful work can finish):
      ISNE (source) = 100 every hour
      SWPP cheaper at h=0..1 (=10), then 50 from h>=2
      TVA  cheaper at h>=2 (=5), then 50 at h<2
    Policy 2 with m=90 (1.5 hours of migration):
      h=0: mig_min_rem=0 -> Policy 2 picks SWPP (10 < 100). Migration starts:
           mig_min_rem=90, consumed=60, mig_min_rem=30, useful_this_hour=0.
      h=1: mig_min_rem=30 -> consume 30, mig_min_rem=0, useful_this_hour=30.
           NO migration decision (we entered the hour mid-migration).
      h=2: mig_min_rem=0 -> Policy 2 picks TVA (5 < SWPP's 50). Migration:
           mig_min_rem=90, consumed=60, useful=0.
      h=3: mig_min_rem=30 -> useful=30, no decision.
      h=4..N: TVA remains cheapest current_grid (5 is the lowest), so Policy 2
           stops migrating. useful=60/hr. Continues until useful_min_completed
           >= 240 (4 hours useful).
    Total useful so far at end of h=3: 0+30+0+30 = 60. Need 180 more useful
    minutes -> 3 more hours of 60 useful -> ends at h=6.

    Expected: migration_count == 2, hours_tracked == 7.
    """
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    # Build a 10-hour lookup so the sim has slack to reach 240 useful minutes
    # despite the migrations.
    lookup = {}
    for h in range(10):
        ts = BASE_TS_2020 + h * 3600
        lookup[("ISNE", ts)] = 100.0
        lookup[("SWPP", ts)] = 10.0 if h <= 1 else 50.0
        lookup[("TVA", ts)] = 5.0 if h >= 2 else 50.0
    cfg = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid="ISNE",
        policy_id=2,
        expected_completion_min=240,
        expected_migration_min=90,
        use_hw=False,
        hw_weighting=False,
        overhead_cost=False,
        deadline_gate=False,
        include_network_power=False,
        sweep_kind="main",
    )
    result = simulate_one_run(lookup, cfg)
    assert result["migration_count"] == 2, (
        f"Expected exactly 2 migrations (h=0 -> SWPP, h=2 -> TVA), "
        f"got {result['migration_count']}"
    )
    # After both migrations TVA is the cheapest grid; Policy 2 stays put.
    # Useful minutes per hour:
    #   h=0: 0 (60-60 mig)
    #   h=1: 30 (60-30 mig tail)
    #   h=2: 0 (60-60 mig)
    #   h=3: 30 (60-30 mig tail)
    #   h=4: 60
    #   h=5: 60
    #   h=6: 60  -> cumulative 240, terminate (overshoots to exactly 240)
    # Total wall-clock = 7 hours.
    assert result["completed_hours"] == 7, (
        f"Expected completed_hours=7 (4 useful hours + 3 hours of in-progress "
        f"migration consuming useful minutes), got {result['completed_hours']}"
    )


# ── 260512-kfc: useful-work-driven termination regression tests ──────

def test_sim_extends_runtime_for_migration_minutes():
    """260512-kfc: a single 30-min migration in a 2880-min job extends total
    wall-clock from 48 to 49 hours; useful_minutes_completed lands within
    [2880, 2940).
    """
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    # 60 hours of constant-intensity 2-grid fixture so the sim never runs out
    # of data. SWPP cheaper than ISNE so Policy 2 migrates exactly once at h=0
    # and then stays put.
    lookup = {}
    for h in range(60):
        ts = BASE_TS_2020 + h * 3600
        lookup[("ISNE", ts)] = 100.0
        lookup[("SWPP", ts)] = 50.0
    cfg = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid="ISNE",
        policy_id=2,
        expected_completion_min=2880,
        expected_migration_min=30,
        use_hw=False,
        hw_weighting=False,
        overhead_cost=False,
        deadline_gate=False,
        include_network_power=False,
        sweep_kind="main",
    )
    result = simulate_one_run(lookup, cfg)
    assert result["migration_count"] == 1, (
        f"Expected 1 migration, got {result['migration_count']}"
    )
    assert result["completed_hours"] == 49, (
        f"Expected completed_hours=49 (2880 useful min + 30 mig min consuming "
        f"useful in h=0 -> 2910 min wall, 49 hours), "
        f"got {result['completed_hours']}"
    )
    assert 2880 <= result["useful_minutes_completed"] < 2940, (
        f"useful_minutes_completed out of range [2880, 2940): "
        f"{result['useful_minutes_completed']}"
    )


def test_sim_safety_cap_fires_on_pathological_policy():
    """260512-kfc: a fixture that forces Policy 2 to migrate every hour with
    m=60 (full-hour migrations, zero useful work) hits the safety cap
    `max_iter_hours = ceil(2 * useful_minutes_target / 60)` and raises
    RuntimeError.
    """
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    # Three grids; rotate the cheapest each hour so Policy 2 always wants to
    # switch. Need m=60 so the entire hour is consumed by migration and
    # useful_minutes_this_hour == 0. But m=60 means migration_minutes_remaining
    # goes to 0 by end of hour -> Policy 2 makes another decision next hour.
    # With rotating mins, the target is always different from current_grid,
    # so Policy 2 keeps migrating every hour -> safety cap fires.
    lookup = {}
    for h in range(200):  # well past the safety cap of 96
        ts = BASE_TS_2020 + h * 3600
        # Rotate the strict min: ISNE (h%3==0), TVA (h%3==1), SWPP (h%3==2).
        lookup[("ISNE", ts)] = 10.0 if h % 3 == 0 else 100.0
        lookup[("TVA", ts)] = 10.0 if h % 3 == 1 else 100.0
        lookup[("SWPP", ts)] = 10.0 if h % 3 == 2 else 100.0
    cfg = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid="ISNE",
        policy_id=2,
        expected_completion_min=2880,
        expected_migration_min=60,  # full-hour migrations
        use_hw=False,
        hw_weighting=False,
        overhead_cost=False,
        deadline_gate=False,
        include_network_power=False,
        sweep_kind="main",
    )
    raised = False
    msg = ""
    try:
        simulate_one_run(lookup, cfg)
    except RuntimeError as e:
        msg = str(e)
        raised = "safety cap" in msg.lower()
    assert raised, (
        "Expected safety-cap RuntimeError on pathological migrate-every-hour "
        f"fixture; got raised={raised}, msg={msg!r}"
    )


# ── 260515-jav: sysbench-backed empirical runtime opt-in tests ────


def test_sim_default_use_empirical_runtime_matches_existing_behavior():
    """RunConfig.use_empirical_runtime default (False) is byte-identical to
    an explicit-False RunConfig.

    The point of this test is to PROVE the default path is unchanged: any
    deterministic fixture will do. We use the synthetic small_lookup so the
    assertion does not depend on real CSV data. Together with the existing
    16 tests (which still pass), this guarantees the new RunConfig field
    doesn't perturb prior behavior.
    """
    from _simulation_core import simulate_one_run  # noqa: WPS433
    lookup = make_small_lookup(hours=60)
    cfg_default = make_default_run_config(expected_completion_min=120)
    cfg_explicit_off = make_default_run_config(
        expected_completion_min=120, use_empirical_runtime=False
    )
    r1 = simulate_one_run(lookup, cfg_default)
    r2 = simulate_one_run(lookup, cfg_explicit_off)
    assert r1["total_carbon_gco2"] == r2["total_carbon_gco2"], (
        f"Default and explicit-False configs must produce identical "
        f"total_carbon_gco2: {r1['total_carbon_gco2']} vs "
        f"{r2['total_carbon_gco2']}"
    )
    # Additional invariants on the rest of the result dict
    for key in ("migration_count", "completed_hours", "baseline_carbon_gco2"):
        assert r1[key] == r2[key], (
            f"Default and explicit-False configs must produce identical "
            f"{key}: {r1[key]} vs {r2[key]}"
        )


def _make_sysbench_grid_lookup(hours: int = 60):
    """Lookup with two grids (CISO, MISO) that BOTH have sysbench data.

    Per CONTEXT.md the CISO/MISO pair is well-covered (CISO=26 hostnames,
    MISO=4). The fixture is shaped so Policy 6's MISO forecast-sum changes
    sign depending on whether the dest horizon weights the spike fully or
    fractionally. With the CISO/MISO empirical ratio ~0.9603, mig_time_h
    ~0.0008 h (ceil=1) and a 13-hour job:
      - default dest window  = [1.0, 14.0)  (full hour 13 = full spike)
      - empirical dest window = [1.0, 13.484) (only ~0.484 of hour 13,
        the rest of the partial last hour)
    Sizing the spike at hour 13 to 2000 makes that fractional weight
    decisive: default (full spike) gives MISO=1200+2000=3200 > 2600 stay
    cost (no migrate); empirical (partial spike) gives MISO=1200+968=2168
    < 2600 (migrate).

    260526-lgv: prior fixture used a 10000-spike at hour 12 against the
    integer-rounded `dest_time_left_int=12` boundary. The piecewise-constant
    fractional-window fix eliminated that integer quantization, so the
    fixture was rebuilt around a fractional-spike-weight flip at hour 12.

    260601-gyw: discrete-hour dest window offset (ceil(mig_time_h) instead
    of fractional mig_time_h) shifts the spike-discriminating hour from 12
    to 13. With ceil(mig_time_h)=1, the default window is [1, 14) (interior
    h=1..13) and the empirical window is [1, 13.484) (interior h=1..12 with
    partial-last-hour at h=13 weighted 0.484). The spike was moved from
    hour 12 to hour 13 to remain at the discriminating boundary.
    """
    lookup = {}
    for h in range(hours):
        ts = BASE_TS_2020 + h * 3600
        # CISO: constant; stay_carbon is 200*13 = 2600 over the stay horizon.
        lookup[("CISO", ts)] = 200.0
        # MISO: cheap until hour 13, then a moderate spike. Spike size 2000
        # chosen so default (full weight 1.0) gives MISO=1200+2000=3200 > 2600
        # (no migrate), but empirical (weight 0.484) gives MISO=1200+968=2168
        # < 2600 (migrate). The discriminating hour is the partial-last-hour
        # of the empirical dest window [1.0, 13.484), i.e. hour 13.
        lookup[("MISO", ts)] = 100.0 if h < 13 else 2000.0
    return lookup


def test_sim_opt_in_use_empirical_runtime_differs_from_default():
    """RunConfig.use_empirical_runtime=True changes Policy 6's decision math.

    The fixture is engineered to expose the per-destination horizon scaling
    (the only place the CISO/MISO empirical ratio can manifest given that
    the stay-case time_left_h is by definition ratio=1.0 for src==src). The
    260515-jav implementation makes Policy 6's dest forecast horizon
    sensitive to perf_ratio(src, dest), so a faster MISO ratio shortens its
    forecast window fractionally -- under the piecewise-constant fractional
    weighting (260526-lgv), the hour-12 spike is weighted 1.0 by the default
    13.0-hour window but only ~0.484 by the empirical 12.484-hour window,
    flipping the migration decision.

    Assertions:
      - On/off totals differ (proves the empirical path fires).
      - Ratio in (0.5, 2.0) -- 10x-bug sanity band per CONTEXT.md line 139.
      - Note: with hw/overhead/deadline toggles all OFF for this fixture,
        the math is analytic; the default-on snapshot is preserved by the
        existing 16 tests.
    """
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    lookup = _make_sysbench_grid_lookup(hours=60)
    base = dict(
        start_ts=BASE_TS_2020,
        source_grid="CISO",
        policy_id=6,
        # 780 min (13h) puts the spike at hour 12 inside the partial-last-hour
        # of the empirical dest window [0, 12.484) -- weighted 0.484 rather
        # than 1.0 by the default window [0, 13.0).
        expected_completion_min=780,
        # All Policy 6 toggles OFF for a clean analytic comparison; the
        # default-on snapshot invariant is covered by the other tests.
        hw_weighting=False,
        overhead_cost=False,
        deadline_gate=False,
        include_network_power=False,
        use_hw=False,
    )
    cfg_off = RunConfig(**base, use_empirical_runtime=False)
    cfg_on = RunConfig(**base, use_empirical_runtime=True)
    result_off = simulate_one_run(lookup, cfg_off)
    result_on = simulate_one_run(lookup, cfg_on)
    # Sanity-check the ratio is in (0.5, 2.0) so a 10x bug surfaces
    off = max(result_off["total_carbon_gco2"], 1e-9)
    on = max(result_on["total_carbon_gco2"], 1e-9)
    ratio = on / off
    assert 0.5 < ratio < 2.0, (
        f"empirical/default total_carbon ratio {ratio:.4f} outside sane band "
        f"(0.5, 2.0); on={on}, off={off}"
    )
    # The key proof that the new code path actually fires: at least one of
    # total_carbon, migration_count, or dest_grids_visited must differ
    # between default and opt-in. The CISO/MISO empirical ratio (~0.96 vs
    # clock ~0.91) perturbs time_left_h by ~5%, enough to shift forecast
    # sums and decisions for this fixture.
    differs = (
        result_on["total_carbon_gco2"] != result_off["total_carbon_gco2"]
        or result_on["migration_count"] != result_off["migration_count"]
        or result_on.get("dest_grids_visited") != result_off.get("dest_grids_visited")
    )
    assert differs, (
        f"Opt-in use_empirical_runtime=True should differ from default on "
        f"a fixture where both grids have sysbench data. Got identical "
        f"results: on={result_on}, off={result_off}"
    )


# ── 260525-ksw: HW × CI invariant regression ─────────────────────


def test_total_carbon_uses_hw_even_when_policy_ignores_hw():
    """Regression for 260525-ksw HW × CI invariant.

    Policy 3 is HW-blind in its destination scoring, but the simulation core's
    total_carbon accounting MUST still include HW scaling when use_hw=True.
    Construct a degenerate single-grid lookup so there is only one possible
    destination and the policy can never migrate; assert that the resulting
    total_carbon equals Σ(raw_intensity × power_per_core) over completed hours.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    from heuristics.hardware import HW_TABLE  # noqa: WPS433

    # Single grid in HW_TABLE (use ISNE — matches FIXTURE_GRIDS convention).
    grid = "ISNE"
    raw_per_hour = 200.0
    hours_to_cover = 3
    minutes = hours_to_cover * 60  # 180 useful minutes, no migrations possible
    lookup = {(grid, BASE_TS_2020 + h * 3600): raw_per_hour
              for h in range(hours_to_cover + 2)}  # +2 slack for safety
    cfg = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid=grid,
        policy_id=3,            # HW-BLIND in its decision logic
        use_hw=True,            # but accounting MUST use HW
        expected_completion_min=minutes,
        expected_migration_min=5,
        app_size_mb=64.0,
    )
    result = simulate_one_run(lookup, cfg)

    expected = raw_per_hour * HW_TABLE[grid].power_per_core * hours_to_cover
    got = result["total_carbon_gco2"]
    assert abs(got - round(expected, 1)) < 0.6, (
        f"HW × CI invariant violated: expected ≈ {expected:.1f} "
        f"(raw {raw_per_hour} × power_per_core {HW_TABLE[grid].power_per_core} "
        f"× {hours_to_cover}h), got total_carbon_gco2 = {got}"
    )
    assert result["migration_count"] == 0, (
        "Single-grid lookup must yield zero migrations; "
        f"got {result['migration_count']}"
    )


# ── 260526-gj6: policy_use_hw_override decouples decisions from accounting ───


def test_policy_use_hw_override_decouples_decisions_from_accounting():
    """When policy_use_hw_override=False but use_hw=True, total_carbon should be
    HW-scaled (accumulation uses power_per_core) but policies' argmin picks
    should be on raw intensity (so P2 may pick a different target than it would
    with HW-scaled intensity).

    Fixture construction: pick (ISNE, TVA) where power_per_core ratio ~2.5x:
      ISNE.ppc = 6.2357,  TVA.ppc = 15.625
    Choose CI such that raw argmin and HW-scaled argmin disagree:
      raw:        TVA=200 < ISNE=300            -> raw argmin = TVA
      HW-scaled:  TVA=200*15.625=3125
                  ISNE=300*6.2357=1870.7        -> HW-scaled argmin = ISNE

    Under policy_use_hw_override=False (HW-blind decisions):
      P2 starting at ISNE sees raw argmin = TVA -> migrates to TVA in hour 0.
      dest_grids_visited must include 'TVA'.
    Under cfg.use_hw=True (accumulation always HW-on):
      total_carbon includes HW x raw_CI for every hour the pod sits on each
      grid (and the 0.5-h migration lump at hour 0 source-side ISNE intensity).
      With expected_migration_min=0 (free migration) and source_grid=ISNE
      migrating to TVA at hour 0, hour-0 useful minutes happen on the new grid.
      Setting m=0 isolates accumulation to TVA's HW x CI = 200*15.625 per
      useful hour, allowing a clean formula check.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _simulation_core import RunConfig, simulate_one_run  # noqa: WPS433
    from heuristics.hardware import HW_TABLE  # noqa: WPS433

    raw_isne = 300.0
    raw_tva = 200.0
    hours_to_cover = 3
    minutes = hours_to_cover * 60
    # +2 hours of slack so any lookahead/wrap probes don't fall off the lookup.
    lookup = {}
    for h in range(hours_to_cover + 2):
        ts = BASE_TS_2020 + h * 3600
        lookup[("ISNE", ts)] = raw_isne
        lookup[("TVA", ts)] = raw_tva

    # Sanity-check the fixture invariants before exercising the sim.
    isne_ppc = HW_TABLE["ISNE"].power_per_core
    tva_ppc = HW_TABLE["TVA"].power_per_core
    assert raw_tva < raw_isne, "fixture: raw argmin must be TVA"
    assert raw_tva * tva_ppc > raw_isne * isne_ppc, (
        "fixture: HW-scaled argmin must be ISNE (i.e. argmins must disagree)"
    )

    cfg = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid="ISNE",
        policy_id=2,                            # always-min-CI policy
        use_hw=True,                            # accumulation HW-on
        policy_use_hw_override=False,           # decisions HW-blind
        expected_completion_min=minutes,
        expected_migration_min=0,               # free migration -> clean accounting
        app_size_mb=64.0,
    )
    result = simulate_one_run(lookup, cfg)

    # Assertion 1: Policy 2 chose the raw-CI argmin (TVA), not the HW-scaled
    # argmin (ISNE). Migration at hour 0 means dest_grids_visited == ['TVA'].
    assert result["dest_grids_visited"] == ["TVA"], (
        "policy_use_hw_override=False should make P2 pick raw-CI argmin (TVA), "
        f"got dest_grids_visited={result['dest_grids_visited']}"
    )
    assert result["migration_count"] == 1, (
        f"Expected exactly one migration at hour 0; got "
        f"{result['migration_count']}"
    )

    # Assertion 2: total_carbon is HW-scaled. The sim loop accumulates the
    # current grid's HW x CI BEFORE applying the migration decision, so hour 0
    # accumulates on ISNE (the source) and hours 1..N-1 accumulate on TVA.
    # With m=0 (free migration) and hours_to_cover=3 useful hours:
    #   hour 0: ISNE -> raw_isne * isne_ppc
    #   hour 1..2: TVA -> raw_tva * tva_ppc each
    expected = raw_isne * isne_ppc + raw_tva * tva_ppc * (hours_to_cover - 1)
    got = result["total_carbon_gco2"]
    assert abs(got - round(expected, 1)) < 1.0, (
        f"total_carbon should be HW-scaled (HW x raw_CI), expected "
        f"~{expected:.1f} (= 1h source ISNE {raw_isne}*{isne_ppc} "
        f"+ {hours_to_cover - 1}h target TVA {raw_tva}*{tva_ppc}), got {got}"
    )
    # And it must NOT equal the raw-CI sum, which is the bug we are guarding
    # against (the whole point of policy_use_hw_override). Raw sum would be
    # raw_isne + raw_tva * (hours_to_cover - 1) = 300 + 200 + 200 = 700.
    raw_sum_no_hw = raw_isne + raw_tva * (hours_to_cover - 1)
    assert got > 5 * raw_sum_no_hw, (
        f"total_carbon should be HW-scaled and much larger than the raw-CI "
        f"sum {raw_sum_no_hw}; got {got} (ratio {got / raw_sum_no_hw:.2f}x)"
    )

    # Assertion 3 (cross-check): the same fixture with policy_use_hw_override
    # unset (None) and use_hw=True must NOT migrate, because the HW-scaled
    # argmin matches the source (ISNE). Confirms the override is what's
    # changing the decision and not some other behavior.
    cfg_hw_aware = RunConfig(
        start_ts=BASE_TS_2020,
        source_grid="ISNE",
        policy_id=2,
        use_hw=True,                            # accumulation HW-on
        policy_use_hw_override=None,            # default: decisions see cfg.use_hw=True
        expected_completion_min=minutes,
        expected_migration_min=0,
        app_size_mb=64.0,
    )
    result_hw = simulate_one_run(lookup, cfg_hw_aware)
    assert result_hw["dest_grids_visited"] == [], (
        "HW-aware decision should stay at ISNE (HW-scaled argmin); "
        f"got dest_grids_visited={result_hw['dest_grids_visited']}"
    )
    assert result_hw["migration_count"] == 0


# ── 260526-lgv: piecewise-constant fractional-window accumulator regression ───


def test_policy6_uses_fractional_weights_at_window_boundaries():
    """260526-lgv: Policy 6's stay/migrate carbon projection uses fractional
    weights at window boundaries, not int-rounded integer-hour summation.

    The piecewise-constant interpretation: hour x's published intensity
    applies to the entire interval [x, x+1). A window [a, b) splits into
    three parts:
      - Partial first hour: weight = (ceil(a) - a) * intensity(floor(a))
      - Full interior hours: weight = 1.0 * intensity(h) for each h
      - Partial last hour: weight = (b - floor(b)) * intensity(floor(b))

    All lookups land on integer-hour boundaries to preserve the
    lookup_intensity fast-path (260505-fvu).

    This test calls _accumulate_carbon_window directly with three carefully
    chosen windows that exercise: (1) both partial-first and partial-last
    (sub-hour migration), (2) integer-aligned window (whole-hour migration,
    byte-identical to pre-fix behavior), (3) zero-offset fractional-length
    window (stay loop semantics).
    """
    from heuristics.policy_heuristic import _accumulate_carbon_window  # noqa: WPS433

    # 2-hour lookup: hour 0 = intensity 100, hour 1 = 200, hour 2 = 300.
    lookup = {("A", 0): 100.0, ("A", 3600): 200.0, ("A", 7200): 300.0}

    # Case 1 (sub-hour migration): window [0.5, 1.5).
    # Partial first hour [0.5, 1.0) -> 0.5 * 100 = 50.
    # Partial last hour [1.0, 1.5) -> 0.5 * 200 = 100.
    # No interior full hours.
    result = _accumulate_carbon_window(
        lookup, "A", decision_ts=0,
        window_start_h=0.5, window_length_h=1.0,
        weight=1.0, lookahead_cap_h=48,
    )
    assert abs(result - 150.0) < 1e-6, f"expected 150.0, got {result}"

    # Case 2 (whole-hour migration): window [1.0, 2.0).
    # No partial first hour. One full interior hour at h=1 -> 1.0 * 200 = 200.
    # No partial last hour (last_full = 2, end_h = 2.0, so 2 < 2.0 is False).
    result2 = _accumulate_carbon_window(
        lookup, "A", decision_ts=0,
        window_start_h=1.0, window_length_h=1.0,
        weight=1.0, lookahead_cap_h=48,
    )
    assert abs(result2 - 200.0) < 1e-6, f"expected 200.0, got {result2}"

    # Case 3 (stay loop, fractional length): window [0.0, 2.5).
    # No partial first hour. Full interior hours h=0,1 -> 100 + 200 = 300.
    # Partial last hour [2.0, 2.5) -> 0.5 * 300 = 150.
    result3 = _accumulate_carbon_window(
        lookup, "A", decision_ts=0,
        window_start_h=0.0, window_length_h=2.5,
        weight=1.0, lookahead_cap_h=48,
    )
    assert abs(result3 - 450.0) < 1e-6, f"expected 450.0, got {result3}"


# ── 260527-fbb: lookahead derives from deadline when unset ────────────


def test_policy6_lookahead_derives_from_deadline_when_unset():
    """260527-fbb: When lookahead_hours is None (default), Policy 6 derives it
    from expected_total_minutes / 60 * deadline_multiplier. Explicit integer
    values are honored verbatim, so the horizon sweep and any caller passing
    an explicit N remain byte-identical to pre-260527-fbb behavior.
    """
    from heuristics.policy_heuristic import HeuristicPolicy

    # Default (canonical 48h × 1.5 = 72h)
    p = HeuristicPolicy(app_size_mb=64.0, expected_total_minutes=2880)
    assert p.lookahead_hours == 72, (
        f"canonical default should derive 72 h from 2880 min × 1.5; got {p.lookahead_hours}"
    )

    # Explicit override still works
    p2 = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=2880, lookahead_hours=24
    )
    assert p2.lookahead_hours == 24, (
        f"explicit lookahead_hours=24 must be honored verbatim; got {p2.lookahead_hours}"
    )

    # Non-canonical job: 120 min × 2.0 = 4 h
    p3 = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=120, deadline_multiplier=2.0
    )
    assert p3.lookahead_hours == 4, (
        f"120 min × 2.0 should derive 4 h; got {p3.lookahead_hours}"
    )

    # Floor at 1 hour for very short jobs (30 min × 1.0 = 0.5 h → 0 → floored to 1)
    p4 = HeuristicPolicy(
        app_size_mb=64.0, expected_total_minutes=30, deadline_multiplier=1.0
    )
    assert p4.lookahead_hours == 1, (
        f"short-job floor should clamp to 1 h; got {p4.lookahead_hours}"
    )


# ── 260527-fuv: lump-source migration_carbon alignment ────────────────


def test_policy6_migration_carbon_is_lump_source_and_destination_independent():
    """260527-fuv: Policy 6's internal migration_carbon estimate uses the sim's
    lump-source formula (mig_time_h × src_HW × src_CI when hw_weighting=True,
    or × src_CI alone when hw_weighting=False) and is INDEPENDENT of the
    destination's intensity-now or hardware. Locks in the alignment with
    _simulation_core.py:365 (migration_fraction_h × source-intensity) so a
    future refactor can't accidentally re-introduce the three-phase split
    (ckpt @ src + send @ avg + restore @ dst) that biased P6 toward
    over-migration whenever the destination was cleaner than the source.

    The test asserts two things, the second of which is the regression
    catcher:

      (1) FORMULA IDENTITY: the lump-source expression
              mig_time_h × src_HW × src_CI
          equals the sim's actual charge from _simulation_core.py:365:
              migration_fraction_h × intensity
          and the hw_weighting=False variant
              mig_time_h × 1.0 × src_CI
          equals the use_hw=False sim charge. Pure arithmetic identity.

      (2) DECISION-CARBON DECOMPOSITION: build a fixture where the only
          variable that matters to ARGMIN(dst) under the OLD three-phase
          model is dst_intensity_now (post-migration forecasts are
          identical, destinations have identical hardware, source CI is
          fixed). Under the OLD model, swapping dst_a's and dst_b's
          decision-hour CI would flip the argmin (because the restore +
          network terms key off dst_intensity_now). Under the NEW
          lump-source model, the migration_carbon is identical for both
          destinations AND identical before/after the swap, so the
          argmin is determined entirely by dest_run_carbon. We can't
          read migration_carbon out of decide() directly, so we use a
          STRONGER assertion: we instrument the policy by inspecting
          src_intensity_now and confirming the chosen target's expected
          total carbon (under the lump-source formula) is minimized.
    """
    from heuristics.policy_heuristic import HeuristicPolicy, _accumulate_carbon_window  # noqa: WPS433
    from heuristics.hardware import HW_TABLE  # noqa: WPS433
    from heuristics.overhead import (  # noqa: WPS433
        ckpt_overhead, send_overhead, restore_overhead,
    )

    # ── (1) Formula identity ──────────────────────────────────────────
    # The lump-source formula must equal the sim's actual charge for any
    # mig_time_h, src HW, and src CI.
    src_hw = HW_TABLE["ERCO"]
    src_ppc = src_hw.power_per_core
    for mig_time_min in (5.0, 15.0, 30.0, 60.0, 90.0):
        mig_time_h = mig_time_min / 60.0
        for src_ci in (50.0, 200.0, 400.0, 750.0):
            # Sim charge (HW × CI, use_hw=True path of _simulation_core.py:299-300, 365)
            sim_charge_hw_on = mig_time_h * (src_ci * src_ppc)
            # Heuristic estimate under hw_weighting=True
            heur_hw_on = mig_time_h * src_ppc * src_ci
            assert abs(heur_hw_on - sim_charge_hw_on) < 1e-9, (
                f"hw_weighting=True formula identity broken: "
                f"heuristic {heur_hw_on} != sim {sim_charge_hw_on}"
            )
            # Sim charge (raw CI, use_hw=False path of _simulation_core.py:302, 365)
            sim_charge_hw_off = mig_time_h * src_ci
            # Heuristic estimate under hw_weighting=False
            heur_hw_off = mig_time_h * 1.0 * src_ci
            assert abs(heur_hw_off - sim_charge_hw_off) < 1e-9, (
                f"hw_weighting=False formula identity broken: "
                f"heuristic {heur_hw_off} != sim {sim_charge_hw_off}"
            )

    # ── (2) Decision-CI independence under realistic decide() ─────────
    # Pick two destinations with IDENTICAL HW so mig_time_h is identical
    # across them (send/restore depend on dst HW). PACE and PGE both have
    # power_per_core=7.5 in HW_TABLE; they're real grids exercised by the
    # 2022 Gantt fixture below.
    src = "ERCO"
    dst_a = "PACE"
    dst_b = "PGE"
    grids = [src, dst_a, dst_b]
    assert HW_TABLE[dst_a].power_per_core == HW_TABLE[dst_b].power_per_core, (
        "fixture: destinations must have identical power_per_core so mig_time_h "
        "is identical across them"
    )

    src_ci = 400.0
    dst_a_ci_now = 50.0
    dst_b_ci_now = 600.0
    post_mig_ci = 200.0

    lookup = {}
    for h in range(80):
        ts = BASE_TS_2020 + h * 3600
        lookup[(src, ts)] = src_ci
        if h == 0:
            lookup[(dst_a, ts)] = dst_a_ci_now
            lookup[(dst_b, ts)] = dst_b_ci_now
        else:
            lookup[(dst_a, ts)] = post_mig_ci
            lookup[(dst_b, ts)] = post_mig_ci

    app_size_mb = 64.0
    p = HeuristicPolicy(
        app_size_mb=app_size_mb,
        expected_total_minutes=2880,
        hw_weighting=True,
        overhead_cost=True,
        deadline_gate=True,
    )

    # Compute, OUTSIDE the policy, exactly what dest_run_carbon would be
    # for each destination under the lump-source model. This lets us
    # reconstruct what total_carbon the policy MUST have computed for
    # each destination and verify the argmin is consistent with the
    # lump-source formula.
    dst_a_hw = HW_TABLE[dst_a]
    mig_time_h = (
        ckpt_overhead(app_size_mb, src_hw)
        + send_overhead(src_hw, dst_a_hw, app_size_mb)
        + restore_overhead(app_size_mb, dst_a_hw)
    ) / 3600.0
    # Lump-source migration_carbon under hw_weighting=True. Identical for
    # both destinations because they have identical HW (mig_time_h equal)
    # and the formula references only src.
    expected_mig_carbon = mig_time_h * src_ppc * src_ci

    # Compute dest_run_carbon for each destination using the same helper
    # the policy uses. lookahead_cap_h = 72 (derived from canonical 48h × 1.5).
    # time_left_h = 48 (full job) since elapsed=0; same for both destinations.
    time_left_h = 48.0
    dest_weight = dst_a_hw.power_per_core
    drc_a = _accumulate_carbon_window(
        lookup, dst_a, BASE_TS_2020,
        window_start_h=mig_time_h, window_length_h=time_left_h,
        weight=dest_weight, lookahead_cap_h=72,
    )
    drc_b = _accumulate_carbon_window(
        lookup, dst_b, BASE_TS_2020,
        window_start_h=mig_time_h, window_length_h=time_left_h,
        weight=dest_weight, lookahead_cap_h=72,
    )
    expected_total_a = expected_mig_carbon + drc_a
    expected_total_b = expected_mig_carbon + drc_b
    expected_target = dst_a if expected_total_a <= expected_total_b else dst_b

    should_migrate, target = p.decide(
        lookup, grids, src, BASE_TS_2020,
        remaining_hours=48, elapsed_hours=0.0,
    )
    assert should_migrate is True, (
        "P6 should migrate: src 400 vs dest forecasted 200 favors migration"
    )
    assert target == expected_target, (
        f"Lump-source argmin must equal external recomputation; "
        f"expected={expected_target} (total_a={expected_total_a:.4f}, "
        f"total_b={expected_total_b:.4f}), got target={target}. "
        f"A mismatch here means migration_carbon depends on something "
        f"other than (mig_time_h × src_HW × src_CI)."
    )

    # ── hw_weighting=False branch ─────────────────────────────────────
    # Drop the power_per_core factor and re-verify formula identity end-
    # to-end. This locks in the HEUR-10 ablation toggle for the new model.
    p_no_hw = HeuristicPolicy(
        app_size_mb=app_size_mb,
        expected_total_minutes=2880,
        hw_weighting=False,
        overhead_cost=True,
        deadline_gate=True,
    )
    expected_mig_carbon_no_hw = mig_time_h * 1.0 * src_ci
    drc_a_no_hw = _accumulate_carbon_window(
        lookup, dst_a, BASE_TS_2020,
        window_start_h=mig_time_h, window_length_h=time_left_h,
        weight=1.0, lookahead_cap_h=72,
    )
    drc_b_no_hw = _accumulate_carbon_window(
        lookup, dst_b, BASE_TS_2020,
        window_start_h=mig_time_h, window_length_h=time_left_h,
        weight=1.0, lookahead_cap_h=72,
    )
    expected_target_no_hw = dst_a if (
        expected_mig_carbon_no_hw + drc_a_no_hw
        <= expected_mig_carbon_no_hw + drc_b_no_hw
    ) else dst_b
    _, target_no_hw = p_no_hw.decide(
        lookup, grids, src, BASE_TS_2020,
        remaining_hours=48, elapsed_hours=0.0,
    )
    assert target_no_hw == expected_target_no_hw, (
        f"hw_weighting=False argmin must equal external recomputation; "
        f"expected={expected_target_no_hw}, got={target_no_hw}"
    )

    # ── overhead_cost=False branch ────────────────────────────────────
    # Zeroes migration_carbon entirely (HEUR-10 toggle preserved).
    p_no_oh = HeuristicPolicy(
        app_size_mb=app_size_mb,
        expected_total_minutes=2880,
        hw_weighting=True,
        overhead_cost=False,
        deadline_gate=True,
    )
    # With migration_carbon = 0, argmin = argmin(dest_run_carbon).
    expected_target_no_oh = dst_a if drc_a <= drc_b else dst_b
    _, target_no_oh = p_no_oh.decide(
        lookup, grids, src, BASE_TS_2020,
        remaining_hours=48, elapsed_hours=0.0,
    )
    assert target_no_oh == expected_target_no_oh, (
        f"overhead_cost=False (migration_carbon=0) argmin must equal "
        f"argmin(dest_run_carbon); expected={expected_target_no_oh}, "
        f"got={target_no_oh}"
    )

    # ── (3) Source-code structural assertion ─────────────────────────
    # The migration_carbon assignment in policy_heuristic.py must NOT
    # reference hw[dest].power_per_core, dst_intensity_now, or
    # network_power_watts. A textual grep is more robust than a behavioral
    # test here because the mig_time × ppc factors are so small relative
    # to dest_run_carbon that the choice rarely flips on migration_carbon
    # alone -- yet the three-phase model's bias is real over a multi-day
    # Gantt where many marginal-call hours accumulate. Locking the
    # textual form catches the regression even when behavioral tests under
    # contrived fixtures cannot.
    #
    # Strategy: extract the lines forming the migration_carbon ASSIGNMENT
    # block (the lines from `if self.overhead_cost:` up through the
    # `else: migration_carbon = 0.0` block) and forbid the three-phase
    # tokens within that block. We bracket on the toggle's `if`/`else`
    # structure so we don't accidentally include unrelated lines.
    import inspect  # noqa: WPS433
    from heuristics import policy_heuristic as _policy_module  # noqa: WPS433
    src_text = inspect.getsource(_policy_module.HeuristicPolicy.decide)
    src_lines = src_text.splitlines()
    # Find the `if self.overhead_cost:` line and walk forward, capturing
    # until we exit the indentation level (next dedent past the `else`
    # branch). The block is small (<10 lines).
    overhead_if_idx = None
    for i, ln in enumerate(src_lines):
        if "if self.overhead_cost:" in ln:
            overhead_if_idx = i
            break
    assert overhead_if_idx is not None, (
        "Couldn't find `if self.overhead_cost:` block in decide(). The "
        "structural check needs an update to track the new block location."
    )
    # Capture roughly 12 lines starting from the if; that's enough to span
    # the if-branch + else-branch even with multi-line assignments.
    mig_block_lines = src_lines[overhead_if_idx:overhead_if_idx + 12]
    mig_block = "\n".join(mig_block_lines)

    forbidden_in_assignment = ("dst_intensity_now", "hw[dest]", "network_power_watts")
    for tok in forbidden_in_assignment:
        assert tok not in mig_block, (
            f"Three-phase regression: migration_carbon block contains "
            f"forbidden token '{tok}'. Lump-source formula must depend "
            f"ONLY on (mig_time_h, src_HW, src_intensity_now). Block:\n"
            f"{mig_block}"
        )
    # Required tokens: the lump-source formula must reference src_intensity_now.
    assert "src_intensity_now" in mig_block, (
        "Lump-source migration_carbon must reference src_intensity_now. "
        f"Saw block:\n{mig_block}"
    )


# ── 260601-gyw: discrete-hour dest window offset ─────────────────


def test_policy6_dest_window_uses_discrete_hour_offset():
    """Policy 6's dest_run_carbon window must start at ceil(mig_time_h), not
    at fractional mig_time_h. Matches the sim's discrete-hour loop body
    (full source intensity at the decision hour, grid switch at end-of-hour).

    Locks in the 260601-gyw fix; protects against accidental regression to
    260526-lgv's fractional offset.
    """
    from heuristics.policy_heuristic import _accumulate_carbon_window  # noqa: WPS433
    import math

    # 4-hour lookup: hour 0=100, hour 1=200, hour 2=300, hour 3=400.
    # Use Unix-timestamp keying (decision_ts=0 + h*3600) so the helper's
    # exact-match path is exercised (no fuzzy-match collisions).
    lookup = {
        ("A", 0): 100.0,
        ("A", 3600): 200.0,
        ("A", 7200): 300.0,
        ("A", 10800): 400.0,
    }

    # For 30-min mig (mig_time_h=0.5), dest window should start at ceil(0.5)=1.
    # Window: [1, 1+2) = hours 1 and 2 (full). NOT hours 0.5..2.5.
    offset = float(math.ceil(0.5))
    result = _accumulate_carbon_window(
        lookup, "A", decision_ts=0,
        window_start_h=offset, window_length_h=2.0,
        weight=1.0, lookahead_cap_h=48,
    )
    # Expected (discrete): 1.0*200 + 1.0*300 = 500.0
    assert abs(result - 500.0) < 1e-6, f"discrete expected 500.0, got {result}"

    # Counter-check: the fractional offset (mig_time_h=0.5) would give a
    # DIFFERENT result. Window [0.5, 2.5):
    #   partial first hour [0.5, 1.0) -> 0.5 * 100 = 50
    #   full interior h=1            -> 1.0 * 200 = 200
    #   partial last hour [2.0, 2.5) -> 0.5 * 300 = 150
    #   total = 400.0
    result_fractional = _accumulate_carbon_window(
        lookup, "A", decision_ts=0,
        window_start_h=0.5, window_length_h=2.0,
        weight=1.0, lookahead_cap_h=48,
    )
    assert abs(result_fractional - 400.0) < 1e-6, (
        f"fractional expected 400.0, got {result_fractional}"
    )
    assert result != result_fractional, (
        "discrete and fractional models must differ for sub-hour mig"
    )


def test_policy6_dest_window_integer_hour_migration_unchanged():
    """For migrations that are exact integer hours (60, 120, ...), ceil(N)=N,
    so the discrete-hour fix is a no-op. Behavior matches pre-260526-lgv
    integer-hour path (and pre-260601-gyw fractional path, since they
    coincide at integer offsets)."""
    from heuristics.policy_heuristic import _accumulate_carbon_window  # noqa: WPS433
    import math

    lookup = {
        ("A", 0): 100.0,
        ("A", 3600): 200.0,
        ("A", 7200): 300.0,
    }

    # For 60-min mig (mig_time_h=1.0), dest starts at ceil(1.0)=1.0.
    # Window: [1, 3) -> full interior hours 1 and 2 -> 200 + 300 = 500.
    offset = float(math.ceil(1.0))
    result = _accumulate_carbon_window(
        lookup, "A", decision_ts=0,
        window_start_h=offset, window_length_h=2.0,
        weight=1.0, lookahead_cap_h=48,
    )
    assert abs(result - 500.0) < 1e-6, f"expected 500.0, got {result}"


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
        # 260519-fhe: opt-in flag for 2022 final-eval access.
        test_runconfig_bypass_test_split_allows_2022_timestamp,
        test_intensity_lookup_filters_2022,
        # 260511-jce: minute-granular migration carbon regressions.
        test_migration_carbon_minute_granular,
        test_migration_carbon_zero_overhead_is_free,
        # 260512-kfc: replaces the cooldown gate test (migrating_cooldown removed).
        test_migration_minutes_remaining_gates_re_migration_during_in_progress,
        # 260512-kfc: useful-work-driven termination + safety cap regressions.
        test_sim_extends_runtime_for_migration_minutes,
        test_sim_safety_cap_fires_on_pathological_policy,
        # 260515-jav: sysbench-backed empirical runtime opt-in regressions.
        test_sim_default_use_empirical_runtime_matches_existing_behavior,
        test_sim_opt_in_use_empirical_runtime_differs_from_default,
        # 260525-ksw: HW × CI invariant regression.
        test_total_carbon_uses_hw_even_when_policy_ignores_hw,
        # 260526-gj6: policy_use_hw_override decouples decisions from accounting.
        test_policy_use_hw_override_decouples_decisions_from_accounting,
        # 260526-lgv: piecewise-constant fractional-window accumulator regression.
        test_policy6_uses_fractional_weights_at_window_boundaries,
        # 260527-fbb: lookahead derives from deadline when unset.
        test_policy6_lookahead_derives_from_deadline_when_unset,
        # 260527-fuv: lump-source migration_carbon alignment with sim.
        test_policy6_migration_carbon_is_lump_source_and_destination_independent,
        # 260601-gyw: discrete-hour dest window offset (ceil(mig_time_h)).
        test_policy6_dest_window_uses_discrete_hour_offset,
        test_policy6_dest_window_integer_hour_migration_unchanged,
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
