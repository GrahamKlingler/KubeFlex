#!/usr/bin/env python3
"""Phase 4 evaluation orchestrator: multi-policy sweep, ablation, and horizon sensitivity.

Requirements addressed:
  - HEUR-10: 8-cell ablation sweep (Policy 6 toggle combinations)
  - HEUR-11: 7-horizon sweep (lookahead_hours in {1,2,4,8,12,24,48})
  - EVAL-01: multi-policy comparison
  - EVAL-02: 10+ timestamp sweep (8,784 hourly starts of 2020 x 26 grids, far exceeding)
  - EVAL-03: visualization-ready unified CSV
  - INFR-04: in-process orchestration via multiprocessing.Pool

Usage:
  # Full sweep (~370k runs):
  python3 evaluate_policies.py --sweep-kind all

  # Smoke run (~30 s):
  python3 evaluate_policies.py --sweep-kind all --smoke

  # Just the ablation:
  python3 evaluate_policies.py --sweep-kind ablation

Outputs (data/evaluation/run_<ts>/):
  - results.csv      -- unified long-format CSV per D-19
  - ablation.csv     -- sweep_kind=='ablation' subset
  - horizon.csv      -- sweep_kind=='horizon' subset
  - metadata.json    -- sweep parameters, git SHA, run timing, wrap-into-val count

Join-key naming: this orchestrator builds a grid-keyed intensity lookup by
recursing ``data/regions/{REGION}/{GRID}.csv`` and joining against the
grid-keyed HW_TABLE in ``data/hardware/hw_avg.csv`` (see quick task
260502-i16). The cluster-execution path remains region-keyed.

Data discipline:
  - 2022 hard-block (D-23): build_intensity_lookup_from_regions_tree filters
    to (2020, 2021) AND generate_sweep calls check_split_access for every cfg
  - End-of-year wrap (D-22): late-2020 starts may read 2021 forecast values for
    trailing hours; flagged via wrapped_into_val side-channel; aggregated count
    written to metadata.json (no per-run prints -- workers are silent)
"""

import argparse
import csv
import itertools
import json
import math  # noqa: F401 (available for callers; kept per plan spec)
import multiprocessing as mp
import os  # noqa: F401 (available; kept per plan spec)
import subprocess
import sys
import time
import warnings
from dataclasses import asdict  # noqa: F401 (re-exported for callers)
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# Project import shim (CLAUDE.md "Import Organization")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from heuristics.data_splits import check_split_access  # noqa: E402
from heuristics.hardware import HW_TABLE  # noqa: E402
from _simulation_core import (  # noqa: E402
    RunConfig,
    _ablation_id,
    simulate_one_run as _core_simulate_one_run,
)

try:
    from tqdm import tqdm
except ImportError:
    sys.stderr.write("ERROR: tqdm is required (pip install tqdm)\n")
    sys.exit(2)


# ── Constants ────────────────────────────────────────────────────────

# Default regions tree: <repo>/data/regions/{REGION}/US-{REGION}-{GRID}.csv
DEFAULT_REGIONS_TREE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "regions"
)

# Populated lazily in main() once the regions tree is resolved (and once
# HW_TABLE membership is known so we can drop grids without hardware specs).
GRIDS: Tuple[str, ...] = ()

HORIZON_VALUES: Tuple[int, ...] = (1, 2, 4, 8, 12, 24, 48)  # D-13
ABLATION_CELLS: List[Tuple[bool, bool, bool]] = list(
    itertools.product([False, True], repeat=3)
)  # 8 (hw, oh, dl) tuples
MAIN_POLICIES: Tuple[int, ...] = (1, 2, 3, 4, 5, 6)
HORIZON_BASELINE_POLICIES: Tuple[int, ...] = (1, 2, 3, 4, 5)

# D-19 unified CSV schema (renamed source_region -> source_grid in 260502-i16
# to match the grid-keyed expected-sim path).
SCHEMA: List[str] = [
    "policy", "source_grid", "start_ts", "start_datetime",
    "hw_weighting", "overhead_cost", "deadline_gate", "ablation_id", "lookahead_hours",
    "app_size_mb", "expected_completion_min", "deadline_multiplier",
    "total_carbon_gco2", "baseline_carbon_gco2", "savings_pct",
    "migration_count", "completed_hours", "sweep_kind",
]

# Output directory base (data/evaluation/ tree per D-18)
OUT_DIR_BASE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "evaluation"

