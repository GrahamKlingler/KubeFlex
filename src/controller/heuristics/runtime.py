#!/usr/bin/env python3
"""Hardware-adjusted runtime estimation for KubeFlex migrations.

Provides estimate_remaining_hours() which adjusts the remaining execution
time of a workload based on hardware capability differences between source
and destination regions. This implements the prog_time_left(program)
equivalent from heuristic.txt, scaled by hardware differences.

Primary scaling factor: clock speed ratio (source / dest).
Fallback: power_per_core ratio when clock speed data is unavailable (0.0).
"""

from heuristics.hardware import HardwareSpec


def estimate_remaining_hours(
    expected_total_minutes: int,
    elapsed_hours: float,
    source_hw: HardwareSpec,
    dest_hw: HardwareSpec,
) -> float:
    """Estimate remaining execution hours after migrating to destination hardware.

    Args:
        expected_total_minutes: Total expected workload duration in minutes
            (as if running entirely on source hardware).
        elapsed_hours: Hours already completed on source hardware.
        source_hw: Hardware specification of the current (source) region.
        dest_hw: Hardware specification of the destination region.

    Returns:
        Estimated remaining hours on destination hardware. A faster
        destination returns fewer hours; a slower one returns more.
    """
    total_hours = expected_total_minutes / 60.0
    remaining_at_source = max(0.0, total_hours - elapsed_hours)

    # Compute scaling factor based on hardware capability ratio
    if source_hw.clock_speed_ghz > 0 and dest_hw.clock_speed_ghz > 0:
        # Faster clock at dest means fewer remaining hours
        scaling = source_hw.clock_speed_ghz / dest_hw.clock_speed_ghz
    elif source_hw.power_per_core > 0 and dest_hw.power_per_core > 0:
        # Fallback: higher power_per_core ~ more capable hardware
        scaling = source_hw.power_per_core / dest_hw.power_per_core
    else:
        scaling = 1.0

    return remaining_at_source * scaling
