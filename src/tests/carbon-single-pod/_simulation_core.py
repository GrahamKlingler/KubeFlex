#!/usr/bin/env python3
"""Pure simulation core for the carbon-aware migration harness (Phase 4).

This module contains the hour-by-hour expected-simulation loop extracted from
run_carbon_migration_test.py:run_expected_simulation() (Phase 3). The loop is
now I/O-free, print-free, and importable so:

  - run_carbon_migration_test.py (CLI single-run wrapper) calls it as a thin layer
  - evaluate_policies.py (Plan 03 orchestrator) calls it from a multiprocessing
    Pool worker (RESEARCH.md Pattern 2 / D-16)

Contracts:
  - RunConfig: frozen dataclass with all per-run knobs (RESEARCH.md Pattern 2)
  - simulate_one_run(intensity_lookup, cfg): pure function, returns D-19 dict
  - _get_policy_for_config(cfg): cache-free policy factory (RESEARCH.md Pitfall 1)
  - _ablation_id(cfg): D-11 formatter

Join-key naming: this module operates on grid-keyed intensity lookups
(``(grid, ts) -> intensity``) and HW_TABLE (loaded from
``data/hardware/hw_avg.csv``, keyed by grid identifier such as ``ISNE``).
The cluster-execution path still uses region-keyed lookups; this divergence
is intentional (see quick task 260502-i16).

Data discipline (D-22, D-23, RESEARCH.md Pitfall 5):
  - check_split_access raises RuntimeError on any 2022 timestamp
  - end-of-year wrap into val (2021) sets wrapped_into_val=True (no print; orchestrator aggregates)
"""

import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Add controller package to import path (project convention; CLAUDE.md "Import Organization")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics.base import BasePolicy  # noqa: E402
from heuristics.data_splits import check_split_access  # noqa: E402
from heuristics.hardware import HW_TABLE  # noqa: E402
from heuristics.policies import (  # noqa: E402
    Policy1,
    Policy2,
    Policy3,
    Policy4,
    Policy5,
    lookup_intensity,
)
from heuristics.overhead import NETWORK_POWER_WATTS  # noqa: E402
from heuristics.policy_heuristic import HeuristicPolicy  # noqa: E402


# ── RunConfig ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunConfig:
    """Immutable specification for a single expected-simulation run.

    See RESEARCH.md Pattern 2 and CONTEXT.md D-08, D-09, D-13, D-19 for field semantics.

    ``source_grid`` identifies the initial power grid (e.g. ``ISNE``,
    ``CISO``); the join key was renamed from ``source_region`` in quick task
    260502-i16 when the simulation moved to grid-keyed forecasting data.
    """
    start_ts: int
    source_grid: str
    policy_id: int                          # 1..6
    app_size_mb: float = 64.0
    expected_completion_min: int = 2880     # 48 h canonical
    expected_migration_min: int = 5
    deadline_multiplier: float = 1.5
    lookahead_hours: int = 48
    hw_weighting: bool = True               # HEUR-10 toggle
    overhead_cost: bool = True              # HEUR-10 toggle
    deadline_gate: bool = True              # HEUR-10 toggle
    include_network_power: bool = True      # sub-toggle of overhead_cost
    network_power_watts: float = NETWORK_POWER_WATTS  # ablation knob, forwarded to HeuristicPolicy
    use_hw: bool = True                     # P1..P5 hardware scaling
    sweep_kind: str = "main"                # 'main' | 'ablation' | 'horizon'


# ── Helpers ──────────────────────────────────────────────────────────

def _ablation_id(cfg: RunConfig) -> str:
    """Return D-11 ablation cell label, e.g. 'HW1_OH1_DL1' or 'HW0_OH0_DL0'."""
    return "HW{}_OH{}_DL{}".format(int(cfg.hw_weighting), int(cfg.overhead_cost), int(cfg.deadline_gate))


def _get_policy_for_config(cfg: RunConfig) -> BasePolicy:
    """Cache-free policy factory.

    RESEARCH.md Pitfall 1: the parallel sweep needs a fresh HeuristicPolicy per
    ablation cell. This factory does NOT cache instances. Cheap to call (~us).
    """
    if cfg.policy_id == 6:
        return HeuristicPolicy(
            app_size_mb=cfg.app_size_mb,
            expected_total_minutes=cfg.expected_completion_min,
            deadline_multiplier=cfg.deadline_multiplier,
            include_network_power=cfg.include_network_power,
            network_power_watts=cfg.network_power_watts,
            lookahead_hours=cfg.lookahead_hours,
            hw_weighting=cfg.hw_weighting,
            overhead_cost=cfg.overhead_cost,
            deadline_gate=cfg.deadline_gate,
        )
    cls_map = {1: Policy1, 2: Policy2, 3: Policy3, 4: Policy4, 5: Policy5}
    return cls_map[cfg.policy_id]()