# Worker process global -- set by _init_worker (RESEARCH.md Pattern 1)
_LOOKUP: Optional[Dict[Tuple[str, int], float]] = None


# ── Intensity lookup builder ─────────────────────────────────────────

def _grid_from_stem(stem: str) -> str:
    """Derive the canonical grid identifier from a CSV file stem.

    The grid CSVs live at ``data/regions/{REGION}/{STEM}.csv`` where ``STEM``
    is typically ``US-{REGION}-{GRID}`` (e.g. ``US-NE-ISNE``, ``US-CAL-CISO``).
    The trailing dash-separated segment is the canonical grid key; this is the
    same key used in ``data/hardware/hw_avg.csv``'s ``grid`` column.
    """
    return stem.rsplit("-", 1)[-1]


def discover_grids(regions_root: Path) -> Tuple[str, ...]:
    """Walk ``regions_root/*/*.csv`` and return the sorted set of grid stems."""
    if not Path(regions_root).exists():
        return ()
    return tuple(
        sorted({_grid_from_stem(p.stem) for p in Path(regions_root).glob("*/*.csv")})
    )


def build_intensity_lookup_from_regions_tree(
    regions_root: Path,
    include_years: Tuple[int, ...] = (2020, 2021),
    allowed_grids: Optional[Tuple[str, ...]] = None,
) -> Dict[Tuple[str, int], float]:
    """Build ``{(grid, unix_ts): intensity}`` by recursing ``regions_root``.

    Walks ``regions_root/*/*.csv`` (one level deep: ``REGION/GRID-FILE.csv``)
    and emits one entry per row keyed by the trailing grid identifier (e.g.
    ``ISNE`` for ``US-NE-ISNE``). The parent directory name (the region) is
    preserved as metadata in the filename but is NOT used as a join key.

    D-23 enforced: include_years defaults to (2020, 2021); 2022 is NEVER loaded.

    Source schema (matches the original ``src/sample_data/{REGION}.csv``
    files used by Phase 3):
        datetime, timestamp, carbon_intensity_direct_avg, ...

    Args:
        regions_root: Path to ``data/regions/``.
        include_years: Years to load (others are silently skipped).
        allowed_grids: If set, only include rows whose grid is in this set.
            Useful for restricting to grids that have HW_TABLE entries so the
            simulation does not see destinations it cannot hardware-cost.

    Returns:
        Dict mapping (grid, unix_ts) -> carbon intensity.

    Raises:
        FileNotFoundError: If no CSV files are found under ``regions_root``.
    """
    regions_root = Path(regions_root)
    csv_paths = sorted(regions_root.glob("*/*.csv"))
    if not csv_paths:
        raise FileNotFoundError(
            f"[EVAL] no grid CSVs found under {regions_root} "
            f"(expected layout: data/regions/REGION/US-REGION-GRID.csv)"
        )
    allowed = set(allowed_grids) if allowed_grids is not None else None
    lookup: Dict[Tuple[str, int], float] = {}
    for path in csv_paths:
        grid = _grid_from_stem(path.stem)
        if allowed is not None and grid not in allowed:
            continue
        with open(path) as f:
            for row in csv.DictReader(f):
                v = row.get("carbon_intensity_direct_avg")
                if not v:
                    continue
                year = int(row["datetime"][:4])
                if year not in include_years:
                    continue
                ts = int(float(row["timestamp"]))
                lookup[(grid, ts)] = float(v)
    return lookup


# ── Timestamp helpers ────────────────────────────────────────────────

def _main_sweep_timestamps(year: int = 2020) -> List[int]:
    """Every hour of `year` as unix timestamps (D-01: 8,784 hourly starts for leap year 2020)."""
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    out = []
    cur = start
    while cur < end:
        out.append(int(cur.timestamp()))
        cur += timedelta(hours=1)
    return out


def _monthly_horizon_timestamps(year: int = 2020) -> List[int]:
    """First-of-month at 00:00 UTC for `year` (D-14: 12 horizon-sensitivity start points)."""
    return [
        int(datetime(year, m, 1, tzinfo=timezone.utc).timestamp())
        for m in range(1, 13)
    ]


# ── Sweep enumeration ────────────────────────────────────────────────

