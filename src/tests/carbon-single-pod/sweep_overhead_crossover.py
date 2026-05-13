#!/usr/bin/env python3
"""Multi-policy overhead-crossover sweep (quick task 260511-kqo, extends 260511-k7l/jce).

This is a one-shot orchestrator with two modes:

  --mode pairwise (default)
    Sweep one or more directional ``--pairs SRC:DST`` (default: BANC:CISO and
    CISO:BANC) across the policy list. Policy 6 sees exactly the two pair grids
    as destination candidates.

  --mode all-grids (new in 260511-kqo)
    For each start_ts, pick ``source_grid = argmin over HW_POOL_GRIDS of
    lookup_intensity(g, start_ts)`` (HW-scaled iff use_hw). The destination
    candidate pool is the full 26-grid HW set. One source per timestamp,
    shared across policies and overhead values per locked CONTEXT.md decision.

Both modes support arbitrary policy subsets via ``--policies``. The default
output directories differ by mode (Sweep A vs Sweep B locked paths under
``data/quick/260511-kqo-*/``); pass ``--out-dir`` to override.

Reference: ``.planning/quick/260511-k7l-add-policy-5-to-banc-ciso-overhead-cross/260511-k7l-PLAN.md``
and ``.planning/quick/260511-jce-extend-policy-2-vs-policy-6-overhead-swe/260511-jce-CONTEXT.md``.

The sweep is a single linked knob: for each candidate overhead value
``m`` (minutes) in the grid [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240,
360], we
  (a) set ``RunConfig.expected_migration_min = m`` so the *actual* simulated
      migration cost (now minute-granular per 260511-jce) scales with the
      swept knob, and
  (b) wrap the run in a ``scaled_overhead(m)`` context manager that
      monkey-patches ``heuristics.policy_heuristic.{ckpt_overhead,
      send_overhead, restore_overhead}`` (the *bound* symbols inside Policy 6,
      not the source module) so that Policy 6's stay-vs-migrate estimate
      *also* scales linearly with the swept knob.

The ``scaled_overhead`` patch is a no-op for Policy 2 and Policy 5 because
neither imports the overhead helpers; they still feel overhead via
``cfg.expected_migration_min`` which the sim core's minute-granular charge
applies uniformly across all policies.

CRITICAL: ``src/controller/heuristics/policy_heuristic.py`` line 29 does
    from heuristics.overhead import (ckpt_overhead, send_overhead,
                                     restore_overhead, NETWORK_POWER_WATTS)
which binds the symbols into the ``heuristics.policy_heuristic`` module
namespace at import time. Monkey-patching ``heuristics.overhead.ckpt_overhead``
has NO EFFECT on Policy 6's behavior because Policy 6 has already resolved
its own bound reference. The patch must target
``heuristics.policy_heuristic.{ckpt_overhead, send_overhead, restore_overhead}``.

This script does NOT modify ``_simulation_core.py``, ``evaluate_policies.py``,
``policy_heuristic.py``, ``overhead.py``, or ``evaluation_plots.py``. It only
imports them and patches the Policy 6 bindings inside a context manager that
restores the originals on exit. The sim core and ``scaled_overhead`` patch are
unchanged from 260511-jce; only the policy list and downstream aggregation /
plot / summary code are generalized to handle arbitrary policy subsets.

Default output directories (changed in 260511-kqo):
  - Sweep A (mode=pairwise): ``data/quick/260511-kqo-all-policies-6-pairs/``
  - Sweep B (mode=all-grids): ``data/quick/260511-kqo-all-policies-all-hw-grids/``

Sweep A artifacts (mode=pairwise):
  - ``curves.csv``           -- long-format per-run results (one row per
                                (overhead, direction, policy, start_ts)).
  - ``curves.png``           -- 6 rows x 2 columns subplot grid (rows=unordered
                                pair index, cols=direction A->B and B->A) when
                                >2 pairs; otherwise the legacy 1-row layout.
  - ``crossover_summary.md`` -- per-direction pairwise crossover analysis with
                                a "no crossover" group counter to keep the file
                                readable when len(policies) is large.

Sweep B artifacts (mode=all-grids):
  - ``curves.csv``           -- per-run rows: overhead_min, start_ts,
                                source_grid_chosen, policy, total_carbon,
                                migration_count, dest_grids_visited (|-sep).
  - ``aggregates.csv``       -- per-(overhead, policy) means/stds across start_ts.
  - ``curves.png``           -- single panel, 6 policy curves over the
                                overhead grid (means).
  - ``crossover_summary.md`` -- pairwise crossovers on aggregated curves,
                                per-overhead aggregate table, plus
                                "Destination diversity" and "Source diversity"
                                sections specific to Sweep B.
"""

import argparse
import csv
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

import matplotlib
matplotlib.use("Agg")  # headless-safe; must come before pyplot import
import matplotlib.pyplot as plt  # noqa: E402

# Project import shim (mirror evaluate_policies.py lines 57-59 so we can import
# the same controller-package modules without installing them).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _simulation_core import RunConfig, simulate_one_run  # noqa: E402
from evaluate_policies import (  # noqa: E402
    DEFAULT_REGIONS_TREE_DIR,
    discover_grids,
    build_intensity_lookup_from_regions_tree,
    _main_sweep_timestamps,
)
from heuristics.hardware import HW_TABLE  # noqa: E402
from heuristics.policies import lookup_intensity  # noqa: E402
from evaluation_plots import POLICY_COLORS  # noqa: E402

# Module references whose *bound* symbols we will patch / read.
from heuristics import policy_heuristic as ph  # noqa: E402
from heuristics import overhead as oh_mod  # noqa: E402


# ── Constants (LOCKED by CONTEXT.md / k7l PLAN) ──────────────────────

# 13-value grid up to 360 min (260511-jce locked). Denser at the low end where
# crossovers are likely; coarser past 60 min where multi-hour overhead regimes
# only matter qualitatively.
OVERHEAD_GRID_MIN = (0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360)
# Default policy list for the three-policy crossover sweep (260511-k7l).
# Order is preserved for plot/CSV/summary ordering — users can pass
# --policies to swap or reorder.
POLICIES_DEFAULT = (2, 5, 6)
# Friendly names for each policy id (used in plot legends and summaries).
POLICY_NAMES = {
    1: "no-migration",
    2: "always-best",
    3: "forecast-sum",
    4: "adaptive",
    5: "always-best-1h",
    6: "heuristic",
}
VALID_POLICY_IDS = frozenset(POLICY_NAMES.keys())
# Repo-data root (data/quick/...).
_DATA_QUICK = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "quick"
)
# Locked output dirs per CONTEXT.md / PLAN.md for 260511-kqo.
SWEEP_A_OUT_DIR = _DATA_QUICK / "260511-kqo-all-policies-6-pairs"
SWEEP_B_OUT_DIR = _DATA_QUICK / "260511-kqo-all-policies-all-hw-grids"
# Legacy default retained for back-compat with 260511-k7l callers; new
# top-level main() selects SWEEP_A_OUT_DIR or SWEEP_B_OUT_DIR by --mode.
OUT_DIR = SWEEP_A_OUT_DIR
# BANC and CISO are both CAL-region grids with competitive carbon intensities;
# the directional pairs let us answer the crossover question in both
# directions on a single sweep run.
DIRECTIONAL_PAIRS = (("BANC", "CISO"), ("CISO", "BANC"))  # LOCKED
ANCHOR_APP_SIZE_MB = 64.0  # canonical app size used for the baseline anchor

# 26-grid HW set, from data/hardware/hw_avg.csv. Used as Sweep B's source pool
# (argmin per ts) AND destination candidate pool. CONTEXT.md locked.
HW_POOL_GRIDS = (
    "AECI", "AZPS", "BANC", "CISO", "DUK", "EPE", "ERCO", "IPCO", "ISNE", "JEA",
    "LDWP", "MISO", "NEVP", "NWMT", "NYIS", "PACE", "PGE", "PJM", "PNM", "PSCO",
    "SCL", "SOCO", "SWPP", "TEPC", "TVA", "WACM",
)


# ── Linked-knob: overhead estimate patch (load-bearing) ──────────────

