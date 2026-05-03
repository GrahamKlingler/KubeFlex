#!/usr/bin/env python3
"""Static hardware lookup for KubeFlex power grids.

Maps each power grid (e.g. ``ISNE``, ``CISO``, ``TVA``) to its hardware
specifications (CPU model, power consumption, core counts). Values are
loaded from ``data/hardware/hw_avg.csv`` at module import time; the CSV
is the single source of truth.

The ``grid`` key matches the trailing segment of the grid CSV filenames
under ``data/regions/{REGION}/US-{REGION}-{GRID}.csv`` (e.g. file stem
``US-NE-ISNE`` -> grid ``ISNE``).
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(frozen=True)
class HardwareSpec:
    """Immutable hardware specification for a power grid."""

    name: str
    power_per_core: float  # Watts per core (maps to hw.wattage in heuristic pseudocode)
    available_cores: int  # Total cores in the grid's node pool
    tdp_watts: float  # Thermal design power (total node wattage)
    physical_cores: int  # Physical core count per node
    clock_speed_ghz: float  # Base clock speed in GHz


# Default CSV location: <repo>/data/hardware/hw_avg.csv
# This file lives at <repo>/src/controller/heuristics/hardware.py, so go up
# four parents to reach the repo root.
_DEFAULT_HW_CSV = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "hardware" / "hw_avg.csv"
)


def load_hw_table_from_csv(path: Path) -> Dict[str, HardwareSpec]:
    """Load a grid-keyed HardwareSpec table from a CSV file.

    Expected CSV columns (header row required):
        grid, region, name, power_per_core, available_cores, tdp_watts,
        physical_cores, clock_speed_ghz

    The ``grid`` column is the canonical join key (e.g. ``ISNE``, ``CISO``).
    The ``region`` column is metadata only and not used for keying.

    Args:
        path: Filesystem path to ``hw_avg.csv``.

    Returns:
        Dict mapping grid identifier -> HardwareSpec.

    Raises:
        FileNotFoundError: If *path* does not exist.
        KeyError: If a required column is missing in the CSV header
            (re-raised from the row-level access).
    """
    if not Path(path).exists():
        raise FileNotFoundError(
            f"[HW] hardware CSV not found at {path}. "
            f"Expected schema: grid, region, name, power_per_core, "
            f"available_cores, tdp_watts, physical_cores, clock_speed_ghz."
        )
    table: Dict[str, HardwareSpec] = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            grid = row["grid"]  # KeyError surfaces missing column with row context
            table[grid] = HardwareSpec(
                name=row["name"],
                power_per_core=float(row["power_per_core"]),
                available_cores=int(float(row["available_cores"])),
                tdp_watts=float(row["tdp_watts"]),
                # physical_cores is sometimes a fractional average across boxes;
                # round to nearest int but tolerate float-shaped strings like "20.43".
                physical_cores=int(round(float(row["physical_cores"]))),
                clock_speed_ghz=float(row["clock_speed_ghz"]),
            )
    return table


# Module-level table — populated from CSV at import time. Source of truth.
HW_TABLE: Dict[str, HardwareSpec] = load_hw_table_from_csv(_DEFAULT_HW_CSV)


def get_hardware(grid: str) -> HardwareSpec:
    """Return the HardwareSpec for *grid*.

    Raises:
        KeyError: If *grid* is not in HW_TABLE.
    """
    if grid not in HW_TABLE:
        valid = sorted(HW_TABLE.keys())
        raise KeyError(
            f"Unknown grid '{grid}'. Valid grids: {valid}"
        )
    return HW_TABLE[grid]
