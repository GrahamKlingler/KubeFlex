#!/usr/bin/env python3
"""Policy classes for KubeFlex carbon scheduling (Policies 1-5).

Extracted from run_carbon_migration_test.simulate_policy_decision() and wrapped
in the BasePolicy ABC interface. Each policy implements decide() with logic
identical to the original if-elif branches in the simulation harness.

Helper functions lookup_intensity() and get_min_region_at() are also exported
for use by HeuristicPolicy (Policy 6) and the simulation harness dispatcher.
"""

from typing import Dict, List, Optional, Tuple

from heuristics.base import BasePolicy
from heuristics.hardware import HW_TABLE, get_hardware


# ---------------------------------------------------------------------------
# Shared helper functions (originally in run_carbon_migration_test.py)
# ---------------------------------------------------------------------------

def lookup_intensity(intensity_lookup, region, sim_timestamp, strict=False):
    """Look up intensity for a region at a given timestamp, with fuzzy matching.

    With ``strict=False`` (default), falls back to the nearest timestamp within
    a 2 h (7200 s) tolerance to tolerate minor forecast/data clock skew. With
    ``strict=True``, returns ``None`` when no exact (region, sim_timestamp)
    entry exists -- callers that need data-quality signal (gap detection) can
    opt into this mode (WR-09).
    """
    val = intensity_lookup.get((region, sim_timestamp))
    if val is not None:
        return val
    if strict:
        return None
    best_val, best_diff = None, float("inf")
    for (r, ts), v in intensity_lookup.items():
        if r == region:
            d = abs(ts - sim_timestamp)
            if d < best_diff:
                best_diff = d
                best_val = v
    return best_val if best_diff <= 7200 else None


def get_min_region_at(intensity_lookup, regions, sim_timestamp, hw=None):
    """Find the region with minimum carbon at a given timestamp."""
    best_region, best_score = None, float("inf")
    for region in regions:
        val = lookup_intensity(intensity_lookup, region, sim_timestamp)
        if val is None:
            continue
        score = val * hw[region].power_per_core if hw else val
        if score < best_score:
            best_score = score
            best_region = region
    return best_region, best_score


# ---------------------------------------------------------------------------
# Policy classes
# ---------------------------------------------------------------------------

class Policy1(BasePolicy):
    """Initial placement only -- never migrates."""

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
        # No migration after initial placement
        return False, None


class Policy2(BasePolicy):
    """Migrate to the region with minimum intensity this hour."""

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
        use_hw = kwargs.get("use_hw", False)
        min_region, _ = get_min_region_at(
            intensity_lookup, regions, sim_timestamp,
            HW_TABLE if use_hw else None,
        )
        if min_region and min_region != current_region:
            return True, min_region
        return False, None


class Policy3(BasePolicy):
    """Forecast-based: sum intensity over remaining expected_duration, pick lowest total."""

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
        region_totals = {}
        for region in regions:
            total = 0.0
            for h in range(remaining_hours):
                ts = sim_timestamp + h * 3600
                val = lookup_intensity(intensity_lookup, region, ts)
                if val is not None:
                    total += val
            region_totals[region] = total
        if not region_totals:
            return False, None
        optimal = min(region_totals, key=region_totals.get)
        if optimal != current_region:
            return True, optimal
        return False, None


class Policy4(BasePolicy):
    """Forecast-aware adaptive with migration cost threshold."""

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
        forecast_window = kwargs.get("forecast_window", 24)
        cost_multiplier = kwargs.get("cost_multiplier", 3.0)
        migration_seconds = kwargs.get("migration_seconds", 7.0)
        use_hw = kwargs.get("use_hw", False)

        def calculate_carbon(carbon_intensity, hw_usage, core_usage=1, hours=1):
            return carbon_intensity * hw_usage * hours * core_usage

        hw_vals = HW_TABLE

        region_scores = {}
        all_carbon = []
        for region in regions:
            score = 0.0
            for h in range(forecast_window):
                ts = sim_timestamp + h * 3600
                val = lookup_intensity(intensity_lookup, region, ts)
                if val is not None:
                    hour_carbon = calculate_carbon(val, hw_vals[region].power_per_core) if use_hw else val
                    score += hour_carbon
                    all_carbon.append(hour_carbon)
            region_scores[region] = score
        if not region_scores:
            return False, None

        best_region = min(region_scores, key=region_scores.get)
        best_score = region_scores[best_region]
        current_score = region_scores.get(current_region, float("inf"))
        benefit = current_score - best_score

        # Migration cost
        current_intensity = current_score / max(forecast_window, 1)
        target_intensity = best_score / max(forecast_window, 1)
        migration_carbon = (migration_seconds / 3600.0) * max(current_intensity, target_intensity)
        threshold = migration_carbon * cost_multiplier

        if benefit > threshold and best_region != current_region:
            return True, best_region
        return False, None


class Policy5(BasePolicy):
    """Always-best: migrate to best region for the NEXT hour."""

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
        use_hw = kwargs.get("use_hw", False)
        next_ts = sim_timestamp + 3600
        hw = HW_TABLE if use_hw else None
        min_region, min_score = get_min_region_at(intensity_lookup, regions, next_ts, hw)
        current_next = lookup_intensity(intensity_lookup, current_region, next_ts)
        if current_next is None:
            return False, None
        current_score = current_next * HW_TABLE[current_region].power_per_core if use_hw else current_next
        if min_region and min_region != current_region and min_score < current_score:
            return True, min_region
        return False, None
