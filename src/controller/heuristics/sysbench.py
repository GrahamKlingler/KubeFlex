#!/usr/bin/env python3
"""Empirical sysbench-backed performance lookup for KubeFlex (260515-jav).

Loads `data/hardware/sysbench_results.jsonl` (one JSON object per line) and
exposes:

  - ``load_sysbench(path) -> dict[hostname, list[SysbenchPerf]]``
  - ``perf_by_hostname(host, threads=1) -> Optional[float]``
  - ``perf_by_grid(grid, threads=1) -> Optional[float]``
  - ``perf_ratio(src, dst, by_grid=False, threads=1) -> float``

Units: sysbench cpu test ``events_per_second`` (higher is faster). Aggregation
across multiple trials per (hostname, threads) cell uses median.

No-data fallback contract: ``perf_ratio`` returns ``1.0`` (no adjustment) when
EITHER endpoint has no sysbench data, and logs a single warning per
``(src, dst, by_grid)`` triple per process. This lets the simulation work
seamlessly with grids absent from the sysbench census (e.g. BANC, EPE, PACE,
PSCO, TEPC) -- the caller silently falls back to the clock-speed proxy.

Discard rules at load time:
  - ``status != "Succeeded"`` -> drop record
  - ``events_per_second`` is ``None`` -> drop record (defensive)

Data census (260515-jav CONTEXT.md): 460 records total, 198 successful across
48 hostnames and 11 grids (AECI, CISO, DUK, ISNE, MISO, NYIS, PJM, SOCO,
SWPP, TVA, WACM). DUK/ISNE/TVA/WACM have only 1 hostname each so grid
medians for those are single-sample.

Pattern mirrors ``heuristics/hardware.py``: a module-level cached loader keyed
off a CSV/JSONL path, with the canonical data file under ``data/hardware/``.
"""

import functools
import json
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# Default JSONL location: <repo>/data/hardware/sysbench_results.jsonl
# This file lives at <repo>/src/controller/heuristics/sysbench.py, so go up
# four parents to reach the repo root (mirrors hardware.py at line 35).
_DEFAULT_SYSBENCH_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "hardware" / "sysbench_results.jsonl"
)


@dataclass(frozen=True)
class SysbenchPerf:
    """One successful sysbench cpu-test record (single trial)."""

    hostname: str
    grid: str
    events_per_second: float
    threads: int
    model_name: str


# Module-level state for one-shot info log + rate-limited fallback warnings.
_LOAD_LOGGED: bool = False
_FALLBACK_WARNED: Set[Tuple[str, str, bool]] = set()


@functools.lru_cache(maxsize=4)
def load_sysbench(path: str = str(_DEFAULT_SYSBENCH_PATH)) -> Dict[str, List[SysbenchPerf]]:
    """Load `path` as JSONL and return ``{hostname: [SysbenchPerf, ...]}``.

    Discards records with ``status != "Succeeded"`` or ``events_per_second is None``.

    First successful load emits a single info-level summary line. Subsequent
    calls are served from the lru_cache.

    Args:
        path: Filesystem path to the JSONL file. Defaults to the canonical
            ``data/hardware/sysbench_results.jsonl`` under the repo root.

    Returns:
        Mapping of hostname -> list of successful SysbenchPerf records (one per
        trial × threads cell). Hostnames with zero successful records are
        omitted entirely.
    """
    global _LOAD_LOGGED
    result: Dict[str, List[SysbenchPerf]] = {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"[sysbench] data file not found at {p}. "
            f"Expected JSONL with fields: hostname, grid, threads, status, "
            f"events_per_second, model_name."
        )
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # Tolerate stray non-JSON lines; the file is loosely curated.
                continue
            if rec.get("status") != "Succeeded":
                continue
            eps = rec.get("events_per_second")
            if eps is None:
                # Defensive (redundant with status filter, but cheap and safe).
                continue
            perf = SysbenchPerf(
                hostname=rec["hostname"],
                grid=rec.get("grid", ""),
                events_per_second=float(eps),
                threads=int(rec.get("threads", 1)),
                model_name=rec.get("model_name", ""),
            )
            result.setdefault(perf.hostname, []).append(perf)

    if not _LOAD_LOGGED:
        n_records = sum(len(v) for v in result.values())
        n_hosts = len(result)
        grids = {perf.grid for recs in result.values() for perf in recs}
        logger.info(
            "[sysbench] loaded %d records, %d hostnames, %d grids",
            n_records, n_hosts, len(grids),
        )
        _LOAD_LOGGED = True

    return result


def perf_by_hostname(host: str, threads: int = 1) -> Optional[float]:
    """Median events_per_second for ``(host, threads)``.

    Returns None if the hostname is unknown or has no record at this thread
    count.
    """
    table = load_sysbench()
    recs = table.get(host)
    if not recs:
        return None
    matches = [r.events_per_second for r in recs if r.threads == threads]
    if not matches:
        return None
    return float(statistics.median(matches))


def perf_by_grid(grid: str, threads: int = 1) -> Optional[float]:
    """Median events_per_second across all hostnames in ``grid`` at ``threads``.

    Returns None if no successful record exists for this grid (e.g. BANC, EPE,
    PACE, PSCO, TEPC -- grids absent from the sysbench census per CONTEXT.md).
    """
    table = load_sysbench()
    matches: List[float] = []
    for recs in table.values():
        for r in recs:
            if r.grid == grid and r.threads == threads:
                matches.append(r.events_per_second)
    if not matches:
        return None
    return float(statistics.median(matches))


def perf_ratio(src: str, dst: str, by_grid: bool = False, threads: int = 1) -> float:
    """Return ``src_perf / dst_perf`` so a faster destination returns < 1.0.

    Convention matches the clock-speed proxy in ``estimate_remaining_hours``:
    faster destination -> ratio < 1 -> fewer remaining hours.

    If either endpoint has no sysbench data, returns ``1.0`` (no adjustment)
    and logs a single warning per ``(src, dst, by_grid)`` triple per process
    via ``_FALLBACK_WARNED``. This lets callers (Policy 6, the live controller)
    silently fall back to the clock-speed proxy without spamming the log on
    every hourly check.

    Args:
        src: Source key (hostname when by_grid=False, grid identifier when True).
        dst: Destination key (same convention as src).
        by_grid: If True, look up via ``perf_by_grid``; otherwise via
            ``perf_by_hostname``. The sim path uses by_grid=True; the future
            cluster path will use by_grid=False with real hostnames.
        threads: Thread count to filter on. Default 1 (highest success rate
            per CONTEXT.md "Sanity checks").

    Returns:
        Ratio in (0, +inf). 1.0 indicates either equal perf or a no-data
        fallback (distinguish by checking whether ``perf_by_*(src)`` and
        ``perf_by_*(dst)`` both return non-None).
    """
    lookup = perf_by_grid if by_grid else perf_by_hostname
    src_perf = lookup(src, threads)
    dst_perf = lookup(dst, threads)
    if src_perf is None or dst_perf is None:
        key = (src, dst, by_grid)
        if key not in _FALLBACK_WARNED:
            _FALLBACK_WARNED.add(key)
            logger.warning(
                "[sysbench] no perf data for %s=%s, %s=%s (by_grid=%s, threads=%d); "
                "returning ratio=1.0 (caller should fall back to clock-speed proxy)",
                "src" if src_perf is None else "src_ok",
                src,
                "dst" if dst_perf is None else "dst_ok",
                dst,
                by_grid,
                threads,
            )
        return 1.0
    return float(src_perf / dst_perf)