class scaled_overhead:
    """Context manager that scales Policy 6's bound overhead helpers.

    The factor is ``target_total_minutes / baseline_total_min``, where
    ``baseline_total_min`` is the sum of the original linear-fit
    ``ckpt_overhead`` + ``send_overhead`` + ``restore_overhead`` at the canonical
    app size (64 MB) using the anchor grid's hardware as both src and dst.

    Why patch ``heuristics.policy_heuristic`` and NOT ``heuristics.overhead``:
        ``policy_heuristic.py`` does ``from heuristics.overhead import
        (ckpt_overhead, send_overhead, restore_overhead, ...)`` which binds
        the symbols into its own namespace at import time. Mutating
        ``heuristics.overhead.ckpt_overhead`` afterwards has no effect on
        Policy 6 -- it has already resolved its own reference.

    The ``__exit__`` restores originals via ``try/finally``-style guarantee so
    Policy 6 is left unchanged for non-sweep callers, even if a run raises.
    """

    def __init__(self, target_total_minutes: float, anchor_grid: str):
        self.target_total_minutes = float(target_total_minutes)
        self.anchor_grid = anchor_grid
        # Pre-compute scale factor up-front so __enter__ is cheap.
        anchor_hw = HW_TABLE[anchor_grid]
        # Use the ORIGINAL (unpatched) helpers from heuristics.overhead.
        # Whatever is currently bound on ph might be a previous patch wrapper
        # if __enter__ is called twice without exit; we always read from oh_mod
        # to compute the baseline.
        baseline_s = (
            oh_mod.ckpt_overhead(ANCHOR_APP_SIZE_MB, anchor_hw)
            + oh_mod.send_overhead(anchor_hw, anchor_hw, ANCHOR_APP_SIZE_MB)
            + oh_mod.restore_overhead(ANCHOR_APP_SIZE_MB, anchor_hw)
        )
        self.baseline_total_min = baseline_s / 60.0
        if self.baseline_total_min <= 0.0:
            # Guard divide-by-zero; treat as scale=0 so Policy 6's estimate
            # collapses to zero (which is what the user asked for).
            self.scale = 0.0
        else:
            self.scale = self.target_total_minutes / self.baseline_total_min
        self._orig = None  # populated on __enter__

    def __enter__(self):
        # Capture the currently-bound originals on policy_heuristic. These
        # should be identical to the heuristics.overhead helpers under normal
        # circumstances (we never leave a stale patch behind).
        self._orig = (ph.ckpt_overhead, ph.send_overhead, ph.restore_overhead)
        scale = self.scale
        o_ckpt, o_send, o_rest = self._orig
        # Wrappers preserve the original call signatures (see overhead.py:
        # ckpt_overhead(app, src_hw), send_overhead(src_hw, dst_hw, app),
        # restore_overhead(app, dst_hw)).
        ph.ckpt_overhead = (
            lambda app, src_hw, _o=o_ckpt, _s=scale: _o(app, src_hw) * _s
        )
        ph.send_overhead = (
            lambda src_hw, dst_hw, app, _o=o_send, _s=scale: _o(
                src_hw, dst_hw, app
            ) * _s
        )
        ph.restore_overhead = (
            lambda app, dst_hw, _o=o_rest, _s=scale: _o(app, dst_hw) * _s
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        # Restore originals unconditionally so non-sweep callers see the
        # untouched module.
        if self._orig is not None:
            ph.ckpt_overhead, ph.send_overhead, ph.restore_overhead = self._orig
            self._orig = None
        # Returning False (default) propagates any exception.
        return False


# ── Sweep core ────────────────────────────────────────────────────────

def _pick_anchor_grid(usable_grids, preferred=("BANC", "CISO", "ISNE")):
    """Return the grid to use as the linked-knob baseline anchor.

    Prefer BANC/CISO (the 260511-jce directional-pair endpoints); fall back to
    ISNE for backward compat with 260511-gnm callers; otherwise the first
    usable grid (alphabetical order).
    """
    for g in preferred:
        if g in usable_grids:
            return g
    return usable_grids[0]


def _pick_source_grids(usable_grids, override):
    """Resolve --source-grids CLI override or default to a single NE source.

    Kept for backward compatibility with 260511-gnm callers; the 260511-jce
    default sweep uses :func:`_resolve_directional_pairs` instead.
    """
    if override:
        bad = [g for g in override if g not in usable_grids]
        if bad:
            raise SystemExit(
                f"[SWEEP] requested --source-grids {bad} not in usable set "
                f"{usable_grids}"
            )
        return list(override)
    if "ISNE" in usable_grids:
        return ["ISNE"]
    return [usable_grids[0]]


def _resolve_directional_pairs(usable_grids, override_pairs):
    """Return list of (source_grid, dest_grid) pairs to sweep.

    Default: BANC<->CISO bidirectional. CLI ``--pairs`` can override with a list
    of ``SRC:DST`` tokens.
    """
    if override_pairs is None:
        pairs = list(DIRECTIONAL_PAIRS)
    else:
        pairs = []
        for tok in override_pairs:
            try:
                s, d = tok.split(":")
            except ValueError:
                raise SystemExit(
                    f"[SWEEP] bad --pairs token {tok!r}; expected SRC:DST"
                )
            pairs.append((s, d))
    bad = [(s, d) for s, d in pairs
           if s not in usable_grids or d not in usable_grids]
    if bad:
        raise SystemExit(
            f"[SWEEP] requested directional pairs {bad} not in usable set "
            f"{usable_grids}"
        )
    return pairs


def _resolve_policies(override_csv):
    """Parse ``--policies`` CSV (e.g. ``"2,5,6"``) into an ordered tuple of ints.

    Default: :data:`POLICIES_DEFAULT`. Rejects duplicates (so the same policy
    can't be plotted twice) and unknown policy ids (must be in 1..6).
    The order the user typed is preserved.
    """
    if override_csv is None:
        return tuple(POLICIES_DEFAULT)
    raw = [tok.strip() for tok in override_csv.split(",") if tok.strip()]
    if not raw:
        raise SystemExit(
            f"[SWEEP] --policies must be a non-empty comma-separated list "
            f"(got {override_csv!r})"
        )
    try:
        parsed = tuple(int(tok) for tok in raw)
    except ValueError:
        raise SystemExit(
            f"[SWEEP] --policies tokens must all be integers (got {raw!r})"
        )
    bad = [p for p in parsed if p not in VALID_POLICY_IDS]
    if bad:
        raise SystemExit(
            f"[SWEEP] --policies contains unknown ids {bad}; "
            f"valid ids are {sorted(VALID_POLICY_IDS)}"
        )
    if len(set(parsed)) != len(parsed):
        raise SystemExit(
            f"[SWEEP] --policies contains duplicates ({parsed}); "
            f"each policy may appear at most once"
        )
    return parsed


def _build_two_grid_lookup(full_lookup, src_grid, dst_grid):
    """Subset ``full_lookup`` to ``(src_grid, ts)`` and ``(dst_grid, ts)`` entries only.

    ``simulate_one_run`` infers available grids from the lookup keys
    (``sorted(set(g for g, _ts in lookup.keys()))`` in _simulation_core.py
    line 174), so restricting the lookup to two grids is how we constrain
    Policy 6's destination search to a single candidate per direction.
    """
    return {
        (g, ts): v for (g, ts), v in full_lookup.items()
        if g in (src_grid, dst_grid)
    }


def _build_filtered_lookup(full_lookup, grids):
    """Subset ``full_lookup`` to entries for any grid in ``grids``.

    Generalization of :func:`_build_two_grid_lookup` for arbitrary destination
    pools. Used by Sweep B (all-grids mode) so all policies see the same
    26-grid candidate pool.
    """
    grid_set = set(grids)
    return {
        (g, ts): v for (g, ts), v in full_lookup.items() if g in grid_set
    }


def _pick_dynamic_source(intensity_lookup, hw_grids, start_ts, use_hw):
    """Return HW-pool grid with lowest intensity at ``start_ts``.

    Mirrors the Policy 2 / Policy 5 ``get_min_grid_at`` HW-scaling logic so
    Sweep B's source choice uses the same metric the policies themselves use.

    Args:
        intensity_lookup: ``{(grid, ts): intensity}``.
        hw_grids: iterable of candidate grids (the HW pool).
        start_ts: target timestamp.
        use_hw: whether to scale by ``HW_TABLE[grid].power_per_core``.

    Returns:
        The grid name with the minimum score. Skips grids that have no value
        at ``start_ts``ng OR whose value is exactly 0.0 (treated as missing data
        per Rule 2 — SCL has 0.0 across the full dataset, which would make it
        the argmin every timestamp and degenerate Sweep B to a single-source
        zero-carbon run; no real US grid has truly 0 carbon intensity).

    Raises:
        RuntimeError: If NO grid in ``hw_grids`` has a usable value at ``start_ts``.
    """
    best_grid = None
    best_score = float("inf")
    for g in hw_grids:
        v = lookup_intensity(intensity_lookup, g, start_ts)
        if v is None or v <= 0.0:
            continue
        score = v * HW_TABLE[g].power_per_core if use_hw else v
        if score < best_score:
            best_score = score
            best_grid = g
    if best_grid is None:
        raise RuntimeError(
            f"[SWEEP] _pick_dynamic_source: no grid in {list(hw_grids)} has "
            f"a usable (nonzero) value at start_ts={start_ts}"
        )
    return best_grid


def _resolve_timestamps(all_ts, num):
    """Sub-sample ``all_ts`` to roughly ``num`` evenly-spaced timestamps."""
    if num <= 0:
        raise SystemExit("[SWEEP] --num-timestamps must be >= 1")
    if num >= len(all_ts):
        return list(all_ts)
    step = max(1, len(all_ts) // num)
    return list(all_ts[::step])[:num]


def run_sweep(full_lookup, directional_pairs, timestamps, anchor_grid, policies):
    """Execute the 13 x len(directional_pairs) x len(policies) x len(timestamps) cell sweep.

    For each directional ``(src, dst)`` pair we build a two-grid lookup so
    Policy 6 sees exactly one candidate destination (the directional partner),
    then iterate overhead values, timestamps, and policies.

    Returns:
        Tuple[List[dict], float] of (per-run rows, baseline_total_min used
        for scaling).
    """
    template = RunConfig(
        start_ts=0,
        source_grid=directional_pairs[0][0],
        policy_id=policies[0],
        app_size_mb=ANCHOR_APP_SIZE_MB,
        expected_completion_min=2880,
        expected_migration_min=5,
        deadline_multiplier=1.5,
        lookahead_hours=48,
        hw_weighting=True,
        overhead_cost=True,
        deadline_gate=True,
        include_network_power=True,
        use_hw=True,
        # 260513-dkb: 10x cap (480h for a 2880-min job) admits legitimate-but-slow
        # P2/P5 cells at m>=180 that the prior 2x cap (96h) was NaN'ing out and
        # biasing aggregate curves downward via survivorship.
        max_wall_clock_multiplier=10.0,
        sweep_kind="overhead_crossover",
    )

    rows = []
    baseline_total_min_seen = None

    for m in OVERHEAD_GRID_MIN:
        # The scaled_overhead context manager patches Policy 6's bound
        # overhead helpers. Policies 2 and 5 don't call them, so the patch
        # is a no-op for those runs -- Policies 2 and 5 only feel overhead
        # via cfg.expected_migration_min, which we set below.
        with scaled_overhead(float(m), anchor_grid) as so:
            baseline_total_min_seen = so.baseline_total_min  # constant across m
            print(
                f"[PATCH] overhead_min={m:>3d} scale={so.scale:.4f} "
                f"(baseline={so.baseline_total_min:.3f} min, anchor={anchor_grid})"
            )
            for src, dst in directional_pairs:
                pair_lookup = _build_two_grid_lookup(full_lookup, src, dst)
                for ts in timestamps:
                    for p in policies:
                        cfg = replace(
                            template,
                            start_ts=ts,
                            source_grid=src,
                            policy_id=p,
                            expected_migration_min=int(m),
                        )
                        # 260512-kfc: the new useful-work-driven sim raises
                        # RuntimeError if a pathological policy (e.g. Policy 2
                        # with 360-min migrations on a fixture that keeps
                        # offering a cheaper destination) can't reach the
                        # useful-work target within 2x its hour-equivalent. We
                        # record such cells as NaN/0 and continue the sweep
                        # so the rest of the grid still produces curves.
                        try:
                            out = simulate_one_run(pair_lookup, cfg)
                            tc = out["total_carbon_gco2"]
                            bc = out["baseline_carbon_gco2"]
                            mc = out["migration_count"]
                        except RuntimeError as e:
                            if "safety cap" in str(e).lower():
                                print(
                                    f"[CAP] safety cap fired for p={p} "
                                    f"src={src} dst={dst} ts={ts} m={m}: "
                                    "marking NaN and continuing"
                                )
                                tc = float("nan")
                                bc = float("nan")
                                mc = float("nan")
                            else:
                                raise
                        rows.append({
                            "overhead_min": m,
                            "policy": p,
                            "source_grid": src,
                            "dest_grid": dst,
                            "start_ts": ts,
                            "total_carbon_gco2": tc,
                            "baseline_carbon_gco2": bc,
                            "migration_count": mc,
                        })

    return rows, baseline_total_min_seen if baseline_total_min_seen is not None else 0.0


def run_sweep_all_grids(
    full_lookup, hw_grids, timestamps, anchor_grid, policies, use_hw=True,
):
    """Execute the all-grids sweep (Sweep B, 260511-kqo).

    For each ``start_ts`` in ``timestamps``:
      - Pick ``source_grid = argmin over hw_grids of intensity(g, start_ts)``
        ONCE per timestamp (LOCKED: shared across policies and overhead values
        so all policies see identical conditions per timestamp).

    The full 26-grid pool is presented as destinations to every policy. The
    ``scaled_overhead`` monkey-patch wraps each overhead level so Policy 6's
    heuristic-internal estimate scales with the swept knob.

    Returns:
        Tuple[List[dict], float, List[Tuple[int, str]]] of (per-run rows,
        baseline_total_min, sources_by_ts) where ``sources_by_ts`` is a list
        of (start_ts, chosen_source_grid) so downstream summary writers can
        report source diversity.
    """
    template = RunConfig(
        start_ts=0,
        source_grid=hw_grids[0],
        policy_id=policies[0],
        app_size_mb=ANCHOR_APP_SIZE_MB,
        expected_completion_min=2880,
        expected_migration_min=5,
        deadline_multiplier=1.5,
        lookahead_hours=48,
        hw_weighting=True,
        overhead_cost=True,
        deadline_gate=True,
        include_network_power=True,
        use_hw=use_hw,
        # 260513-dkb: 10x cap (480h for a 2880-min job) admits legitimate-but-slow
        # P2/P5 cells at m>=180 that the prior 2x cap (96h) was NaN'ing out and
        # biasing aggregate curves downward via survivorship.
        max_wall_clock_multiplier=10.0,
        sweep_kind="overhead_crossover",
    )

    # Build the full 26-grid lookup ONCE outside the overhead/policy loops --
    # destination candidate pool is invariant across the sweep.
    pool_lookup = _build_filtered_lookup(full_lookup, hw_grids)

    # Precompute the dynamic source per timestamp ONCE. Locked: source is
    # shared across policies and overhead values per CONTEXT.md.
    sources_by_ts = []
    for ts in timestamps:
        src = _pick_dynamic_source(full_lookup, hw_grids, ts, use_hw)
        sources_by_ts.append((ts, src))

    rows = []
    baseline_total_min_seen = None

    for m in OVERHEAD_GRID_MIN:
        with scaled_overhead(float(m), anchor_grid) as so:
            baseline_total_min_seen = so.baseline_total_min
            print(
                f"[PATCH] overhead_min={m:>3d} scale={so.scale:.4f} "
                f"(baseline={so.baseline_total_min:.3f} min, anchor={anchor_grid})"
            )
            for ts, src in sources_by_ts:
                for p in policies:
                    cfg = replace(
                        template,
                        start_ts=ts,
                        source_grid=src,
                        policy_id=p,
                        expected_migration_min=int(m),
                    )
                    # 260512-kfc: see run_sweep — same safety-cap handling.
                    try:
                        out = simulate_one_run(pool_lookup, cfg)
                        tc = out["total_carbon_gco2"]
                        mc = out["migration_count"]
                        dgv = "|".join(out["dest_grids_visited"])
                    except RuntimeError as e:
                        if "safety cap" in str(e).lower():
                            print(
                                f"[CAP] safety cap fired for p={p} src={src} "
                                f"ts={ts} m={m}: marking NaN and continuing"
                            )
                            tc = float("nan")
                            mc = float("nan")
                            dgv = ""
                        else:
                            raise
                    rows.append({
                        "overhead_min": m,
                        "start_ts": ts,
                        "source_grid_chosen": src,
                        "policy": p,
                        "total_carbon": tc,
                        "migration_count": mc,
                        "dest_grids_visited": dgv,
                    })

    return (
        rows,
        baseline_total_min_seen if baseline_total_min_seen is not None else 0.0,
        sources_by_ts,
    )


# ── Aggregation & crossover detection ────────────────────────────────

def per_cell_means_by_direction(rows, directional_pairs, policies):
    """Return per-(src, dst) total-carbon and migration-count mean dicts.

    Output structure::

        carbon[(src, dst)][policy_id] -> list aligned to OVERHEAD_GRID_MIN
        mig_count[(src, dst)][policy_id] -> list aligned to OVERHEAD_GRID_MIN

    Where each list element is the mean across the per-timestamp samples for
    that (overhead, direction, policy) cell. NaN when no samples exist.
    """
    out_carbon = {pair: {p: [] for p in policies} for pair in directional_pairs}
    out_mig = {pair: {p: [] for p in policies} for pair in directional_pairs}
    for m in OVERHEAD_GRID_MIN:
        for src, dst in directional_pairs:
            for p in policies:
                vals = [r["total_carbon_gco2"] for r in rows
                        if r["overhead_min"] == m
                        and r["policy"] == p
                        and r["source_grid"] == src
                        and r["dest_grid"] == dst]
                migs = [r["migration_count"] for r in rows
                        if r["overhead_min"] == m
                        and r["policy"] == p
                        and r["source_grid"] == src
                        and r["dest_grid"] == dst]
                out_carbon[(src, dst)][p].append(
                    mean(vals) if vals else float("nan")
                )
                out_mig[(src, dst)][p].append(
                    mean(migs) if migs else float("nan")
                )
    return out_carbon, out_mig


def find_crossover_pair(a_means, b_means, a_name, b_name):
    """Locate the first overhead at which curve ``a`` stops being worse than ``b``.

    Definition: ``diff[i] = a[i] - b[i]``. Positive means ``a`` is worse.
    Crossover is the smallest ``i >= 1`` where ``sign(diff[i-1]) != sign(diff[i])``
    AND ``diff[i] <= 0`` (``a`` now equal or better). Linear interpolation between
    the bracketing grid points gives the crossover minute, rounded to 0.1.

    Returns:
        Tuple[Optional[float], Optional[int], Optional[str]] -- (crossover_min,
        i, direction_str) where i is the right-side grid index used and
        direction_str is e.g. ``"{a_name} beats {b_name} at overhead >= X min"``.
        All three are None when no crossover exists in the swept range.
    """
    diff = [a - b for a, b in zip(a_means, b_means)]
    for i in range(1, len(OVERHEAD_GRID_MIN)):
        y0, y1 = diff[i - 1], diff[i]
        # Sign-change AND `a` now wins-or-ties.
        if (y0 > 0 and y1 <= 0):
            x0, x1 = OVERHEAD_GRID_MIN[i - 1], OVERHEAD_GRID_MIN[i]
            if y1 == y0:
                # Degenerate flat segment; skip this segment, keep scanning.
                continue
            x_cross = x0 - y0 * (x1 - x0) / (y1 - y0)
            cm = round(x_cross, 1)
            direction_str = (
                f"{a_name} beats {b_name} at overhead >= {cm} min "
                f"(interpolated between {x0} and {x1} min)"
            )
            return cm, i, direction_str
    return None, None, None


def _ordered_pairs(policies):
    """Return ordered list of (a, b) pairs from a policy list, preserving order.

    For policies (2, 5, 6) returns [(2, 5), (2, 6), (5, 6)] — the canonical
    upper-triangular ordering. Each pair is tested twice in the summary (once
    with a vs b and once with b vs a) so we capture sign-change crossovers in
    both directions.
    """
    pairs = []
    for i, a in enumerate(policies):
        for b in policies[i + 1:]:
            pairs.append((a, b))
    return pairs


def aggregate_all_grids(rows, policies):
    """Aggregate Sweep B per-run rows by (overhead, policy) across start_ts.

    Returns:
        Dict[Tuple[int, int], dict] keyed by (overhead_min, policy_id) with
        mean_total_carbon, std_total_carbon (population stdev), mean_migration_count,
        n_samples. Uses population stdev (``statistics.pstdev``) for simplicity --
        documented in the summary methodology section.

    Also exposes carbon_by_policy and mig_by_policy lists aligned to
    OVERHEAD_GRID_MIN for plotting and crossover detection.
    """
    import math as _math
    agg = {}
    for m in OVERHEAD_GRID_MIN:
        for p in policies:
            # 260512-kfc: drop NaN cells (recorded when the sim's safety cap
            # fired for pathological policy/overhead combos). pstdev raises
            # AttributeError on NaN; mean propagates it. Filter at the source.
            carb_raw = [r["total_carbon"] for r in rows
                        if r["overhead_min"] == m and r["policy"] == p]
            migs_raw = [r["migration_count"] for r in rows
                        if r["overhead_min"] == m and r["policy"] == p]
            carb = [v for v in carb_raw if not (isinstance(v, float) and _math.isnan(v))]
            migs = [v for v in migs_raw if not (isinstance(v, float) and _math.isnan(v))]
            n_dropped = len(carb_raw) - len(carb)
            if carb:
                agg[(m, p)] = {
                    "mean_total_carbon": mean(carb),
                    "std_total_carbon": pstdev(carb) if len(carb) > 1 else 0.0,
                    "mean_migration_count": mean(migs) if migs else float("nan"),
                    "n_samples": len(carb),
                    "n_safety_cap_dropped": n_dropped,
                }
            else:
                agg[(m, p)] = {
                    "mean_total_carbon": float("nan"),
                    "std_total_carbon": float("nan"),
                    "mean_migration_count": float("nan"),
                    "n_samples": 0,
                    "n_safety_cap_dropped": n_dropped,
                }
    # Aligned per-policy lists (handy for plotting and crossover detection).
    carbon_by_policy = {
        p: [agg[(m, p)]["mean_total_carbon"] for m in OVERHEAD_GRID_MIN]
        for p in policies
    }
    mig_by_policy = {
        p: [agg[(m, p)]["mean_migration_count"] for m in OVERHEAD_GRID_MIN]
        for p in policies
    }
    return agg, carbon_by_policy, mig_by_policy


# ── Artifact writers ──────────────────────────────────────────────────

def write_csv(rows, path):
    fieldnames = [
        "overhead_min", "policy", "source_grid", "dest_grid", "start_ts",
        "total_carbon_gco2", "baseline_carbon_gco2", "migration_count",
    ]
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            r["overhead_min"], r["source_grid"], r["dest_grid"],
            r["policy"], r["start_ts"],
        ),
    )
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows_sorted:
            w.writerow(r)