def _resolve_timestamps(args, default_fn) -> List[int]:
    """If args.timestamps is set, use it. Else use default_fn() (year-of-2020 or monthly)."""
    if getattr(args, "timestamps", None):
        return list(args.timestamps)
    return default_fn()


def _resolve_grids(args) -> List[str]:
    """Resolve the list of source grids for the sweep.

    Precedence:
      1. ``args.source_grids`` (new primary CLI flag)
      2. ``args.source_regions`` (deprecated alias kept for one release)
      3. The module-level GRIDS tuple (populated in main() from the regions tree)
    """
    sg = getattr(args, "source_grids", None)
    if sg:
        return list(sg)
    sr = getattr(args, "source_regions", None)
    if sr:
        # Deprecated alias path -- main() already prints the warning when
        # this attribute was set via CLI; here we just honor the value.
        return list(sr)
    return list(GRIDS)


def generate_sweep(args) -> Iterator[RunConfig]:
    """Yield RunConfigs in deterministic order. Calls check_split_access per cfg (D-22, D-23).

    sweep_kind in {main, ablation, horizon, all}.
    --smoke reduces each sub-sweep to a small deterministic subset (<30s total runtime).
    """
    sweep_kind = args.sweep_kind
    smoke = bool(getattr(args, "smoke", False))

    # Common per-cfg kwargs from args.
    # In smoke mode, use a short 2-hour simulation so the subset completes in <30s.
    base_completion_min = int(getattr(args, "expected_completion_min", 2880))
    smoke_completion_min = 120  # 2 hours -- fast smoke target
    common = dict(
        app_size_mb=float(getattr(args, "app_size_mb", 64.0)),
        expected_completion_min=smoke_completion_min if smoke else base_completion_min,
        expected_migration_min=int(getattr(args, "expected_migration_min", 5)),
        deadline_multiplier=float(getattr(args, "deadline_multiplier", 1.5)),
        include_network_power=bool(getattr(args, "include_network_power", True)),
        use_hw=True,
    )

    # Smoke mode globally squashes expected_completion_min to 120 (2 h) for speed,
    # but a 2-hour sim collapses policies 2-6 to identical results because policy 6's
    # overhead amortization, deadline gate, lookahead horizon, and hw weighting have
    # no room to differentiate from naive policies. Lift the floor for the main and
    # ablation sub-sweeps to the same value the horizon override already uses
    # (max(HORIZON_VALUES) * 60 == 2880 minutes / 48 hours), and warn the user.
    main_ablation_completion_min = max(base_completion_min, max(HORIZON_VALUES) * 60)
    if smoke:
        common_main_ablation = dict(
            common, expected_completion_min=main_ablation_completion_min,
        )
        print(
            "[SWEEP] WARNING: smoke mode main/ablation sub-sweeps use "
            "expected_completion_min={} (overriding smoke default {}) so "
            "policies 2-6 do not collapse to identical results over a "
            "2-hour sim horizon.".format(
                main_ablation_completion_min, smoke_completion_min,
            )
        )
    else:
        common_main_ablation = common

    if sweep_kind in ("main", "all"):
        timestamps = _resolve_timestamps(args, lambda: _main_sweep_timestamps(2020))
        grids = _resolve_grids(args)
        if smoke:
            # Deterministic small subset: ~30 timestamps x 1 grid x 6 policies = ~180 cfgs
            timestamps = timestamps[::max(1, len(timestamps) // 30)][:30]
            grids = grids[:1]
        # Deterministic order: (timestamp, grid, policy)
        for ts in timestamps:
            for g in grids:
                for p in MAIN_POLICIES:
                    cfg = RunConfig(
                        start_ts=ts,
                        source_grid=g,
                        policy_id=p,
                        lookahead_hours=int(getattr(args, "lookahead_hours", 48)),
                        hw_weighting=True,
                        overhead_cost=True,
                        deadline_gate=True,
                        sweep_kind="main",
                        **common_main_ablation,
                    )
                    check_split_access(cfg.start_ts)  # D-23 -- raises on 2022
                    yield cfg

    if sweep_kind in ("ablation", "all"):
        timestamps = _resolve_timestamps(args, lambda: _main_sweep_timestamps(2020))
        grids = _resolve_grids(args)
        if smoke:
            timestamps = timestamps[:1]
            grids = grids[:1]
        for ts in timestamps:
            for g in grids:
                for (hw, oh, dl) in ABLATION_CELLS:
                    cfg = RunConfig(
                        start_ts=ts,
                        source_grid=g,
                        policy_id=6,
                        lookahead_hours=int(getattr(args, "lookahead_hours", 48)),
                        hw_weighting=hw,
                        overhead_cost=oh,
                        deadline_gate=dl,
                        sweep_kind="ablation",
                        **common_main_ablation,
                    )
                    check_split_access(cfg.start_ts)
                    yield cfg

    if sweep_kind in ("horizon", "all"):
        # 12 monthly starts x N grids x 7 horizons (Policy 6) per D-14
        h_timestamps = _resolve_timestamps(args, _monthly_horizon_timestamps)
        grids = _resolve_grids(args)
        if smoke:
            h_timestamps = h_timestamps[:1]
            grids = grids[:1]
            # Smoke mode globally squashes expected_completion_min to 120 (2 h) for
            # speed, but the horizon plot compares Policy 6 across lookahead_hours
            # in {1..48}: with total_sim_hours=2, every cell collapses to
            # min(time_left_int=2, lookahead_hours)==2 and the chart conveys nothing
            # (CR-04). Force expected_completion_min long enough that lookahead_hours
            # actually bounds the destination loop, and warn the user that the smoke
            # override has been overridden for this sub-sweep.
            horizon_completion_min = max(base_completion_min, max(HORIZON_VALUES) * 60)
            common_h = dict(common, expected_completion_min=horizon_completion_min)
            print(
                "[SWEEP] WARNING: smoke mode horizon sub-sweep uses "
                "expected_completion_min={} (overriding smoke default {}) so "
                "lookahead_hours actually differentiates cells.".format(
                    horizon_completion_min, smoke_completion_min,
                )
            )
        else:
            common_h = common
        # Policy 6 with all 7 horizons
        for ts in h_timestamps:
            for g in grids:
                for h in HORIZON_VALUES:
                    cfg = RunConfig(
                        start_ts=ts,
                        source_grid=g,
                        policy_id=6,
                        lookahead_hours=h,
                        hw_weighting=True,
                        overhead_cost=True,
                        deadline_gate=True,
                        sweep_kind="horizon",
                        **common_h,
                    )
                    check_split_access(cfg.start_ts)
                    yield cfg
        # Policies 1-5 baselines (single per (ts, grid) -- lookahead irrelevant for them)
        if not smoke:
            for ts in h_timestamps:
                for g in grids:
                    for p in HORIZON_BASELINE_POLICIES:
                        cfg = RunConfig(
                            start_ts=ts,
                            source_grid=g,
                            policy_id=p,
                            lookahead_hours=int(getattr(args, "lookahead_hours", 48)),
                            sweep_kind="horizon",
                            **common_h,
                        )
                        check_split_access(cfg.start_ts)
                        yield cfg


# ── Worker boilerplate (RESEARCH.md Pattern 1) ────────────────────────

def _init_worker(intensity_lookup: Dict[Tuple[str, int], float]) -> None:
    """Pool initializer: stash the lookup in the worker's module global."""
    global _LOOKUP
    _LOOKUP = intensity_lookup


def simulate_one_run(cfg: RunConfig) -> Dict[str, Any]:
    """Worker entry point. Reads _LOOKUP set by _init_worker."""
    # Use a real RuntimeError rather than `assert` so that running under
    # `python -O` (which strips asserts) still produces an actionable error
    # instead of an opaque AttributeError from lookup_intensity (WR-01).
    if _LOOKUP is None:
        raise RuntimeError(
            "Worker not initialized -- Pool must be started with "
            "initializer=_init_worker, initargs=(intensity_lookup,)."
        )
    return _core_simulate_one_run(_LOOKUP, cfg)


# ── Output writers ───────────────────────────────────────────────────

def _to_int_or_zero(v) -> int:
    """Coerce row values that may be int / str / float / "" / None to int.

    `str.isdigit()` rejects empty string, negative ints, and float-shaped strings
    like "48.0" — using it directly in _sort_key (WR-10) made the deterministic
    sort fragile to any future change that emits lookahead_hours as a float.
    """
    if v is None or v == "":
        return 0
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _sort_key(row: Dict[str, Any]) -> Tuple:
    return (
        row.get("sweep_kind", ""),
        int(row.get("policy", 0)),
        row.get("source_grid", ""),
        int(row.get("start_ts", 0)),
        row.get("ablation_id", "") or "",
        # lookahead_hours can be int or "" (Plan 02 returns "" for non-Policy-6).
        # Use the defensive coerce so future float-shaped values still sort.
        _to_int_or_zero(row.get("lookahead_hours")),
    )


def _write_csv(path: Path, rows: List[Dict[str, Any]], schema: List[str]) -> None:
    """Sort rows deterministically then write CSV with DictWriter."""
    rows_sorted = sorted(rows, key=_sort_key)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema, extrasaction="ignore")
        w.writeheader()
        for row in rows_sorted:
            w.writerow(row)


def _get_git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _write_metadata_json(
    path: Path,
    args: argparse.Namespace,
    n_workers: int,
    total_runs: int,
    wrap_into_val_count: int,
    started_at: float,
    finished_at: float,
) -> None:
    payload = {
        "git_sha": _get_git_sha(),
        "started_at": datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat(),
        "finished_at": datetime.fromtimestamp(finished_at, tz=timezone.utc).isoformat(),
        "duration_seconds": round(finished_at - started_at, 2),
        "n_workers": n_workers,
        "total_runs": total_runs,
        "wrap_into_val_count": wrap_into_val_count,
        "args": {k: v for k, v in vars(args).items() if not k.startswith("_")},
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)


# ── CLI ──────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 4 evaluation orchestrator (HEUR-10/11, EVAL-01/02/03, INFR-04)"
    )
    parser.add_argument("--sweep-kind", choices=["main", "ablation", "horizon", "all"], default="all")
    parser.add_argument("--smoke", action="store_true",
                        help="Run a small deterministic subset (<30s)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Pool worker count (default: cpu_count - 1) (D-17)")
    parser.add_argument("--chunksize", type=int, default=64,
                        help="Pool.imap_unordered chunksize (RESEARCH.md Pitfall 7)")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory (default: data/evaluation/run_<ts>/)")
    parser.add_argument("--app-size-mb", type=float, default=64.0)
    parser.add_argument("--expected-completion-min", type=int, default=2880)
    parser.add_argument("--expected-migration-min", type=int, default=5)
    parser.add_argument("--deadline-multiplier", type=float, default=1.5)
    parser.add_argument("--lookahead-hours", type=int, default=48)
    parser.add_argument("--no-network-power", dest="include_network_power",
                        action="store_false")
    parser.set_defaults(include_network_power=True)
    parser.add_argument("--regions-dir", default=None,
                        help="Path to data/regions/ (default: auto-detect from script location). "
                             "Layout: data/regions/{REGION}/US-{REGION}-{GRID}.csv (260502-i16).")
    parser.add_argument("--sample-data-dir", default=None,
                        help="DEPRECATED: legacy alias for --regions-dir from before quick "
                             "task 260502-i16. Honored for one release with a DeprecationWarning.")
    parser.add_argument("--source-grids", nargs="+", default=None,
                        help="Source grids to sweep (e.g. ISNE TVA SWPP). "
                             "Default: all grids that appear under --regions-dir AND have "
                             "an entry in data/hardware/hw_avg.csv (260502-i16).")
    parser.add_argument("--source-regions", nargs="+", default=None,
                        help="DEPRECATED: legacy alias for --source-grids from before quick "
                             "task 260502-i16. Honored for one release with a DeprecationWarning.")
    parser.add_argument("--timestamps", type=int, nargs="+", default=None,
                        help="Override timestamp list (testing only)")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    started_at = time.time()

    # Honor deprecated CLI aliases: emit a one-time DeprecationWarning and copy
    # the legacy value into the new attribute so downstream code only reads the
    # new name. Quick task 260502-i16: --sample-data-dir -> --regions-dir,
    # --source-regions -> --source-grids.
    if args.sample_data_dir is not None and args.regions_dir is None:
        warnings.warn(
            "--sample-data-dir is deprecated; use --regions-dir "
            "(data/regions/{REGION}/US-{REGION}-{GRID}.csv layout). "
            "Honored for one release.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.regions_dir = args.sample_data_dir
    if args.source_regions is not None and args.source_grids is None:
        warnings.warn(
            "--source-regions is deprecated; use --source-grids "
            "(grid identifiers like ISNE / TVA / SWPP). Honored for one release.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.source_grids = args.source_regions

    # Resolve paths
    regions_root = (
        Path(args.regions_dir)
        if args.regions_dir
        else DEFAULT_REGIONS_TREE_DIR
    )
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR_BASE / f"run_{ts_str}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Populate the module-level GRIDS tuple from the regions tree, restricted
    # to grids that have a HW_TABLE entry. Without this filter the simulation
    # would see destinations it cannot hardware-cost (KeyError in get_hardware).
    discovered = set(discover_grids(regions_root))
    hw_grids = set(HW_TABLE.keys())
    usable = discovered & hw_grids
    skipped = sorted(discovered - hw_grids)
    global GRIDS
    GRIDS = tuple(sorted(usable))

    print("=" * 60)
    print("[EVAL] Phase 4 multi-policy evaluation orchestrator")
    print("=" * 60)
    print(f"  Sweep kind:     {args.sweep_kind}")
    print(f"  Smoke mode:     {args.smoke}")
    print(f"  Regions tree:   {regions_root}")
    print(f"  Output dir:     {out_dir}")
    print(f"  Usable grids:   {len(GRIDS)} (intersection of regions-tree and HW_TABLE)")
    if skipped:
        print(f"  Skipped grids:  {len(skipped)} have no hw_avg.csv entry: {skipped}")
    print()

    if not GRIDS:
        print(
            "[EVAL] ERROR: no usable grids found. Check that --regions-dir points "
            "to data/regions/ and that data/hardware/hw_avg.csv contains entries."
        )
        return 2

    # Build the intensity lookup once in the parent (D-23 filter via include_years).
    # allowed_grids restricts the lookup to the GRIDS tuple so the worker pool
    # never sees a destination grid without a hardware spec (260502-i16).
    print("[EVAL] building intensity lookup from regions tree...")
    intensity_lookup = build_intensity_lookup_from_regions_tree(
        regions_root, allowed_grids=GRIDS,
    )
    print(f"[EVAL] intensity_lookup size: {len(intensity_lookup)} entries (2020-2021 only)")

    # Enumerate the sweep
    print("[SWEEP] enumerating run configurations...")
    run_configs = list(generate_sweep(args))  # RESEARCH.md Pitfall 6: list, not generator
    print(f"[SWEEP] total run configs: {len(run_configs)}")
    if not run_configs:
        print("[SWEEP] empty sweep -- nothing to do")
        return 0

    # Pool config (D-17)
    n_workers = args.workers if args.workers else max(1, (mp.cpu_count() or 2) - 1)
    print(f"[POOL] launching {n_workers} workers (chunksize={args.chunksize})")

    # Run the sweep
    results: List[Dict[str, Any]] = []
    with mp.Pool(
        processes=n_workers,
        initializer=_init_worker,
        initargs=(intensity_lookup,),
    ) as pool:
        for r in tqdm(
            pool.imap_unordered(simulate_one_run, run_configs, chunksize=args.chunksize),
            total=len(run_configs),
            desc="[SWEEP]",
        ):
            results.append(r)

    # Aggregate and write outputs (D-18)
    wrap_into_val_count = sum(1 for r in results if r.get("wrapped_into_val"))
    results_csv = out_dir / "results.csv"
    ablation_csv = out_dir / "ablation.csv"
    horizon_csv = out_dir / "horizon.csv"
    metadata_json = out_dir / "metadata.json"

    print("[EVAL] writing outputs...")
    _write_csv(results_csv, results, SCHEMA)
    _write_csv(ablation_csv, [r for r in results if r.get("sweep_kind") == "ablation"], SCHEMA)
    _write_csv(horizon_csv, [r for r in results if r.get("sweep_kind") == "horizon"], SCHEMA)

    finished_at = time.time()
    _write_metadata_json(
        metadata_json, args, n_workers, len(results), wrap_into_val_count,
        started_at, finished_at,
    )

    print()
    print("=" * 60)
    print("[EVAL] DONE")
    print("=" * 60)
    print(f"  Total runs:          {len(results)}")
    print(f"  Wrap into val:       {wrap_into_val_count}")
    print(f"  Duration:            {finished_at - started_at:.1f} s")
    print(f"  Results CSV:         {results_csv}")
    print(f"  Ablation CSV:        {ablation_csv}")
    print(f"  Horizon CSV:         {horizon_csv}")
    print(f"  Metadata JSON:       {metadata_json}")
    return 0


if __name__ == "__main__":   # mandatory spawn guard (RESEARCH.md Pitfall 2)
    sys.exit(main())
