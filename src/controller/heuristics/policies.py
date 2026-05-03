#!/usr/bin/env python3
"""Policy classes for KubeFlex carbon scheduling (Policies 1-5).

Extracted from run_carbon_migration_test.simulate_policy_decision() and wrapped
in the BasePolicy ABC interface. Each policy implements decide() with logic
identical to the original if-elif branches in the simulation harness.

Helper functions lookup_intensity() and get_min_grid_at() are also exported
for use by HeuristicPolicy (Policy 6) and the simulation harness dispatcher.

Join-key naming: the expected-simulation path keys all intensity / hardware
lookups by GRID (e.g. ``ISNE``, ``CISO``, ``TVA``). The cluster-execution
path still keys by REGION; this divergence is intentional (see quick task
260502-i16).
"""

from typing import Dict, List, Optional, Tuple

from heuristics.base import BasePolicy
from heuristics.hardware import HW_TABLE, get_hardware


# ---------------------------------------------------------------------------
# Shared helper functions (originally in run_carbon_migration_test.py)
# ---------------------------------------------------------------------------

def lookup_intensity(intensity_lookup, grid, sim_timestamp, strict=False):
    """Look up intensity for a grid at a given timestamp, with fuzzy matching.

    With ``strict=False`` (default), falls back to the nearest timestamp within
    a 2 h (7200 s) tolerance to tolerate minor forecast/data clock skew. With
    ``strict=True``, returns ``None`` when no exact (grid, sim_timestamp)
    entry exists -- callers that need data-quality signal (gap detection) can
    opt into this mode (WR-09).
    """
    val = intensity_lookup.get((grid, sim_timestamp))
    if val is not None:
        return val
    if strict:
        return None
    best_val, best_diff = None, float("inf")
    for (g, ts), v in intensity_lookup.items():
        if g == grid:
            d = abs(ts - sim_timestamp)
            if d < best_diff:
                best_diff = d
                best_val = v
    return best_val if best_diff <= 7200 else None


def get_min_grid_at(intensity_lookup, grids, sim_timestamp, hw=None):
    """Find the grid with minimum carbon at a given timestamp."""
    best_grid, best_score = None, float("inf")
    for grid in grids:
        val = lookup_intensity(intensity_lookup, grid, sim_timestamp)
        if val is None:
            continue
        score = val * hw[grid].power_per_core if hw else val
        if score < best_score:
            best_score = score
            best_grid = grid
    return best_grid, best_score


# ---------------------------------------------------------------------------
# Policy classes
# ---------------------------------------------------------------------------

class Policy1(BasePolicy):
    """Initial placement only -- never migrates."""

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
        # No migration after initial placement
        return False, None


class Policy2(BasePolicy):
    """Migrate to the grid with minimum intensity this hour."""

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
        use_hw = kwargs.get("use_hw", False)
        min_grid, _ = get_min_grid_at(
            intensity_lookup, grids, sim_timestamp,
            HW_TABLE if use_hw else None,
        )
        if min_grid and min_grid != current_grid:
            return True, min_grid
        return False, None


class Policy3(BasePolicy):
    """Forecast-based: sum intensity over remaining expected_duration, pick lowest total."""

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
        grid_totals = {}
        for grid in grids:
            total = 0.0
            for h in range(remaining_hours):
                ts = sim_timestamp + h * 3600
                val = lookup_intensity(intensity_lookup, grid, ts)
                if val is not None:
                    total += val
            grid_totals[grid] = total
        if not grid_totals:
            return False, None
        optimal = min(grid_totals, key=grid_totals.get)
        if optimal != current_grid:
            return True, optimal
        return False, None


class Policy4(BasePolicy):
    """Forecast-aware adaptive with migration cost threshold."""

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
        forecast_window = kwargs.get("forecast_window", 24)
        cost_multiplier = kwargs.get("cost_multiplier", 3.0)
        migration_seconds = kwargs.get("migration_seconds", 7.0)
        use_hw = kwargs.get("use_hw", False)

        def calculate_carbon(carbon_intensity, hw_usage, core_usage=1, hours=1):
            return carbon_intensity * hw_usage * hours * core_usage

        hw_vals = HW_TABLE

        grid_scores = {}
        all_carbon = []
        for grid in grids:
            score = 0.0
            for h in range(forecast_window):
                ts = sim_timestamp + h * 3600
                val = lookup_intensity(intensity_lookup, grid, ts)
                if val is not None:
                    hour_carbon = calculate_carbon(val, hw_vals[grid].power_per_core) if use_hw else val
                    score += hour_carbon
                    all_carbon.append(hour_carbon)
            grid_scores[grid] = score
        if not grid_scores:
            return False, None

        best_grid = min(grid_scores, key=grid_scores.get)
        best_score = grid_scores[best_grid]
        current_score = grid_scores.get(current_grid, float("inf"))
        benefit = current_score - best_score

        # Migration cost
        current_intensity = current_score / max(forecast_window, 1)
        target_intensity = best_score / max(forecast_window, 1)
        migration_carbon = (migration_seconds / 3600.0) * max(current_intensity, target_intensity)
        threshold = migration_carbon * cost_multiplier

        if benefit > threshold and best_grid != current_grid:
            return True, best_grid
        return False, None


class Policy5(BasePolicy):
    """Always-best: migrate to best grid for the NEXT hour."""

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
        use_hw = kwargs.get("use_hw", False)
        next_ts = sim_timestamp + 3600
        hw = HW_TABLE if use_hw else None
        min_grid, min_score = get_min_grid_at(intensity_lookup, grids, next_ts, hw)
        current_next = lookup_intensity(intensity_lookup, current_grid, next_ts)
        if current_next is None:
            return False, None
        current_score = current_next * HW_TABLE[current_grid].power_per_core if use_hw else current_next
        if min_grid and min_grid != current_grid and min_score < current_score:
            return True, min_grid
        return False, None