def write_plot(carbon_by_dir, pair_crossovers, directional_pairs,
               timestamps, policies, path):
    """Multi-subplot figure dispatching layout on len(directional_pairs).

    - <= 2 pairs: legacy single-row layout, one axes per pair.
    - > 2 pairs: 6 rows x 2 columns grid (rows = unordered pair index, columns
      = direction A->B and B->A); pairs are grouped by their unordered pair
      key so the two directions for each unordered pair sit in the same row.
      Each subplot shows all policy curves with priority-ordered crossover
      annotations capped at 2 to keep visual noise low.

    ``pair_crossovers`` is a nested dict
    ``pair_crossovers[(src, dst)][(a, b)] -> (cm, idx, direction_str) or None``.
    """
    # Priority pair ordering for crossover annotations. P6 vs others first
    # (the heuristic is the thesis-relevant comparator), then P5 vs P2.
    priority_pairs = [
        (5, 6), (6, 5), (4, 6), (6, 4), (3, 6), (6, 3),
        (2, 6), (6, 2), (5, 4), (4, 5), (2, 5), (5, 2),
    ]

    pair_count = len(directional_pairs)
    if pair_count <= 2:
        # Legacy single-row layout (used for backward-compat smoke / k7l replay).
        nrows, ncols = 1, max(1, pair_count)
        fig, axes = plt.subplots(nrows, ncols, figsize=(14, 6), sharey=True)
        if pair_count == 1:
            axes = [axes]
        else:
            axes = list(axes)
        ordered_pairs_for_plot = list(directional_pairs)
    else:
        # Grid layout: group directional pairs by their unordered pair key so
        # both directions of each unordered pair land in the same row. Rows in
        # order of first appearance in ``directional_pairs``.
        unordered_order = []
        unordered_groups = {}
        for src, dst in directional_pairs:
            key = tuple(sorted((src, dst)))
            if key not in unordered_groups:
                unordered_groups[key] = []
                unordered_order.append(key)
            unordered_groups[key].append((src, dst))
        # Build a flat row-major axes order: for each unordered pair (row),
        # column 0 = first directional listed, column 1 = second (or None).
        ordered_pairs_for_plot = []
        for key in unordered_order:
            group = unordered_groups[key]
            ordered_pairs_for_plot.append(group[0])
            ordered_pairs_for_plot.append(group[1] if len(group) > 1 else None)
        nrows = len(unordered_order)
        ncols = 2
        fig, axes_grid = plt.subplots(nrows, ncols, figsize=(13, max(6, 2.7 * nrows)), sharey=False)
        if nrows == 1:
            axes = [axes_grid[0], axes_grid[1]]
        else:
            axes = [ax for row in axes_grid for ax in row]

    for ax_idx, (ax, pair) in enumerate(zip(axes, ordered_pairs_for_plot)):
        if pair is None:
            ax.axis("off")
            continue
        src, dst = pair
        per_policy_means = {p: carbon_by_dir[pair][p] for p in policies}
        for p in policies:
            color = POLICY_COLORS.get(p, "#000000")
            name = POLICY_NAMES.get(p, f"policy {p}")
            ax.plot(
                OVERHEAD_GRID_MIN, per_policy_means[p],
                marker="o", linewidth=1.5, color=color,
                label=f"Policy {p} ({name})",
            )
        all_vals = [v for vs in per_policy_means.values() for v in vs if v == v]
        y_top = max(all_vals) if all_vals else 1.0

        annotated = []
        for (a, b) in priority_pairs:
            if (a, b) not in pair_crossovers.get(pair, {}):
                continue
            cross = pair_crossovers[pair][(a, b)]
            if cross is None:
                continue
            cm, _idx, _direction_str = cross
            if any(abs(cm - prev_cm) < 0.05 for prev_cm, _, _ in annotated):
                continue
            annotated.append((cm, a, b))
            if len(annotated) >= 2:
                break

        for idx, (cm, a, b) in enumerate(annotated):
            ax.axvline(x=cm, linestyle="--", color="gray", linewidth=1.0)
            y_text = y_top if idx == 0 else y_top * 0.92
            ax.text(
                cm, y_text,
                f" P{a}>P{b}~{cm:g}m",
                color="gray", va="top", ha="left", fontsize=7,
            )

        ax.set_title(f"{src} -> {dst}", fontsize=10)
        ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.6)
        ax.tick_params(axis="both", labelsize=8)

    # Axis labels + legend depend on layout.
    if pair_count <= 2:
        for ax in axes:
            ax.set_xlabel("Migration overhead (minutes)")
            ax.legend(loc="upper left", fontsize=8)
        axes[0].set_ylabel("Mean total carbon (gCO2eq, HW-scaled)")
    else:
        # In grid mode: x-label on bottom row, y-label on left column only,
        # legend on first subplot only.
        for col in range(ncols):
            bottom_ax_idx = (nrows - 1) * ncols + col
            if bottom_ax_idx < len(axes) and ordered_pairs_for_plot[bottom_ax_idx] is not None:
                axes[bottom_ax_idx].set_xlabel("Migration overhead (minutes)", fontsize=9)
        for row in range(nrows):
            left_ax_idx = row * ncols
            if ordered_pairs_for_plot[left_ax_idx] is not None:
                axes[left_ax_idx].set_ylabel("Mean total carbon (gCO2eq)", fontsize=9)
        # Legend only on the first non-empty subplot.
        for ax, pair in zip(axes, ordered_pairs_for_plot):
            if pair is not None:
                ax.legend(loc="upper left", fontsize=7)
                break

    fig.suptitle(
        f"Policies {', '.join(str(p) for p in policies)} -- "
        f"carbon vs migration overhead ({pair_count} directional pair"
        f"{'s' if pair_count != 1 else ''}, linked knob)"
    )
    fig.text(
        0.99, 0.02,
        f"{len(timestamps)} starts; 48 h jobs; --use-hw",
        ha="right", va="bottom", fontsize=8, color="dimgray",
    )
    fig.tight_layout(rect=[0, 0.01, 1, 0.97])
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _git_short_sha():
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def write_summary_md(
    path, pair_crossovers, carbon_by_dir, mig_count_by_dir,
    directional_pairs, baseline_total_min, anchor_grid, timestamps,
    policies,
):
    """Render the per-direction pairwise crossover summary markdown.

    For each directional pair, emit:
      - Pairwise crossover sentences for all ordered pairs in ``policies`` —
        both ``(a, b)`` and ``(b, a)`` directions so we capture sign changes
        regardless of which curve starts higher.
      - A per-overhead table with one carbon column and one mig-count column
        per swept policy.
      - A "Sanity checks" subsection reporting min/max migration counts per
        policy (Policy 5 should be approximately constant; Policy 6 should
        drop with overhead).
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = _git_short_sha()
    policies_csv = ", ".join(str(p) for p in policies)
    policies_label = " vs ".join(f"Policy {p}" for p in policies)
    policy_legend = ", ".join(
        f"P{p}={POLICY_NAMES.get(p, str(p))}" for p in policies
    )

    md = [
        f"# Policies {policies_csv} -- Pairwise Overhead Crossover (260511-kqo)",
        "",
        f"**Quick task:** 260511-kqo (extends 260511-k7l / 260511-jce)",
        f"**Comparison:** {policies_label}",
        f"**Policy legend:** {policy_legend}",
        f"**Generated:** {now_iso}",
        f"**Git SHA:** {sha}",
        "",
        "## Sim-core formula (unchanged from 260511-jce)",
        "",
        "Migration carbon at decision hour: "
        "`(expected_migration_min / 60) * source_intensity_at_h` "
        "(HW-scaled iff `use_hw=True`).",
        "Cooldown: `max(0, ceil((expected_migration_min - 60) / 60))` hours.",
        "During cooldown, intensity accumulates on the target grid.",
        "",
        "## Methodology",
        "",
        f"- Policies compared: {policies_label}.",
        "- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound "
        "overhead helpers "
        "(`ckpt_overhead`/`send_overhead`/`restore_overhead` in "
        "`heuristics.policy_heuristic`) scaled by "
        "`target_minutes / baseline_total_min`.",
        "- **The `scaled_overhead` monkey-patch is a no-op for Policies 2 and 5.** "
        "Neither imports the overhead helpers; they only feel overhead via "
        "`cfg.expected_migration_min` (the sim core's minute-granular "
        "source-side carbon charge at the decision hour). The linked knob "
        "bites Policy 6 alone via its heuristic overhead estimator.",
        f"- Baseline total: `{baseline_total_min:.3f}` min "
        f"(linear fit at {ANCHOR_APP_SIZE_MB:g} MB, anchor `{anchor_grid}`).",
        f"- Grid: {list(OVERHEAD_GRID_MIN)}",
        f"- Samples: {len(timestamps)} 2020 hourly starts per direction.",
        f"- Directions: {[f'{s}->{d}' for s, d in directional_pairs]}",
        "- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), "
        "use_hw=True.",
        "",
    ]

    ordered_pairs = _ordered_pairs(policies)

    for pair in directional_pairs:
        src, dst = pair
        md.append(f"## {src} -> {dst}")
        md.append("")
        md.append("**Pairwise crossover analysis:**")
        md.append("")
        # For each ordered pair (a, b) where a precedes b in policies, report
        # both (a vs b) and (b vs a) — only one direction can fire at a time
        # so we emit a single "no crossover" line when neither does. When the
        # policy list is large (>= 4 policies), group "no crossover" pairs into
        # a single trailing counter line per CONTEXT.md verbosity rule.
        group_no_cross = len(policies) >= 4
        no_cross_pairs = []
        for (a, b) in ordered_pairs:
            ab = pair_crossovers.get(pair, {}).get((a, b))
            ba = pair_crossovers.get(pair, {}).get((b, a))
            if ab is not None:
                _cm, _idx, direction_str = ab
                md.append(f"- P{a} vs P{b}: {direction_str}.")
            elif ba is not None:
                _cm, _idx, direction_str = ba
                md.append(f"- P{a} vs P{b}: {direction_str}.")
            else:
                if group_no_cross:
                    no_cross_pairs.append((a, b))
                else:
                    md.append(
                        f"- P{a} vs P{b}: no crossover in swept range "
                        f"[0, {OVERHEAD_GRID_MIN[-1]}] min."
                    )
        if group_no_cross and no_cross_pairs:
            joined = ", ".join(f"P{a}-vs-P{b}" for a, b in no_cross_pairs)
            md.append(
                f"- All other {len(no_cross_pairs)} pairs: no crossover in "
                f"[0, {OVERHEAD_GRID_MIN[-1]}] min ({joined})."
            )
        md.append("")

        # Per-overhead carbon + mig-count table. One carbon column and one
        # mig-count column per swept policy; diff column omitted to keep
        # the table narrow (pairwise crossover statements above carry the
        # comparisons).
        header_cells = ["overhead_min"]
        header_cells += [f"P{p} carbon" for p in policies]
        header_cells += [f"P{p} mig_count" for p in policies]
        md.append("| " + " | ".join(header_cells) + " |")
        md.append("| " + " | ".join(["---"] * len(header_cells)) + " |")
        c = carbon_by_dir[pair]
        mc = mig_count_by_dir[pair]
        for i, m in enumerate(OVERHEAD_GRID_MIN):
            row_cells = [str(m)]
            row_cells += [f"{c[p][i]:.1f}" for p in policies]
            row_cells += [f"{mc[p][i]:.2f}" for p in policies]
            md.append("| " + " | ".join(row_cells) + " |")
        md.append("")

        # Sanity checks: per-policy mig-count min/max across overhead grid.
        md.append("**Sanity checks (migration-count range across overhead grid):**")
        md.append("")
        md.append("| Policy | min mig_count | max mig_count | range |")
        md.append("| --- | --- | --- | --- |")
        for p in policies:
            vals = [v for v in mc[p] if v == v]  # filter NaN
            if not vals:
                md.append(f"| P{p} | -- | -- | -- |")
                continue
            mn, mx = min(vals), max(vals)
            md.append(
                f"| P{p} ({POLICY_NAMES.get(p, str(p))}) | "
                f"{mn:.2f} | {mx:.2f} | {(mx - mn):.2f} |"
            )
        md.append("")
        md.append(
            "Expected pattern: Policy 5's range is near zero (its decision "
            "ignores the overhead knob — it only compares the current grid "
            "against the partner grid one hour ahead). Policy 2's range is "
            "also small (always-best with no overhead model), but may drop "
            "slightly at very high overhead as the source-side minute-granular "
            "cost in the sim core renders some marginal migrations no longer "
            "worth it. Policy 6's range is larger (the linked knob bites: at "
            "high overhead its heuristic refuses migrations it would have "
            "made at low overhead)."
        )
        md.append("")

    md.extend([
        "## Files",
        "",
        "- `curves.csv` -- long-format per-run results (one row per "
        "(overhead, direction, policy, start_ts)).",
        "- `curves.png` -- two-subplot multi-policy line plot with pairwise "
        "crossover annotations where present.",
        "",
    ])

    with open(path, "w") as f:
        f.write("\n".join(md))


# ── Sweep B (all-grids) writers ───────────────────────────────────────

def write_all_grids_csv(rows, path):
    """Write Sweep B per-run rows (LOCKED schema)."""
    fieldnames = [
        "overhead_min", "start_ts", "source_grid_chosen", "policy",
        "total_carbon", "migration_count", "dest_grids_visited",
    ]
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            r["overhead_min"], r["policy"], r["start_ts"],
        ),
    )
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows_sorted:
            w.writerow(r)


def write_all_grids_aggregates(agg, policies, path):
    """Write Sweep B aggregates (per (overhead, policy)) CSV."""
    fieldnames = [
        "overhead_min", "policy", "mean_total_carbon", "std_total_carbon",
        "mean_migration_count", "n_samples",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for m in OVERHEAD_GRID_MIN:
            for p in policies:
                a = agg[(m, p)]
                w.writerow({
                    "overhead_min": m,
                    "policy": p,
                    "mean_total_carbon": round(a["mean_total_carbon"], 1)
                        if a["mean_total_carbon"] == a["mean_total_carbon"] else "",
                    "std_total_carbon": round(a["std_total_carbon"], 1)
                        if a["std_total_carbon"] == a["std_total_carbon"] else "",
                    "mean_migration_count": round(a["mean_migration_count"], 3)
                        if a["mean_migration_count"] == a["mean_migration_count"] else "",
                    "n_samples": a["n_samples"],
                })


def write_all_grids_plot(carbon_by_policy, mig_by_policy, policies,
                         timestamps, hw_grids, path):
    """Single-panel mean-carbon-vs-overhead plot for Sweep B (6 policy curves)."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    for p in policies:
        color = POLICY_COLORS.get(p, "#000000")
        name = POLICY_NAMES.get(p, f"policy {p}")
        ax.plot(
            OVERHEAD_GRID_MIN, carbon_by_policy[p],
            marker="o", linewidth=1.8, color=color,
            label=f"Policy {p} ({name})",
        )
    ax.set_xlabel("Migration overhead (minutes)")
    ax.set_ylabel("Mean total carbon (gCO2eq, HW-scaled, averaged across start_ts)")
    ax.set_title(
        f"All-grids sweep: {len(hw_grids)}-grid HW destination pool, "
        f"dynamic source per start_ts (260511-kqo)"
    )
    ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.6)
    ax.legend(loc="upper left", fontsize=9)
    fig.text(
        0.99, 0.02,
        f"{len(timestamps)} starts; 48 h jobs; --use-hw; "
        f"argmin-of-{len(hw_grids)} source",
        ha="right", va="bottom", fontsize=8, color="dimgray",
    )
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    fig.savefig(path, dpi=140)
    plt.close(fig)


