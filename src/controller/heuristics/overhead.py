#!/usr/bin/env python3
"""Linear-fit overhead estimation for KubeFlex live migration.

Provides calibrated functions for checkpoint, transfer (send), and restore
overhead as linear functions of application size in megabytes. Coefficients
are derived from Phase 2 empirical data (summary_stats.csv) using a 3-point
linear fit across three representative workloads.

Calibration source:
    data/overhead-benchmark/run_20260420_030700/summary_stats.csv

Known limitation (D-05):
    The linear fit is based on only 3 workload data points:
        sysbench_cpu  ~ 10 MB
        sysbench_memory ~ 64 MB
        memcount      ~ 256 MB
    This is a prototype-quality fit sufficient for thesis simulation; a
    production model would require a broader workload sweep.

App size assignments used during calibration:
    sysbench_cpu    = 10 MB   (minimal CPU workload, small checkpoint)
    sysbench_memory = 64 MB   (memory-intensive workload)
    memcount        = 256 MB  (large memory footprint workload)

Hardware scaling baseline:
    TEN region (Intel Xeon @ 4.00 GHz) is the empirical reference node
    where all Phase 2 benchmarks were collected. REFERENCE_CLOCK_GHZ = 4.00.
"""

from heuristics.hardware import HardwareSpec

# ---------------------------------------------------------------------------
# Checkpoint linear-fit coefficients
# ---------------------------------------------------------------------------
CKPT_SLOPE_S_PER_MB: float = 0.001635      # seconds per MB
CKPT_INTERCEPT_S: float = 0.7561           # baseline seconds
CKPT_R2: float = 0.97                      # fit quality (coefficient of determination)

# ---------------------------------------------------------------------------
# Transfer (network send) linear-fit coefficients
# ---------------------------------------------------------------------------
TRANSFER_SLOPE_S_PER_MB: float = 0.008085  # seconds per MB
TRANSFER_INTERCEPT_S: float = 0.5341       # baseline seconds
TRANSFER_R2: float = 0.99                  # fit quality

# ---------------------------------------------------------------------------
# Restore linear-fit coefficients
# ---------------------------------------------------------------------------
RESTORE_SLOPE_S_PER_MB: float = 0.001681   # seconds per MB
RESTORE_INTERCEPT_S: float = 0.4560        # baseline seconds
RESTORE_R2: float = 0.88                   # fit quality

# ---------------------------------------------------------------------------
# Hardware and network constants
# ---------------------------------------------------------------------------
NETWORK_POWER_WATTS: float = 15.0          # Default network power (D-09)
REFERENCE_CLOCK_GHZ: float = 4.00          # TEN clock_speed_ghz — empirical baseline


def _hw_scaling(hw: HardwareSpec, reference_clock_ghz: float = REFERENCE_CLOCK_GHZ) -> float:
    """Compute hardware scaling factor relative to the reference clock speed.

    Values greater than 1.0 indicate the hardware is slower than the reference
    (TEN region, Intel Xeon @ 4.00 GHz); values less than 1.0 indicate faster
    hardware. This matches D-04: scale baseline overhead estimates by hardware
    capability ratio.

    Args:
        hw: Hardware specification of the node being evaluated.
        reference_clock_ghz: Reference clock speed in GHz. Defaults to
            REFERENCE_CLOCK_GHZ (4.00 GHz, TEN region empirical baseline).

    Returns:
        Scaling factor (reference_clock_ghz / hw.clock_speed_ghz). Returns
        1.0 if hw.clock_speed_ghz is zero to avoid division by zero.
    """
    if hw.clock_speed_ghz > 0:
        return reference_clock_ghz / hw.clock_speed_ghz
    return 1.0


def ckpt_overhead(app_size_mb: float, src_hw: HardwareSpec) -> float:
    """Estimate checkpoint overhead in seconds.

    Uses the linear model calibrated from Phase 2 empirical means, scaled by
    source hardware capability relative to the TEN reference node. Faster
    source hardware produces a shorter checkpoint (scaling < 1.0).

    Args:
        app_size_mb: Application checkpoint size in megabytes.
        src_hw: Hardware specification of the source (current) region.

    Returns:
        Estimated checkpoint duration in seconds.
    """
    base_s = CKPT_SLOPE_S_PER_MB * app_size_mb + CKPT_INTERCEPT_S
    return base_s * _hw_scaling(src_hw)


def send_overhead(src_hw: HardwareSpec, dst_hw: HardwareSpec, app_size_mb: float) -> float:
    """Estimate checkpoint transfer (network send) overhead in seconds.

    Transfer time is network-bound and does not scale with CPU hardware speed.
    The function signature accepts src_hw and dst_hw to match heuristic.txt
    (send_overhead(src, dest, app_size)), but neither hardware spec affects
    the computation — only app_size_mb matters.

    Args:
        src_hw: Hardware specification of the source region (unused in
            computation; included for interface consistency with heuristic.txt).
        dst_hw: Hardware specification of the destination region (unused in
            computation; included for interface consistency with heuristic.txt).
        app_size_mb: Application checkpoint size in megabytes.

    Returns:
        Estimated transfer duration in seconds.
    """
    return TRANSFER_SLOPE_S_PER_MB * app_size_mb + TRANSFER_INTERCEPT_S


def restore_overhead(app_size_mb: float, dst_hw: HardwareSpec) -> float:
    """Estimate restore overhead in seconds.

    Uses the linear model calibrated from Phase 2 empirical means, scaled by
    destination hardware capability relative to the TEN reference node. Faster
    destination hardware produces a shorter restore (scaling < 1.0).

    Args:
        app_size_mb: Application checkpoint size in megabytes.
        dst_hw: Hardware specification of the destination (target) region.

    Returns:
        Estimated restore duration in seconds.
    """
    base_s = RESTORE_SLOPE_S_PER_MB * app_size_mb + RESTORE_INTERCEPT_S
    return base_s * _hw_scaling(dst_hw)


def total_migration_time_s(
    app_size_mb: float, src_hw: HardwareSpec, dst_hw: HardwareSpec
) -> float:
    """Estimate total migration time in seconds.

    Sum of checkpoint, transfer, and restore overhead.

    Args:
        app_size_mb: Application checkpoint size in megabytes.
        src_hw: Hardware specification of the source region.
        dst_hw: Hardware specification of the destination region.

    Returns:
        Total estimated migration duration in seconds.
    """
    return (
        ckpt_overhead(app_size_mb, src_hw)
        + send_overhead(src_hw, dst_hw, app_size_mb)
        + restore_overhead(app_size_mb, dst_hw)
    )


def total_migration_time_h(
    app_size_mb: float, src_hw: HardwareSpec, dst_hw: HardwareSpec
) -> float:
    """Estimate total migration time in hours.

    Convenience wrapper converting total_migration_time_s() to hours for
    direct use in the hourly simulation loop.

    Args:
        app_size_mb: Application checkpoint size in megabytes.
        src_hw: Hardware specification of the source region.
        dst_hw: Hardware specification of the destination region.

    Returns:
        Total estimated migration duration in hours.
    """
    return total_migration_time_s(app_size_mb, src_hw, dst_hw) / 3600.0