def _simulate_policy_decision(
    policy_obj,
    intensity_lookup,
    grids,
    current_grid,
    sim_timestamp,
    expected_duration_hours=1,
    elapsed_hours=0.0,
    **kwargs
):
    """Thin dispatcher: call policy.decide() and return (should_migrate, target_grid).

    Quick task 260502-i16: parameters renamed regions -> grids, current_region ->
    current_grid to match the new grid-keyed expected-simulation path.
    """
    return policy_obj.decide(
        intensity_lookup,
        grids,
        current_grid,
        sim_timestamp,
        expected_duration_hours,
        elapsed_hours=elapsed_hours,
        **kwargs,
    )


# ── Pure simulation ──────────────────────────────────────────────────

def simulate_one_run(intensity_lookup, cfg):
    # type: (Dict, RunConfig) -> Dict[str, Any]
    """Run the expected simulation for ONE RunConfig. Pure: no I/O, no prints.

    Mirrors the hour-by-hour semantics of run_expected_simulation() (lines 423-531
    of run_carbon_migration_test.py at Phase 3 head). Returns a dict matching the
    D-19 unified results schema, plus a side-channel `wrapped_into_val` flag.

    Args:
        intensity_lookup: Dict mapping (region, sim_timestamp) -> float intensity.
        cfg: RunConfig with all per-run parameters.

    Returns:
        Dict with D-19 schema keys plus 'wrapped_into_val' side-channel.

    Raises:
        RuntimeError: If cfg.start_ts falls in the 2022 test period (D-23).
        ValueError: If cfg.start_ts is outside all defined data ranges.
    """
    # Belt + suspenders 2022 guard (orchestrator filters first; trust nothing).
    # Raises RuntimeError if cfg.start_ts is in the 2022 test period (D-23).
    split_at_start = check_split_access(cfg.start_ts)
    # split_at_start is "train" or "val"; we tolerate both as start points.

    # 260512-kfc: useful-work-driven termination. The 260511-jce sim core used a
    # fixed-length `for hour in range(total_sim_hours)` loop where
    # total_sim_hours = ceil(expected_completion_min / 60.0). That treated
    # migration minutes as if they counted toward useful job completion, so a
    # policy that migrated still finished in the same 48 wall-clock hours.
    # The new model accounts for migration minutes separately: useful minutes
    # per hour shrink by the in-progress migration's per-hour minute consumption,
    # and the wall-clock loop terminates only when `useful_minutes_completed`
    # reaches `useful_minutes_target = cfg.expected_completion_min`. Total
    # wall-clock duration is now a VARIABLE derived value: hours_tracked =
    # ceil((useful_minutes_target + total_migration_minutes_consumed) / 60).
    # The 260511-jce minute-granular migration-carbon lump charge at the decision
    # hour is UNCHANGED.
    migration_fraction_h = cfg.expected_migration_min / 60.0  # float hours; 30 min -> 0.5
    migration_seconds_real = cfg.expected_migration_min * 60.0

    # Derive available grids from the intensity_lookup keys so the pure function
    # sees the exact same grid set as the CLI wrapper (which builds the lookup
    # from data/regions/{REGION}/{GRID}.csv). Using HW_TABLE.keys() would add
    # grids absent from the forecast, causing the heuristic to treat them as
    # 0-carbon destinations and producing different migration decisions.
    # HW_TABLE is now grid-keyed (data/hardware/hw_avg.csv).
    grids = sorted(set(g for g, _ts in intensity_lookup.keys()))

    # Validate cfg.source_grid is in the lookup; otherwise the simulation would
    # silently produce zero-carbon nonsense (every lookup_intensity returns None
    # via fuzzy fallback, total_carbon stays at 0, savings_pct=0). That is
    # indistinguishable from a legitimate Policy-1 baseline result and would
    # corrupt the unified results.csv (CR-03).
    if cfg.source_grid not in grids:
        raise ValueError(
            "[SIM] source_grid={!r} not present in intensity_lookup; "
            "available grids: {}".format(cfg.source_grid, grids)
        )

    # State
    current_grid = cfg.source_grid
    initial_grid = cfg.source_grid
    migration_count = 0
    total_carbon = 0.0
    baseline_carbon = 0.0
    hours_tracked = 0
    # 260512-kfc: state across hours; replaces `migrating_cooldown`. Tracks how
    # many minutes of the in-progress migration are still pending. The pod is
    # unavailable for useful work for these minutes; carbon still accumulates
    # on the current grid (target-side, since current_grid was switched to
    # target at the decision hour, matching the 260511-jce semantics).
    migration_minutes_remaining = 0
    useful_minutes_completed = 0
    useful_minutes_target = cfg.expected_completion_min
    # 260512-kfc safety cap: pathological policies (e.g. m=60 every hour with
    # rotating-cheapest fixtures) would never advance useful_minutes_completed.
    # Cap at 2x the target's hour-equivalent so a 48-hour useful job can't take
    # more than ~96 wall-clock hours. RuntimeError fires loudly if exceeded so
    # the policy / fixture issue is visible.
    max_iter_hours = int(math.ceil(2 * useful_minutes_target / 60.0))
    # Additive diagnostic (quick task 260511-kqo): list of successful migration
    # destinations in chronological order. Does NOT include the source grid.
    # Empty list when no migrations occurred. Existing tests/callers ignore
    # unknown return-dict keys.
    dest_grids_visited = []

    policy_obj = _get_policy_for_config(cfg)

    hour = 0
    while useful_minutes_completed < useful_minutes_target:
        if hour >= max_iter_hours:
            raise RuntimeError(
                "[SIM] simulation exceeded safety cap of {} hours; policy {} "
                "may be migrating pathologically (cfg={!r})".format(
                    max_iter_hours, cfg.policy_id, cfg,
                )
            )

        sim_ts = cfg.start_ts + hour * 3600

        raw_intensity = lookup_intensity(intensity_lookup, current_grid, sim_ts)
        raw_baseline = lookup_intensity(intensity_lookup, initial_grid, sim_ts)

        # Apply hardware scaling when use_hw is set.
        # HW_TABLE is now grid-keyed (data/hardware/hw_avg.csv).
        if cfg.use_hw and raw_intensity is not None:
            intensity = raw_intensity * HW_TABLE[current_grid].power_per_core
        else:
            intensity = raw_intensity
        if cfg.use_hw and raw_baseline is not None:
            baseline_intensity = raw_baseline * HW_TABLE[initial_grid].power_per_core
        else:
            baseline_intensity = raw_baseline

        if intensity is not None:
            total_carbon += intensity
        if baseline_intensity is not None:
            baseline_carbon += baseline_intensity
        hours_tracked += 1

        # 260512-kfc: per-hour migration-minutes accounting. If a migration is
        # in progress from a prior hour, consume up to 60 of those minutes
        # before considering a new decision. Only when migration_minutes_remaining
        # reaches 0 may a new migration decision be made.
        if migration_minutes_remaining > 0:
            migration_minutes_this_hour = min(60, migration_minutes_remaining)
            migration_minutes_remaining -= migration_minutes_this_hour
            # No new migration decision this hour; still mid-migration.
        else:
            migration_minutes_this_hour = 0
            # 260512-kfc: tighter "hours of useful work remaining" estimate
            # than the prior `total_sim_hours - hour`; preserves the prior
            # intent without inflating the policy's deadline view by the
            # safety-cap slack.
            remaining_hours = max(
                1,
                int(math.ceil(
                    (useful_minutes_target - useful_minutes_completed) / 60.0
                )),
            )
            should_migrate, target_grid = _simulate_policy_decision(
                policy_obj,
                intensity_lookup,
                grids,
                current_grid,
                sim_ts,
                expected_duration_hours=remaining_hours,
                elapsed_hours=float(hour),
                forecast_window=24,
                cost_multiplier=3.0,
                migration_seconds=migration_seconds_real,
                use_hw=cfg.use_hw,
            )
            if should_migrate and target_grid:
                migration_count += 1
                # 260511-jce: minute-granular migration carbon (UNCHANGED).
                # `intensity` is the source-grid intensity at the decision hour,
                # already HW-scaled iff cfg.use_hw=True by the loop body above.
                if intensity is not None:
                    migration_carbon = migration_fraction_h * intensity
                    total_carbon += migration_carbon
                # 260512-kfc: migration starts immediately at the decision hour
                # and consumes up to 60 min of this hour. Replaces the prior
                # hour-quantized `migrating_cooldown = max(0, ceil((m-60)/60))`
                # approach with minute-granular tracking.
                migration_minutes_remaining = cfg.expected_migration_min
                consumed_now = min(60, migration_minutes_remaining)
                migration_minutes_this_hour = consumed_now
                migration_minutes_remaining -= consumed_now
                current_grid = target_grid
                # 260511-kqo: track destinations for downstream diagnostics.
                dest_grids_visited.append(target_grid)

        # 260512-kfc: useful minutes this hour = whatever's left of the 60-min
        # window after subtracting in-progress migration time.
        useful_minutes_this_hour = 60 - migration_minutes_this_hour
        useful_minutes_completed += useful_minutes_this_hour
        hour += 1

    # 260512-kfc: final wall-clock duration is a derived per-policy value
    # (variable; was previously a fixed precomputed constant). Used below by
    # the end-of-year-wrap detection block.
    total_sim_hours = hour

    # Derived metrics. The CLI wrapper computes total_runtime_ms,
    # migration_overhead_ms, migration_fraction, migration_carbon_est, and
    # job_time_carbon for its own carbon_log.csv emission. None of these are
    # part of the D-19 unified schema returned here, so we do not compute them
    # in the pure core (WR-02). If the schema is ever extended to include them,
    # add the derivations back here and surface them in the return dict so the
    # two paths really do share the same fields.
    if baseline_carbon > 0:
        savings = baseline_carbon - total_carbon
        savings_pct = (savings / baseline_carbon) * 100.0
    else:
        savings_pct = 0.0

    # End-of-year wrap detection (D-22, RESEARCH.md Pitfall 4).
    # If the final lookup timestamp falls in the val period but start was train,
    # set the side-channel flag (no print; orchestrator aggregates in metadata.json).
    # Compute the actual furthest lookup based on policy_id so non-Policy-6 runs
    # don't get spuriously flagged as "wrapped into val" because of the unused
    # cfg.lookahead_hours default (WR-05).
    if cfg.policy_id == 6:
        extra_hours = cfg.lookahead_hours
    elif cfg.policy_id in (3, 4):
        extra_hours = 24  # forecast_window for forecast-based policies
    elif cfg.policy_id == 5:
        extra_hours = 1   # next-hour only
    else:
        extra_hours = 0   # Policy 1 doesn't look ahead; Policy 2 only looks at current hour
    final_lookup_ts = cfg.start_ts + (total_sim_hours + extra_hours) * 3600
    try:
        final_split = check_split_access(final_lookup_ts)
        wrapped_into_val = (final_split == "val") and (split_at_start == "train")
    except RuntimeError:
        # final_lookup_ts fell into the 2022 test period -- should be impossible for
        # 2020 starts within the supported lookahead range; re-raise so the orchestrator
        # notices immediately rather than silently producing bad results.
        raise

    return {
        "policy": cfg.policy_id,
        "source_grid": cfg.source_grid,
        "start_ts": cfg.start_ts,
        "start_datetime": datetime.fromtimestamp(cfg.start_ts, tz=timezone.utc).isoformat(),
        "hw_weighting": cfg.hw_weighting if cfg.policy_id == 6 else "",
        "overhead_cost": cfg.overhead_cost if cfg.policy_id == 6 else "",
        "deadline_gate": cfg.deadline_gate if cfg.policy_id == 6 else "",
        "ablation_id": _ablation_id(cfg) if cfg.policy_id == 6 else "n/a",
        "lookahead_hours": cfg.lookahead_hours if cfg.policy_id == 6 else "",
        "app_size_mb": cfg.app_size_mb,
        "expected_completion_min": cfg.expected_completion_min,
        "deadline_multiplier": cfg.deadline_multiplier,
        "total_carbon_gco2": round(total_carbon, 1),
        "baseline_carbon_gco2": round(baseline_carbon, 1),
        "savings_pct": round(savings_pct, 3),
        "migration_count": migration_count,
        "completed_hours": hours_tracked,
        # 260512-kfc: useful minutes accumulated by the end of the run. Equals
        # cfg.expected_completion_min plus the final-hour overshoot (bounded by
        # min(60, 60 - migration_minutes_this_hour)). Additive return field.
        "useful_minutes_completed": useful_minutes_completed,
        "sweep_kind": cfg.sweep_kind,
        "wrapped_into_val": wrapped_into_val,  # side-channel for metadata.json (D-22)
        # 260511-kqo: additive diagnostic — chronological list of successful
        # migration destinations (excluding source). Empty list = no migrations.
        "dest_grids_visited": dest_grids_visited,
    }
