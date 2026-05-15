#!/usr/bin/env python3
"""Hardware-adjusted runtime estimation for KubeFlex migrations.

Two sibling estimators:

  - ``estimate_remaining_hours``: clock-speed proxy. Faster destination ->
    fewer remaining hours via ``source_hw.clock_speed_ghz /
    dest_hw.clock_speed_ghz``. Fallback to ``power_per_core`` ratio when clock
    speed is missing (0.0).
  - ``estimate_remaining_hours_empirical`` (260515-jav): sysbench-backed
    empirical sibling. Uses measured ``events_per_second`` from
    ``data/hardware/sysbench_results.jsonl`` via ``heuristics.sysbench``.
    Falls back silently to the clock-speed proxy when either endpoint is
    absent from the sysbench census (e.g. BANC, EPE, PACE, PSCO, TEPC).

Both functions preserve the convention: faster dest -> ratio < 1 -> fewer
remaining hours.
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


def estimate_remaining_hours_empirical(
    expected_total_minutes: int,
    elapsed_hours: float,
    source_hw: HardwareSpec,
    dest_hw: HardwareSpec,
    source_key: str,
    dest_key: str,
    by_grid: bool = False,
) -> float:
    """Empirical sibling of ``estimate_remaining_hours`` (260515-jav).

    Uses sysbench ``events_per_second`` data (via ``heuristics.sysbench``)
    instead of clock speed. Returns
    ``max(0, total - elapsed_hours) * (src_perf / dst_perf)`` so a faster
    destination returns fewer hours, matching the clock-speed convention.

    Falls back to ``estimate_remaining_hours`` (the clock-speed proxy) when
    either endpoint has no sysbench record. This makes the function safe to
    call with any (grid, grid) or (host, host) pair: grids absent from the
    sysbench census silently use the existing proxy.

    Args:
        expected_total_minutes: Total expected workload duration in minutes
            (as if running entirely on source hardware).
        elapsed_hours: Hours already completed on source hardware.
        source_hw: HardwareSpec of the source. Used by the clock-speed
            fallback only; the empirical path keys off ``source_key``.
        dest_hw: HardwareSpec of the destination. Same role as source_hw.
        source_key: Hostname (cluster path) or grid identifier (sim path).
        dest_key: Hostname or grid identifier (same convention as source_key).
        by_grid: True when source_key/dest_key are grid identifiers (sim
            path); False when they are hostnames (cluster path).

    Returns:
        Estimated remaining hours on destination. Identical to
        ``estimate_remaining_hours(...)`` when either endpoint is missing
        sysbench data.
    """
    # Local import keeps the runtime module self-contained (heuristics.sysbench
    # is only loaded when the empirical path is exercised).
    from heuristics.sysbench import perf_by_grid, perf_by_hostname, perf_ratio

    lookup = perf_by_grid if by_grid else perf_by_hostname
    src_perf = lookup(source_key, 1)
    dst_perf = lookup(dest_key, 1)
    if src_perf is None or dst_perf is None:
        # Silent fallback: distinguishes "no data" from "identical perf".
        # perf_ratio itself returns 1.0 in this case and rate-limits the
        # warning. Delegating here matches the documented contract.
        return estimate_remaining_hours(
            expected_total_minutes, elapsed_hours, source_hw, dest_hw,
        )

    ratio = perf_ratio(source_key, dest_key, by_grid=by_grid)
    total_hours = expected_total_minutes / 60.0
    remaining_at_source = max(0.0, total_hours - elapsed_hours)
    return remaining_at_source * ratio
