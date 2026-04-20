#!/usr/bin/env python3
"""Abstract base class for all KubeFlex carbon scheduling policies (1-6)."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple


class BasePolicy(ABC):
    """Abstract base for all KubeFlex carbon scheduling policies (1-6).

    Subclasses implement decide() which evaluates one simulated hour and
    returns (should_migrate, target_region). This enforces a uniform interface
    across all policies, enabling the simulation harness to dispatch to any
    policy via a thin caller (D-11, D-13).
    """

    @abstractmethod
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

        Called once per simulated hour by the simulation harness. Each policy
        applies its own decision logic and returns the migration outcome.

        Args:
            intensity_lookup: Mapping from (region, unix_timestamp) to carbon
                intensity (gCO2eq/kWh). Populated by the simulation harness
                from the forecast cache or database query.
            regions: List of available destination region identifiers
                (e.g., ['NE', 'TEN', 'CENT']).
            current_region: Region where the workload is currently running.
            sim_timestamp: Current simulation time as a Unix timestamp (int).
                Represents the start of the current simulated hour.
            remaining_hours: Estimated hours remaining in the workload. Used
                by deadline-aware and forecast-based policies.
            elapsed_hours: Hours the workload has already executed on
                current_region. Defaults to 0.0. Used by policies that adjust
                remaining time based on hardware differences.
            **kwargs: Policy-specific parameters (e.g., app_size_mb,
                deadline_multiplier, include_network_power for Policy 6).
                Non-heuristic policies ignore these kwargs.

        Returns:
            A 2-tuple (should_migrate, target_region):
                - should_migrate (bool): True if the policy recommends
                  migrating at this hour, False otherwise.
                - target_region (Optional[str]): The recommended destination
                  region identifier if should_migrate is True, else None.
        """
        ...
