#!/usr/bin/env python3
"""Static hardware lookup for KubeFlex cluster regions.

Maps each power grid region to its hardware specifications (CPU model,
power consumption, core counts). Values sourced from Nautilus cluster
hardware inventory (hardware.txt).
"""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class HardwareSpec:
    """Immutable hardware specification for a cluster region."""

    name: str
    power_per_core: float  # Watts per core (maps to hw.wattage in heuristic pseudocode)
    available_cores: int  # Total cores in the region's node pool
    tdp_watts: float  # Thermal design power (total node wattage)
    physical_cores: int  # Physical core count per node
    clock_speed_ghz: float  # Base clock speed in GHz


HW_TABLE: Dict[str, HardwareSpec] = {
    "CENT": HardwareSpec(
        name="AMD EPYC 64 Core",
        power_per_core=3.5,
        available_cores=8192,
        tdp_watts=225.0,
        physical_cores=64,
        clock_speed_ghz=2.47,
    ),
    "NE": HardwareSpec(
        name="AMD EPYC 24 Core",
        power_per_core=8.3,
        available_cores=1152,
        tdp_watts=200.0,
        physical_cores=24,
        clock_speed_ghz=4.15,
    ),
    "TEN": HardwareSpec(
        name="Intel(R) Xeon(R) Silver 4215R CPU @ 3.20GHz",
        power_per_core=16.25,
        available_cores=128,
        tdp_watts=130.0,
        physical_cores=8,
        clock_speed_ghz=4.00,
    ),
}


def get_hardware(region: str) -> HardwareSpec:
    """Return the HardwareSpec for *region*.

    Raises:
        KeyError: If *region* is not in HW_TABLE.
    """
    if region not in HW_TABLE:
        valid = sorted(HW_TABLE.keys())
        raise KeyError(
            f"Unknown region '{region}'. Valid regions: {valid}"
        )
    return HW_TABLE[region]
