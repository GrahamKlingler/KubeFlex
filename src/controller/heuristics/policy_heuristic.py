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

from typing import Dict, List, Optional, Tuple

from heuristics.base import BasePolicy
from heuristics.hardware import get_hardware
from heuristics.overhead import (
    ckpt_overhead,
    send_overhead,
    restore_overhead,
    total_migration_time_h,
    NETWORK_POWER_WATTS,
)
from heuristics.runtime import estimate_remaining_hours
from heuristics.policies import lookup_intensity


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
        self.last_skip_reason: Optional[str] = None

    def decide(
        self,
        intensity_lookup: Dict,
        regions: List[str],
        current_region: str,
        sim_timestamp: int,
        remaining_hours: int,
        elapsed_hours: float = 0.0,
        **kwargs,
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate whether to migrate and, if so, to which region.

        Implements migrate_decision() from heuristic.txt. All time quantities
        use hours as the unit to match the simulation loop granularity.
        Seconds-domain quantities carry a _s suffix; hours-domain carry _h.

        Args:
            intensity_lookup: Mapping from (region, unix_timestamp) -> carbon
                intensity (gCO2eq/kWh).
            regions: Available destination region identifiers.
            current_region: Region where the workload is currently running.
            sim_timestamp: Current simulation time as Unix timestamp (int).
            remaining_hours: Nominal remaining hours (ignored; computed from
                expected_total_minutes and elapsed_hours internally).
            elapsed_hours: Hours already completed on current_region hardware.
            **kwargs: Ignored (provided for ABC compatibility).

        Returns:
            (should_migrate, target_region) tuple.
        """
        # Step 1: reset per-call state
        self.last_skip_reason = None

        # Step 2: hardware lookup
        src_hw = get_hardware(current_region)
        hw = {r: get_hardware(r) for r in set(regions) | {current_region}}

        # Step 3: compute per-destination overhead (hours)
        ckpt_oh_s = ckpt_overhead(self.app_size_mb, src_hw)
        overhead_h: Dict[str, float] = {}
        for r in regions:
            if r == current_region:
                overhead_h[r] = 0.0
            else:
                send_oh_s = send_overhead(src_hw, hw[r], self.app_size_mb)
                rest_oh_s = restore_overhead(self.app_size_mb, hw[r])
                overhead_h[r] = (ckpt_oh_s + send_oh_s + rest_oh_s) / 3600.0

        # Step 4: hardware-adjusted remaining time (stay-case: src->src)
        time_left_h = estimate_remaining_hours(
            self.expected_total_minutes, elapsed_hours, src_hw, src_hw
        )
        time_left_int = max(1, round(time_left_h))

        # Step 5: deadline remaining
        total_hours = self.expected_total_minutes / 60.0
        deadline_hours = total_hours * self.deadline_multiplier
        deadline_remaining_h = max(0.0, deadline_hours - elapsed_hours)

        # Step 6: stay_carbon -- weighted by hardware power_per_core (HEUR-05)
        # capped to self.lookahead_hours to prevent O(n) blowup on long jobs.
        # hw_weighting toggle (HEUR-10, D-09): when False, drop the
        # power_per_core multiplier and sum raw forecast intensity.
        stay_carbon = 0.0
        for h in range(min(time_left_int, self.lookahead_hours)):
            ts = sim_timestamp + h * 3600
            val = lookup_intensity(intensity_lookup, current_region, ts)
            if val is not None:
                weight = hw[current_region].power_per_core if self.hw_weighting else 1.0
                stay_carbon += weight * val

        # Step 7: initialize best as stay
        decision_region = current_region
        best_carbon = stay_carbon

        # Step 8: evaluate each candidate destination (HEUR-06)
        src_intensity_now = lookup_intensity(intensity_lookup, current_region, sim_timestamp) or 0.0
        ckpt_oh_h = ckpt_oh_s / 3600.0

        for dest in regions:
            if dest == current_region:
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

            # Destination running carbon over remaining time (offset by migration duration)
            # capped to self.lookahead_hours (same cap as stay_carbon for consistency).
            # hw_weighting toggle (HEUR-10, D-09): mirror the stay-loop semantics.
            dest_run_carbon = 0.0
            offset_s = int(mig_time_h * 3600)
            for h in range(min(time_left_int, self.lookahead_hours)):
                ts = sim_timestamp + offset_s + h * 3600
                val = lookup_intensity(intensity_lookup, dest, ts)
                if val is not None:
                    dest_weight = hw[dest].power_per_core if self.hw_weighting else 1.0
                    dest_run_carbon += dest_weight * val

            total_carbon = migration_carbon + dest_run_carbon

            if total_carbon < best_carbon:
                best_carbon = total_carbon
                decision_region = dest

        # Step 9: return migration decision
        if decision_region != current_region:
            return True, decision_region
        return False, None
