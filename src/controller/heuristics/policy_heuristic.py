#!/usr/bin/env python3
"""Policy 6: HeuristicPolicy -- deadline-aware, forecast-based, overhead-cost-accounting migration.

This is the core thesis contribution. HeuristicPolicy is a direct translation
of the migrate_decision() pseudocode from heuristic.txt. Key features:

  - Size-based overhead estimation: checkpoint, transfer, restore overhead are
    estimated from app_size_mb using calibrated linear-fit functions (overhead.py).
  - Hardware-adjusted remaining time: estimate_remaining_hours() scales the
    remaining workload duration based on source hardware clock speed.
  - Forecast stay-vs-migrate comparison: sums forecasted carbon intensity (weighted
    by hardware power_per_core) over remaining simulated hours for the current
    region (stay cost) and each candidate destination (migrate cost).
  - Migration carbon accounting: checkpoint carbon (source HW, source intensity),
    transfer carbon (network power, avg intensity), restore carbon (dest HW, dest
    intensity) are included in the migrate cost.
  - Deadline gate: migration is blocked if time_left + mig_time > deadline_remaining,
    preventing migrations that could not complete before the job deadline.
  - Togglable network power: include_network_power flag enables clean ablation
    studies (Phase 4, HEUR-10) by excluding the network transfer carbon component.

Reference: heuristic.txt -- migrate_decision() pseudocode.
"""

import math
from typing import Dict, List, Optional, Tuple

from heuristics.base import BasePolicy
from heuristics.hardware import get_hardware
from heuristics.overhead import (
    ckpt_overhead,
    send_overhead,
    restore_overhead,
    NETWORK_POWER_WATTS,
)
from heuristics.runtime import estimate_remaining_hours
from heuristics.policies import lookup_intensity


def _accumulate_carbon_window(
    intensity_lookup,
    grid: str,
    decision_ts: int,
    window_start_h: float,
    window_length_h: float,
    weight: float,
    lookahead_cap_h: int,
) -> float:
    """Sum HW-weighted carbon over [window_start_h, window_start_h + window_length_h)
    relative to decision_ts. Reads hourly published data with piecewise-constant
    interpretation: hour x's value applies to [x, x+1). Fractional weights at
    the first and last hours; full weight for interior hours. All lookups land
    on integer-hour boundaries to preserve the lookup_intensity fast path
    (quick task 260505-fvu, ~107000x speedup).

    Args:
        intensity_lookup: Mapping from (grid, unix_timestamp) -> intensity.
        grid: Grid identifier to look up.
        decision_ts: Unix timestamp at the decision moment (decision_hour).
        window_start_h: Hours after decision_ts where the window begins.
        window_length_h: Length of the window in hours (may be fractional).
        weight: Multiplicative weight (e.g., HW power_per_core, or 1.0).
        lookahead_cap_h: Cap on window length to prevent O(n) blowup.

    Returns:
        Sum of weight x hourly_intensity x hours_in_each_hour-segment.
    """
    end_h = window_start_h + min(window_length_h, lookahead_cap_h)
    if window_start_h >= end_h:
        return 0.0

    first_full = math.ceil(window_start_h)
    last_full = math.floor(end_h)
    carbon = 0.0

    # Partial first hour: [window_start_h, first_full) reads hour (first_full - 1)
    if window_start_h < first_full:
        partial = min(first_full, end_h) - window_start_h
        ts = decision_ts + (first_full - 1) * 3600
        val = lookup_intensity(intensity_lookup, grid, ts)
        if val is not None:
            carbon += weight * val * partial

    # Full interior hours: [first_full, last_full) each contribute 1.0 x hour h
    for h in range(first_full, last_full):
        ts = decision_ts + h * 3600
        val = lookup_intensity(intensity_lookup, grid, ts)
        if val is not None:
            carbon += weight * val

    # Partial last hour: [last_full, end_h) reads hour last_full
    if last_full < end_h and last_full >= first_full:
        partial = end_h - last_full
        ts = decision_ts + last_full * 3600
        val = lookup_intensity(intensity_lookup, grid, ts)
        if val is not None:
            carbon += weight * val * partial

    return carbon