def write_all_grids_summary_md(
    path, agg, rows, policies, baseline_total_min, anchor_grid, timestamps,
    hw_grids, sources_by_ts, carbon_by_policy, mig_by_policy,
):
    """Render the Sweep B summary markdown.

    Sections:
      - Methodology (dynamic-source + all-HW-dest pool)
      - Pairwise crossover sentences across the 6 policies on aggregated curves
        (C(6,2)=15 pairs in both directions; "no crossover" grouped)
      - Per-overhead aggregate table (mean carbon + mean mig_count per policy)
      - Destination diversity (unique dest_grids_visited values per policy)
      - Source diversity (distinct values of source_grid_chosen across timestamps)
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = _git_short_sha()
    policies_csv = ", ".join(str(p) for p in policies)
    policy_legend = ", ".join(
        f"P{p}={POLICY_NAMES.get(p, str(p))}" for p in policies
    )

    md = [
        f"# Policies {policies_csv} -- All-HW-Grids Sweep (260511-kqo)",
        "",
        f"**Quick task:** 260511-kqo (Sweep B: dynamic source + 26-grid HW destinations)",
        f"**Policy legend:** {policy_legend}",
        f"**Generated:** {now_iso}",
        f"**Git SHA:** {sha}",
        "",
        "## Methodology",
        "",
        f"- Destination candidate pool: all {len(hw_grids)} HW-pool grids "
        f"(from `data/hardware/hw_avg.csv`).",
        "- Source grid per `start_ts`: dynamic — "
        "`argmin over HW_POOL_GRIDS of lookup_intensity(g, start_ts)` "
        "(HW-scaled iff `use_hw=True`). Computed ONCE per timestamp; "
        "all policies and overhead values share the same source per ts.",
        "- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound "
        "overhead helpers scaled by `target_minutes / baseline_total_min`.",
        f"- Baseline total: `{baseline_total_min:.3f}` min "
        f"(linear fit at {ANCHOR_APP_SIZE_MB:g} MB, anchor `{anchor_grid}`).",
        f"- Overhead grid: {list(OVERHEAD_GRID_MIN)}",
        f"- Samples: {len(timestamps)} sub-sampled 2020 hourly starts.",
        f"- Stdev reported is population stdev (`statistics.pstdev`).",
        "- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), use_hw=True.",
        "",
    ]

    # Pairwise crossovers on aggregated curves.
    md.append("## Pairwise crossovers on aggregated curves")
    md.append("")
    ordered_pairs = _ordered_pairs(policies)
    pair_crossovers = {}
    for a in policies:
        for b in policies:
            if a == b:
                continue
            res = find_crossover_pair(
                carbon_by_policy[a], carbon_by_policy[b],
                f"P{a}", f"P{b}",
            )
            if res[0] is None:
                pair_crossovers[(a, b)] = None
            else:
                pair_crossovers[(a, b)] = res

    group_no_cross = len(policies) >= 4
    no_cross_pairs = []
    for (a, b) in ordered_pairs:
        ab = pair_crossovers.get((a, b))
        ba = pair_crossovers.get((b, a))
        if ab is not None:
            md.append(f"- P{a} vs P{b}: {ab[2]}.")
        elif ba is not None:
            md.append(f"- P{a} vs P{b}: {ba[2]}.")
        else:
            if group_no_cross:
                no_cross_pairs.append((a, b))
            else:
                md.append(
                    f"- P{a} vs P{b}: no crossover in swept range "
                    f"[0, {OVERHEAD_GRID_MIN[-1]}] min."
                )
    if group_no_cross and no_cross_pairs:
        joined = ", ".join(f"P{a}-vs-P{b}" for a, b in no_cross_pairs)
        md.append(
            f"- All other {len(no_cross_pairs)} pairs: no crossover in "
            f"[0, {OVERHEAD_GRID_MIN[-1]}] min ({joined})."
        )
    md.append("")

    # Per-overhead aggregate table.
    md.append("## Per-overhead aggregates")
    md.append("")
    header_cells = ["overhead_min"]
    header_cells += [f"P{p} carbon" for p in policies]
    header_cells += [f"P{p} mig_count" for p in policies]
    md.append("| " + " | ".join(header_cells) + " |")
    md.append("| " + " | ".join(["---"] * len(header_cells)) + " |")
    for i, m in enumerate(OVERHEAD_GRID_MIN):
        cells = [str(m)]
        cells += [f"{carbon_by_policy[p][i]:.1f}" for p in policies]
        cells += [f"{mig_by_policy[p][i]:.2f}" for p in policies]
        md.append("| " + " | ".join(cells) + " |")
    md.append("")

    # Sanity checks: per-policy mig-count range.
    md.append("**Sanity checks (migration-count range across overhead grid):**")
    md.append("")
    md.append("| Policy | min mig_count | max mig_count | range |")
    md.append("| --- | --- | --- | --- |")
    for p in policies:
        vals = [v for v in mig_by_policy[p] if v == v]
        if not vals:
            md.append(f"| P{p} | -- | -- | -- |")
            continue
        mn, mx = min(vals), max(vals)
        md.append(
            f"| P{p} ({POLICY_NAMES.get(p, str(p))}) | "
            f"{mn:.2f} | {mx:.2f} | {(mx - mn):.2f} |"
        )
    md.append("")

    # Destination diversity per policy: across ALL rows for each policy,
    # union the dest_grids_visited token sets.
    md.append("## Destination diversity")
    md.append("")
    md.append(
        "For each policy, the set of unique destinations actually visited "
        "across all (overhead, start_ts) runs. A policy with high diversity is "
        "exploring more of the destination pool; low diversity may indicate "
        "the policy locks in a single attractor early."
    )
    md.append("")
    md.append("| Policy | Distinct destinations | Top-5 (count) |")
    md.append("| --- | --- | --- |")
    distinct_counts = {}
    for p in policies:
        ctr = Counter()
        for r in rows:
            if r["policy"] != p:
                continue
            for g in r["dest_grids_visited"].split("|"):
                g = g.strip()
                if g:
                    ctr[g] += 1
        distinct = len(ctr)
        distinct_counts[p] = distinct
        top5 = ctr.most_common(5)
        top5_str = ", ".join(f"{g}({c})" for g, c in top5) if top5 else "(none)"
        md.append(
            f"| P{p} ({POLICY_NAMES.get(p, str(p))}) | {distinct} | {top5_str} |"
        )
    md.append("")
    # One-sentence headline comparison.
    cmp_parts = []
    for p in policies:
        cmp_parts.append(f"P{p}={distinct_counts.get(p, 0)}")
    md.append(
        "Headline: distinct destinations per policy across the run set — "
        + ", ".join(cmp_parts) + "."
    )
    md.append("")

    # Source diversity: distinct values of source_grid_chosen across timestamps.
    md.append("## Source diversity")
    md.append("")
    src_ctr = Counter(src for _ts, src in sources_by_ts)
    md.append(
        f"Across the {len(sources_by_ts)} timestamps, the dynamic argmin chose "
        f"{len(src_ctr)} distinct source grids."
    )
    md.append("")
    md.append("| Source grid | Times chosen |")
    md.append("| --- | --- |")
    for g, c in src_ctr.most_common():
        md.append(f"| {g} | {c} |")
    md.append("")

    md.extend([
        "## Files",
        "",
        "- `curves.csv` -- per-run rows (overhead_min, start_ts, "
        "source_grid_chosen, policy, total_carbon, migration_count, "
        "dest_grids_visited).",
        "- `aggregates.csv` -- per-(overhead, policy) means/stds across start_ts.",
        "- `curves.png` -- single-panel mean-carbon-vs-overhead plot with one "
        "curve per policy.",
        "",
    ])

    with open(path, "w") as f:
        f.write("\n".join(md))


# ── CLI ───────────────────────────────────────────────────────────────

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Multi-policy overhead-crossover sweep "
                    "(260511-kqo, extends 260511-k7l/jce)"
    )
    p.add_argument(
        "--mode", choices=("pairwise", "all-grids"), default="pairwise",
        help=(
            "pairwise (default): sweep --pairs directional pairs. "
            "all-grids: dynamic argmin-of-HW-pool source per start_ts; "
            "all 26 HW grids in destination pool. Sweep B (260511-kqo)."
        ),
    )
    p.add_argument("--regions-dir", default=None,
                   help="Override regions tree root (default: data/regions/)")
    p.add_argument("--pairs", nargs="+", default=None,
                   help="Directional pairs as SRC:DST tokens, e.g. BANC:CISO. "
                        "Default: BANC:CISO and CISO:BANC. Ignored when "
                        "--mode all-grids.")
    p.add_argument(
        "--policies", default=None,
        help=(
            "Comma-separated policy ids to sweep (e.g. '1,2,3,4,5,6'). "
            "Default: 2,5,6. Ids must be in 1..6 and unique; the order you "
            "type controls plot/CSV/summary ordering."
        ),
    )
    p.add_argument("--num-timestamps", type=int, default=24,
                   help="Number of sub-sampled 2020 hourly starts "
                        "(default: 24)")
    p.add_argument("--smoke", action="store_true",
                   help="Smoke run with N=4 starts for <60 s sanity check")
    p.add_argument("--out-dir", default=None,
                   help="Override output directory")
    p.add_argument("--self-check", action="store_true",
                   help="Run inline wiring assertions before completing")
    return p.parse_args(argv)


def _run_pairwise_mode(
    args, regions_root, out_dir, usable, policies, timestamps, t0,
):
    """Sweep A: pairwise directional sweep across --pairs."""
    directional_pairs = _resolve_directional_pairs(usable, args.pairs)
    pair_grids = tuple({g for pair in directional_pairs for g in pair})
    anchor_grid = _pick_anchor_grid(usable, preferred=("BANC", "CISO", "ISNE"))

    missing = [g for g in pair_grids if g not in usable]
    if missing:
        print(
            f"[SWEEP] ERROR: directional pair endpoints {missing} not in "
            f"usable grid set ({usable})",
            file=sys.stderr,
        )
        return 1

    print(
        f"[SWEEP] mode=pairwise\n"
        f"[SWEEP] directional_pairs={directional_pairs} anchor={anchor_grid}\n"
        f"[SWEEP] timestamps: {len(timestamps)} starts "
        f"(first={timestamps[0]}, last={timestamps[-1]})\n"
        f"[SWEEP] overhead_grid={list(OVERHEAD_GRID_MIN)} min\n"
        f"[SWEEP] policies={list(policies)}\n"
        f"[SWEEP] out_dir={out_dir}"
    )

    lookup = build_intensity_lookup_from_regions_tree(
        regions_root, allowed_grids=tuple(sorted(pair_grids)),
    )
    print(f"[SWEEP] intensity_lookup: {len(lookup)} (grid, ts) entries")

    rows, baseline_total_min = run_sweep(
        lookup, directional_pairs, timestamps, anchor_grid, policies,
    )
    print(
        f"[SWEEP] completed {len(rows)} simulated runs in "
        f"{time.time() - t0:.2f} s"
    )

    # Self-check assertion: expected row count.
    if args.self_check:
        expected = (
            len(policies) * len(directional_pairs)
            * len(OVERHEAD_GRID_MIN) * len(timestamps)
        )
        assert len(rows) == expected, (
            f"[SELF-CHECK] pairwise row count {len(rows)} != expected {expected}"
        )
        # dest_grids_visited threading is opaque to pairwise rows but the sim
        # core was verified in Task 1; spot-check at least one row has the key.
        sample = simulate_one_run(
            _build_two_grid_lookup(lookup, *directional_pairs[0]),
            RunConfig(
                start_ts=timestamps[0], source_grid=directional_pairs[0][0],
                policy_id=policies[0],
                # 260513-dkb: match the sweep's 10x cap for consistency.
                max_wall_clock_multiplier=10.0,
            ),
        )
        assert "dest_grids_visited" in sample, (
            "[SELF-CHECK] simulate_one_run missing dest_grids_visited key"
        )
        print(f"[SELF-CHECK] pairwise row count = {len(rows)} (expected {expected}) -- OK")

    carbon_by_dir, mig_count_by_dir = per_cell_means_by_direction(
        rows, directional_pairs, policies,
    )

    pair_crossovers = {}
    for pair in directional_pairs:
        d = {}
        for a in policies:
            for b in policies:
                if a == b:
                    continue
                d[(a, b)] = find_crossover_pair(
                    carbon_by_dir[pair][a], carbon_by_dir[pair][b],
                    f"P{a}", f"P{b}",
                )
                if d[(a, b)][0] is None:
                    d[(a, b)] = None
        pair_crossovers[pair] = d

    # Sanity print of mig-count ranges.
    for pair in directional_pairs:
        src, dst = pair
        for p in policies:
            vals = [v for v in mig_count_by_dir[pair][p] if v == v]
            if vals:
                print(
                    f"[SWEEP] Policy {p} mig_count range {src}->{dst}: "
                    f"[{min(vals):.2f}..{max(vals):.2f}] "
                    f"(span={(max(vals) - min(vals)):.2f})"
                )

    csv_path = out_dir / "curves.csv"
    png_path = out_dir / "curves.png"
    md_path = out_dir / "crossover_summary.md"

    write_csv(rows, csv_path)
    print(f"[PLOT] wrote {csv_path}")
    write_plot(
        carbon_by_dir, pair_crossovers, directional_pairs,
        timestamps, policies, png_path,
    )
    print(f"[PLOT] wrote {png_path}")
    write_summary_md(
        md_path, pair_crossovers, carbon_by_dir, mig_count_by_dir,
        directional_pairs, baseline_total_min, anchor_grid, timestamps,
        policies,
    )
    print(f"[PLOT] wrote {md_path}")

    # Per-direction RESULT lines.
    ordered_pairs = _ordered_pairs(policies)
    for pair in directional_pairs:
        src, dst = pair
        parts = []
        for (a, b) in ordered_pairs:
            ab = pair_crossovers[pair].get((a, b))
            ba = pair_crossovers[pair].get((b, a))
            cross = ab if ab is not None else ba
            if cross is None:
                parts.append(f"P{a}-vs-P{b}: no crossover in [0, {OVERHEAD_GRID_MIN[-1]}] min")
            else:
                cm, _idx, direction_str = cross
                parts.append(f"P{a}-vs-P{b}: {direction_str}")
        print(f"[SWEEP] RESULT {src}->{dst}: " + "; ".join(parts) + ".")

    print(f"[SWEEP] total wall-clock: {time.time() - t0:.2f} s")
    return 0


def _run_all_grids_mode(
    args, regions_root, out_dir, usable, policies, timestamps, t0,
):
    """Sweep B: all-grids mode -- dynamic source + 26-grid HW destination pool."""
    if args.pairs:
        print(
            f"[SWEEP] WARNING: --pairs {args.pairs} ignored under "
            f"--mode all-grids (destination pool is the full HW set)."
        )

    # HW pool intersected with disk-available grids.
    missing_hw = [g for g in HW_POOL_GRIDS if g not in usable]
    if missing_hw:
        print(
            f"[SWEEP] ERROR: HW_POOL_GRIDS contains {len(missing_hw)} grids "
            f"missing from disk: {missing_hw}",
            file=sys.stderr,
        )
        return 1
    hw_pool = list(HW_POOL_GRIDS)
    anchor_grid = _pick_anchor_grid(hw_pool, preferred=("BANC", "CISO", "ISNE"))

    # Rule 2 (auto-add critical functionality): filter HW grids whose carbon
    # data is entirely zero/missing. SCL is the known case (all 17,541 entries
    # are 0.0 in data/regions/). A grid with no usable data would silently
    # degenerate Sweep B because (a) the dynamic argmin source selector would
    # always pick it, and (b) every policy's get_min_grid_at would lock onto
    # it as destination. Pre-build a temporary lookup to detect this.
    _probe_lookup = build_intensity_lookup_from_regions_tree(
        regions_root, allowed_grids=tuple(sorted(hw_pool)),
    )
    empty_grids = []
    for g in list(hw_pool):
        vals = [v for (gg, _ts), v in _probe_lookup.items() if gg == g and v > 0.0]
        if not vals:
            empty_grids.append(g)
    if empty_grids:
        print(
            f"[SWEEP] WARNING: HW pool grids with NO nonzero carbon data "
            f"(filtered out): {empty_grids}"
        )
        hw_pool = [g for g in hw_pool if g not in empty_grids]

    print(
        f"[SWEEP] mode=all-grids\n"
        f"[SWEEP] hw_pool_size={len(hw_pool)} anchor={anchor_grid}\n"
        f"[SWEEP] hw_pool={hw_pool}\n"
        f"[SWEEP] timestamps: {len(timestamps)} starts "
        f"(first={timestamps[0]}, last={timestamps[-1]})\n"
        f"[SWEEP] overhead_grid={list(OVERHEAD_GRID_MIN)} min\n"
        f"[SWEEP] policies={list(policies)}\n"
        f"[SWEEP] out_dir={out_dir}"
    )

    lookup = build_intensity_lookup_from_regions_tree(
        regions_root, allowed_grids=tuple(sorted(hw_pool)),
    )
    print(f"[SWEEP] intensity_lookup: {len(lookup)} (grid, ts) entries")

    rows, baseline_total_min, sources_by_ts = run_sweep_all_grids(
        lookup, hw_pool, timestamps, anchor_grid, policies, use_hw=True,
    )
    print(
        f"[SWEEP] completed {len(rows)} simulated runs in "
        f"{time.time() - t0:.2f} s"
    )

    # Self-check assertions.
    if args.self_check:
        expected = len(policies) * len(OVERHEAD_GRID_MIN) * len(timestamps)
        assert len(rows) == expected, (
            f"[SELF-CHECK] all-grids row count {len(rows)} != expected {expected}"
        )
        # Confirm dynamic source picked is in the filtered HW pool.
        for _ts, src in sources_by_ts:
            assert src in hw_pool, (
                f"[SELF-CHECK] dynamic source {src!r} not in hw_pool {hw_pool}"
            )
        # Confirm dest_grids_visited is present in row schema (even if empty).
        assert "dest_grids_visited" in rows[0], (
            "[SELF-CHECK] dest_grids_visited column missing from rows"
        )
        print(f"[SELF-CHECK] all-grids row count = {len(rows)} (expected {expected}) -- OK")
        print(f"[SELF-CHECK] dynamic sources all in HW pool -- OK")

    agg, carbon_by_policy, mig_by_policy = aggregate_all_grids(rows, policies)

    # Sanity print of mig-count ranges per policy.
    for p in policies:
        vals = [v for v in mig_by_policy[p] if v == v]
        if vals:
            print(
                f"[SWEEP] Policy {p} mig_count range (all-grids): "
                f"[{min(vals):.2f}..{max(vals):.2f}] "
                f"(span={(max(vals) - min(vals)):.2f})"
            )

    # Console print of distinct destinations per policy (CONTEXT.md request).
    print("[SWEEP] Distinct destinations per policy:")
    for p in policies:
        seen = set()
        for r in rows:
            if r["policy"] != p:
                continue
            for g in r["dest_grids_visited"].split("|"):
                g = g.strip()
                if g:
                    seen.add(g)
        print(f"[SWEEP]   Policy {p} ({POLICY_NAMES.get(p, '?')}): {len(seen)} distinct destinations")

    csv_path = out_dir / "curves.csv"
    agg_path = out_dir / "aggregates.csv"
    png_path = out_dir / "curves.png"
    md_path = out_dir / "crossover_summary.md"

    write_all_grids_csv(rows, csv_path)
    print(f"[PLOT] wrote {csv_path}")
    write_all_grids_aggregates(agg, policies, agg_path)
    print(f"[PLOT] wrote {agg_path}")
    write_all_grids_plot(
        carbon_by_policy, mig_by_policy, policies, timestamps, hw_pool, png_path,
    )
    print(f"[PLOT] wrote {png_path}")
    write_all_grids_summary_md(
        md_path, agg, rows, policies, baseline_total_min, anchor_grid,
        timestamps, hw_pool, sources_by_ts, carbon_by_policy, mig_by_policy,
    )
    print(f"[PLOT] wrote {md_path}")

    # Final summary line.
    ordered_pairs = _ordered_pairs(policies)
    parts = []
    for (a, b) in ordered_pairs:
        # Compute on the fly for stdout.
        res = find_crossover_pair(
            carbon_by_policy[a], carbon_by_policy[b], f"P{a}", f"P{b}",
        )
        if res[0] is None:
            res = find_crossover_pair(
                carbon_by_policy[b], carbon_by_policy[a], f"P{b}", f"P{a}",
            )
        if res[0] is None:
            parts.append(f"P{a}-vs-P{b}: no crossover")
        else:
            parts.append(f"P{a}-vs-P{b}: {res[2]}")
    print(f"[SWEEP] RESULT all-grids: " + "; ".join(parts) + ".")

    print(f"[SWEEP] total wall-clock: {time.time() - t0:.2f} s")
    return 0


def main(argv=None) -> int:
    args = _parse_args(argv)
    t0 = time.time()

    regions_root = Path(args.regions_dir) if args.regions_dir else DEFAULT_REGIONS_TREE_DIR
    if args.out_dir is not None:
        out_dir = Path(args.out_dir)
    else:
        out_dir = SWEEP_B_OUT_DIR if args.mode == "all-grids" else SWEEP_A_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve usable grids = those present on disk AND in HW_TABLE.
    discovered = set(discover_grids(regions_root))
    if not discovered:
        print(
            f"[SWEEP] ERROR: no grid CSVs found under {regions_root}",
            file=sys.stderr,
        )
        return 1
    usable = sorted(discovered & set(HW_TABLE.keys()))
    if not usable:
        print(
            f"[SWEEP] ERROR: no overlap between discovered grids "
            f"({sorted(discovered)[:5]}...) and HW_TABLE keys",
            file=sys.stderr,
        )
        return 1

    policies = _resolve_policies(args.policies)

    all_ts = _main_sweep_timestamps(2020)
    n = 4 if args.smoke else int(args.num_timestamps)
    timestamps = _resolve_timestamps(all_ts, n)

    print(
        f"[SWEEP] regions_root={regions_root}\n"
        f"[SWEEP] usable_grids={usable}"
    )

    if args.mode == "all-grids":
        return _run_all_grids_mode(
            args, regions_root, out_dir, usable, policies, timestamps, t0,
        )
    return _run_pairwise_mode(
        args, regions_root, out_dir, usable, policies, timestamps, t0,
    )


if __name__ == "__main__":
    sys.exit(main())