class HeuristicPolicy(BasePolicy):
    """Policy 6: full migrate_decision() from heuristic.txt.

    Implements deadline-aware, forecast-based, migration-overhead-accounting
    carbon scheduling. This policy accounts for the carbon cost of migrating
    itself and only recommends migration when the net benefit (stay_carbon -
    total_migrate_carbon) is positive.
    """

    def __init__(
        self,
        app_size_mb: float,
        expected_total_minutes: int,
        deadline_multiplier: float = 1.5,
        include_network_power: bool = True,
        network_power_watts: float = NETWORK_POWER_WATTS,
        lookahead_hours: int = 48,
        hw_weighting: bool = True,
        overhead_cost: bool = True,
        deadline_gate: bool = True,
        use_empirical_runtime: bool = False,
    ) -> None:
        """Initialize HeuristicPolicy.

        Args:
            app_size_mb: Application checkpoint size in megabytes. Drives
                overhead estimation functions. Provided via --app-size-mb CLI
                flag in simulation mode (D-03).
            expected_total_minutes: Total expected workload duration in minutes,
                as measured on the reference hardware. Used to compute
                deadline_hours and as input to estimate_remaining_hours().
            deadline_multiplier: Multiplier applied to expected_total_minutes
                to derive the job deadline in hours (D-16). Default 1.5x.
                E.g., 48h expected * 1.5 = 72h deadline.
            include_network_power: If True, include the network transfer carbon
                component in migration_carbon (D-08). Set False for ablation
                studies. Default True.
            network_power_watts: Network switch/NIC power in watts for the
                transfer carbon calculation (D-09). Defaults to NETWORK_POWER_WATTS
                (15.0 W).
            lookahead_hours: Maximum hours to sum in stay/migrate carbon loops.
                Caps O(n) inner loop length to prevent quadratic blowup on long
                jobs. Default 48.
            hw_weighting: If True, weight stay/migrate carbon sums by
                hw[r].power_per_core (HEUR-05 default behavior). If False,
                sums use raw forecast intensity per HEUR-10 / D-09 ablation
                semantics. Default True.
            overhead_cost: If True, account for checkpoint + transfer +
                restore carbon in migration_carbon (HEUR-02/03/04 default
                behavior). If False, migration_carbon = 0 per HEUR-10 / D-09
                ablation. Default True.
            deadline_gate: If True, block migration when time_left + mig_time
                exceeds deadline_remaining (HEUR-08 default behavior). If
                False, skip the deadline check entirely per HEUR-10 / D-09
                ablation. Default True.
            use_empirical_runtime: If True, use sysbench-backed empirical
                runtime estimation (260515-jav). Falls back silently to the
                clock-speed proxy when sysbench data is missing for either
                grid endpoint. Default False (clock-speed proxy, byte-
                identical to pre-260515-jav behavior). The decide() call
                hardcodes by_grid=True because the sim path is grid-keyed; a
                future cluster-path follow-up will need either a separate
                kwarg or a hostname-keyed decide() variant.
        """
        self.app_size_mb = app_size_mb
        self.expected_total_minutes = expected_total_minutes
        self.deadline_multiplier = deadline_multiplier
        self.include_network_power = include_network_power
        self.network_power_watts = network_power_watts
        self.lookahead_hours = lookahead_hours
        self.hw_weighting = hw_weighting
        self.overhead_cost = overhead_cost
        self.deadline_gate = deadline_gate
        self.use_empirical_runtime = use_empirical_runtime
        self.last_skip_reason: Optional[str] = None

    def decide(
        self,
        intensity_lookup: Dict,
        grids: List[str],
        current_grid: str,
        sim_timestamp: int,
        remaining_hours: int,
        elapsed_hours: float = 0.0,
        **kwargs,
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate whether to migrate and, if so, to which grid.

        Implements migrate_decision() from heuristic.txt. All time quantities
        use hours as the unit to match the simulation loop granularity.
        Seconds-domain quantities carry a _s suffix; hours-domain carry _h.

        Args:
            intensity_lookup: Mapping from (grid, unix_timestamp) -> carbon
                intensity (gCO2eq/kWh).
            grids: Available destination grid identifiers.
            current_grid: Grid where the workload is currently running.
            sim_timestamp: Current simulation time as Unix timestamp (int).
            remaining_hours: Nominal remaining hours (ignored; computed from
                expected_total_minutes and elapsed_hours internally).
            elapsed_hours: Hours already completed on current_grid hardware.
            **kwargs: Ignored (provided for ABC compatibility).

        Returns:
            (should_migrate, target_grid) tuple.
        """
        # Step 1: reset per-call state
        self.last_skip_reason = None

        # Step 2: hardware lookup
        src_hw = get_hardware(current_grid)
        hw = {g: get_hardware(g) for g in set(grids) | {current_grid}}

        # Step 3: compute per-destination overhead (hours)
        ckpt_oh_s = ckpt_overhead(self.app_size_mb, src_hw)
        overhead_h: Dict[str, float] = {}
        for g in grids:
            if g == current_grid:
                overhead_h[g] = 0.0
            else:
                send_oh_s = send_overhead(src_hw, hw[g], self.app_size_mb)
                rest_oh_s = restore_overhead(self.app_size_mb, hw[g])
                overhead_h[g] = (ckpt_oh_s + send_oh_s + rest_oh_s) / 3600.0

        # Step 4: hardware-adjusted remaining time (stay-case: src->src)
        # 260515-jav: optional sysbench-backed empirical estimator. Falls back
        # silently to the clock-speed proxy when either endpoint lacks
        # sysbench data, so the default-False path is byte-identical to the
        # pre-260515-jav behavior. by_grid=True because decide() only has
        # grid names; the cluster-path follow-up will need hostnames.
        if self.use_empirical_runtime:
            from heuristics.runtime import estimate_remaining_hours_empirical
            time_left_h = estimate_remaining_hours_empirical(
                self.expected_total_minutes, elapsed_hours,
                src_hw, src_hw,
                source_key=current_grid, dest_key=current_grid,
                by_grid=True,
            )
        else:
            time_left_h = estimate_remaining_hours(
                self.expected_total_minutes, elapsed_hours, src_hw, src_hw
            )

        # Step 5: deadline remaining
        total_hours = self.expected_total_minutes / 60.0
        deadline_hours = total_hours * self.deadline_multiplier
        deadline_remaining_h = max(0.0, deadline_hours - elapsed_hours)

        # Step 6: stay_carbon via fractional-window accumulator (260526-lgv).
        # Piecewise-constant interpretation: hour x's published intensity
        # applies to the entire [x, x+1) interval. Fractional weights at
        # window boundaries; integer-hour timestamps preserve the
        # lookup_intensity fast path (260505-fvu). hw_weighting toggle
        # (HEUR-10, D-09): when False, weight is 1.0 (raw intensity).
        stay_weight = hw[current_grid].power_per_core if self.hw_weighting else 1.0
        stay_carbon = _accumulate_carbon_window(
            intensity_lookup, current_grid, sim_timestamp,
            window_start_h=0.0,
            window_length_h=time_left_h,
            weight=stay_weight,
            lookahead_cap_h=self.lookahead_hours,
        )

        # Step 7: initialize best as stay
        decision_grid = current_grid
        best_carbon = stay_carbon

        # Step 8: evaluate each candidate destination (HEUR-06)
        src_intensity_now = lookup_intensity(intensity_lookup, current_grid, sim_timestamp) or 0.0
        ckpt_oh_h = ckpt_oh_s / 3600.0

        for dest in grids:
            if dest == current_grid:
                continue

            mig_time_h = overhead_h[dest]

            # Deadline gate (HEUR-08, D-17). deadline_gate toggle (HEUR-10,
            # D-09): when False, skip the deadline check entirely.
            if self.deadline_gate and time_left_h + mig_time_h > deadline_remaining_h:
                self.last_skip_reason = "deadline_gate"
                continue

            # Migration carbon components (D-06, D-07)
            dst_intensity_now = lookup_intensity(intensity_lookup, dest, sim_timestamp) or 0.0
            send_oh_h = send_overhead(src_hw, hw[dest], self.app_size_mb) / 3600.0
            rest_oh_h = restore_overhead(self.app_size_mb, hw[dest]) / 3600.0

            # overhead_cost toggle (HEUR-10, D-09): when False, zero out the
            # migration carbon entirely; network_power becomes irrelevant.
            if self.overhead_cost:
                migration_carbon = (
                    ckpt_oh_h * src_hw.power_per_core * src_intensity_now
                    + rest_oh_h * hw[dest].power_per_core * dst_intensity_now
                )
                if self.include_network_power:
                    migration_carbon += (
                        send_oh_h
                        * self.network_power_watts
                        * (src_intensity_now + dst_intensity_now)
                        / 2.0
                    )
            else:
                migration_carbon = 0.0
                # network_power becomes irrelevant when overhead_cost is off (D-09)

            # Destination running carbon via fractional-window accumulator
            # (260526-lgv). Window starts at fractional offset mig_time_h
            # (no rounding) and has fractional length dest_window_h.
            # Piecewise-constant: hour x's intensity applies to [x, x+1),
            # so a 30-min migration consumes 0.5h of hour 0 + 0.5h of hour 1
            # (instead of the prior bug which collapsed to hours 0..N-1).
            # Integer-hour timestamps inside the helper preserve the
            # lookup_intensity fast path (260505-fvu). hw_weighting toggle
            # (HEUR-10, D-09) mirrors stay-loop semantics.
            #
            # 260515-jav: when use_empirical_runtime=True, scale the
            # destination horizon by perf_ratio(src, dest) so a faster
            # destination uses a SHORTER horizon and a slower one uses a
            # LONGER horizon. The stay-case (src->src) is ratio=1.0 by
            # definition, so the empirical path surfaces only here. When
            # use_empirical_runtime is False, dest_window_h == time_left_h
            # and behavior is byte-identical to pre-260515-jav.
            if self.use_empirical_runtime:
                from heuristics.sysbench import perf_ratio as _perf_ratio
                dest_ratio = _perf_ratio(current_grid, dest, by_grid=True)
                dest_window_h = max(0.0, time_left_h * dest_ratio)
            else:
                dest_window_h = time_left_h

            dest_weight = hw[dest].power_per_core if self.hw_weighting else 1.0
            dest_run_carbon = _accumulate_carbon_window(
                intensity_lookup, dest, sim_timestamp,
                window_start_h=mig_time_h,
                window_length_h=dest_window_h,
                weight=dest_weight,
                lookahead_cap_h=self.lookahead_hours,
            )

            total_carbon = migration_carbon + dest_run_carbon

            if total_carbon < best_carbon:
                best_carbon = total_carbon
                decision_grid = dest

        # Step 9: return migration decision
        if decision_grid != current_grid:
            return True, decision_grid
        return False, None
