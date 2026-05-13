#!/usr/bin/env python3
"""Gantt-style per-policy runtime-breakdown plotter (quick task 260512-j87).

Complementary view to ``sweep_overhead_crossover.py``: instead of aggregating
many runs into mean-carbon-vs-overhead curves, this script zooms into specific
48-hour simulation traces and visualizes — per policy — what the pod is doing
at each hour of the simulation:

  - running on the BANC grid (one color)
  - running on the CISO grid (another color)
  - in the middle of a migration (split into ckpt / send / restore phases)

Output (locked defaults, 4 seasonal starts x 2 directions x 6 policies x
1 overhead value = 48 sims producing 8 PNGs + ``runs_summary.csv``):

  data/quick/260512-j87-runtime-breakdown-banc-ciso/
    30min_2020-01-16_BANC-CISO.png
    30min_2020-01-16_CISO-BANC.png
    30min_2020-04-16_BANC-CISO.png
    30min_2020-04-16_CISO-BANC.png
    30min_2020-07-17_BANC-CISO.png
    30min_2020-07-17_CISO-BANC.png
    30min_2020-10-16_BANC-CISO.png
    30min_2020-10-16_CISO-BANC.png
    runs_summary.csv

Reproducibility: the sim is deterministic given an ``intensity_lookup`` and a
``RunConfig`` — same inputs produce byte-identical PNGs and CSV across runs.

Design notes:

  - DO NOT modify ``_simulation_core.py``. We capture per-hour migration
    decisions via the LOCKED wrapper approach: monkey-patch
    ``_simulation_core._simulate_policy_decision`` inside a ``try/finally``
    block for the duration of one ``simulate_one_run`` call. This is the same
    technique used by ``sweep_overhead_crossover.scaled_overhead``.

  - Phase split synthesis runs OUTSIDE the simulation. We use the *original*
    (unpatched) ``heuristics.overhead.{ckpt,send,restore}_overhead`` helpers
    and scale their (ckpt:send:restore) ratio proportionally to match the
    simulated overhead (e.g. 30 min). We do NOT import / use
    ``sweep_overhead_crossover.scaled_overhead`` because that patches Policy
    6's *internal* estimator and we do not want to affect policy decisions
    here — we're only visualizing.

  - Carbon-accounting note: for sub-60-min overhead (cooldown=0) the sim's
    minute-granular lump-sum source charge at the decision hour is consistent
    with the visualized "30 min of the 60-min hour is migration phases on
    source" model. For >60-min overhead the visualization extrapolates phase
    durations across hour boundaries while the sim still charges only at the
    decision hour's source intensity. The locked overhead here is 30 min so
    we do not exercise that regime; the plot caption notes the disclaimer.
"""

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Project import shim (mirror sweep_overhead_crossover.py lines 99-102 so we
# can import the same controller-package modules without installing them).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _simulation_core import RunConfig, simulate_one_run  # noqa: E402
import _simulation_core as sc  # noqa: E402
from evaluate_policies import (  # noqa: E402
    DEFAULT_REGIONS_TREE_DIR,
    build_intensity_lookup_from_regions_tree,
)
from heuristics.hardware import HW_TABLE  # noqa: E402
from heuristics.overhead import (  # noqa: E402
    ckpt_overhead,
    send_overhead,
    restore_overhead,
)
from sweep_overhead_crossover import (  # noqa: E402
    ANCHOR_APP_SIZE_MB,
    DIRECTIONAL_PAIRS,
    _build_two_grid_lookup,
)


# ── Constants (LOCKED by CONTEXT.md) ──────────────────────────────────

POLICIES_DEFAULT: Tuple[int, ...] = (1, 2, 3, 4, 5, 6)
VALID_POLICY_IDS = frozenset(POLICIES_DEFAULT)

# 4 seasonal anchors (one per quarter) at 00:00 UTC, in 2020.
SEASONAL_STARTS_2020: Tuple[int, ...] = tuple(
    int(datetime(2020, m, d, tzinfo=timezone.utc).timestamp())
    for m, d in ((1, 16), (4, 16), (7, 17), (10, 16))
)

# Single overhead value mid-range; sub-hour so phase breakdown is interesting.
OVERHEAD_MIN_DEFAULT: int = 30

# Repo data root: data/quick/...
_DATA_QUICK = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "quick"
)
OUT_DIR_DEFAULT: Path = _DATA_QUICK / "260512-j87-runtime-breakdown-banc-ciso"

# Plot colors (LOCKED in CONTEXT.md "Claude's Discretion").
COLOR_MAP: Dict[str, str] = {
    "grid_BANC": "#1f77b4",   # saturated blue
    "grid_CISO": "#ff7f0e",   # saturated orange
    "ckpt":      "#bdbdbd",   # light gray
    "send":      "#757575",   # medium gray
    "restore":   "#37474f",   # dark charcoal
}

# Caption locked verbatim by must_haves entry 7.
SUBTITLE_LOCKED: str = (
    "Phase durations synthesized from heuristics/overhead.py linear fits at "
    "64 MB, scaled proportionally to match the 30-min sim overhead."
)


# ── Task 1: Data-producing core ──────────────────────────────────────

def simulate_with_decisions(intensity_lookup, cfg: RunConfig) -> Dict[str, Any]:
    """Run ``simulate_one_run`` while capturing per-hour migration decisions.

    Wraps ``_simulation_core._simulate_policy_decision`` via module-attribute
    monkey-patch inside a ``try/finally`` so the original function is restored
    even if the simulation raises. On every accepted migration decision
    (``should_migrate=True`` AND ``target_grid is not None``) we record::

        {"hour": int(elapsed_hours),
         "source_grid": current_grid,   # grid pod was on BEFORE the migration
         "target_grid": target_grid}

    Self-consistency assertions guarantee the captured event list aligns with
    the sim's ``migration_count`` and ``dest_grids_visited`` fields. A
    mismatch would indicate sim-core drift and is surfaced loudly.

    Args:
        intensity_lookup: ``{(grid, ts): intensity}`` (typically a two-grid
            subset produced by ``_build_two_grid_lookup``).
        cfg: ``RunConfig`` for the single simulation.

    Returns:
        The unmodified ``simulate_one_run`` return dict, plus a new key
        ``migration_events: List[Dict[str, Any]]``.
    """
    events: List[Dict[str, Any]] = []
    orig = sc._simulate_policy_decision

    def wrapped(
        policy_obj,
        intensity_lookup_,
        grids,
        current_grid,
        sim_timestamp,
        expected_duration_hours=1,
        elapsed_hours=0.0,
        **kwargs,
    ):
        decision = orig(
            policy_obj,
            intensity_lookup_,
            grids,
            current_grid,
            sim_timestamp,
            expected_duration_hours,
            elapsed_hours=elapsed_hours,
            **kwargs,
        )
        should_migrate, target = decision
        if should_migrate and target:
            events.append({
                "hour": int(elapsed_hours),
                "source_grid": current_grid,
                "target_grid": target,
            })
        return decision

    sc._simulate_policy_decision = wrapped
    try:
        out = simulate_one_run(intensity_lookup, cfg)
    finally:
        sc._simulate_policy_decision = orig

    # Self-consistency: events list MUST align with the sim's own bookkeeping.
    # If either assertion fires, sim-core drift has occurred — surface loudly.
    assert len(events) == out["migration_count"], (
        f"[BREAKDOWN] events={len(events)} != migration_count="
        f"{out['migration_count']} for cfg={cfg}"
    )
    assert [e["target_grid"] for e in events] == list(out["dest_grids_visited"]), (
        f"[BREAKDOWN] events targets={[e['target_grid'] for e in events]} "
        f"!= dest_grids_visited={out['dest_grids_visited']} for cfg={cfg}"
    )

    out = dict(out)  # avoid mutating the sim's return value
    out["migration_events"] = events
    return out


def synthesize_phase_durations(
    src_hw,
    dst_hw,
    app_size_mb: float,
    total_min: float,
) -> Tuple[float, float, float]:
    """Return ``(ckpt_min, send_min, restore_min)`` summing to ``total_min``.

    Uses the *original* (unpatched) helpers from ``heuristics.overhead`` to
    compute baseline ckpt:send:restore ratios at ``app_size_mb`` for the given
    source/destination hardware, then scales proportionally so the three
    phases sum to exactly ``total_min``.

    Args:
        src_hw: ``HardwareSpec`` for the migration source grid.
        dst_hw: ``HardwareSpec`` for the migration destination grid.
        app_size_mb: Application checkpoint size in MB.
        total_min: Target total migration duration in minutes (e.g. 30).

    Returns:
        ``(ckpt_min, send_min, restore_min)`` — three positive floats summing
        to ``total_min`` (within fp tolerance). On degenerate input
        (``total_base <= 0``) returns equal thirds as a safe fallback.
    """
    ckpt_base_s = ckpt_overhead(app_size_mb, src_hw)
    send_base_s = send_overhead(src_hw, dst_hw, app_size_mb)
    rest_base_s = restore_overhead(app_size_mb, dst_hw)
    total_base_s = ckpt_base_s + send_base_s + rest_base_s
    if total_base_s <= 0.0:
        # Degenerate: split evenly so caller still sees positive phases.
        third = total_min / 3.0
        return (third, third, third)
    # Scale (baseline-seconds) -> (target-minutes): the ratio of seconds is
    # preserved, total is forced to ``total_min``.
    scale = total_min / total_base_s
    return (
        ckpt_base_s * scale,
        send_base_s * scale,
        rest_base_s * scale,
    )


# ── Task 2: Per-cell plotter, CLI, and CSV writer ────────────────────

def build_full_lookup(
    regions_root: Path = DEFAULT_REGIONS_TREE_DIR,
    allowed_grids: Tuple[str, ...] = ("BANC", "CISO"),
) -> Dict[Tuple[str, int], float]:
    """Load the full ``{(grid, ts): intensity}`` lookup for the given grids.

    Mirrors the loader call pattern from
    ``sweep_overhead_crossover._run_pairwise_mode`` (line ~1378). Default to
    just BANC and CISO since the LOCKED scope is the BANC↔CISO pair.
    """
    return build_intensity_lookup_from_regions_tree(
        Path(regions_root), allowed_grids=tuple(sorted(allowed_grids)),
    )


def reconstruct_state_segments(
    events: List[Dict[str, Any]],
    total_hours: int,
    source_grid: str,
    overhead_min: float,
    hw_table: Dict[str, Any],
    app_size_mb: float,
) -> List[Tuple[float, float, str]]:
    """Reconstruct per-hour state into a list of ``(x_start, x_end, color_key)`` segments.

    Algorithm:
      - Walk hours ``0..total_hours-1`` tracking ``current_grid``.
      - Hour h with no migration event: one segment
        ``(h, h+1, "grid_<current>")``.
      - Hour h with a migration event (overhead <= 60 min): split the hour
        into four sub-segments —
          1. ``(h, h + t_pre, "grid_<source>")`` running on source pre-migration
          2. ``(h + t_pre, h + t_pre + t_ck, "ckpt")``
          3. ``(h + t_pre + t_ck, h + t_pre + t_ck + t_sn, "send")``
          4. ``(h + t_pre + t_ck + t_sn, h + 1, "restore")``
        For the locked 30-min overhead, ``t_pre = 0.5`` and the remaining
        0.5 h splits proportionally per ``synthesize_phase_durations``.
      - After migration, ``current_grid = target_grid`` for subsequent hours.

    For ``overhead_min > 60`` the migration phases would spill into hours
    h+1, h+2, ... This case is NOT exercised by the locked 30-min overhead;
    we implement it for forward-compatibility by laying the three phases
    contiguously on the time axis starting at the decision hour and filling
    any trailing remainder of the migration-end hour with the destination
    grid.
    """
    # Index events by their decision hour for O(1) lookup.
    event_by_hour: Dict[int, Dict[str, Any]] = {e["hour"]: e for e in events}

    segments: List[Tuple[float, float, str]] = []
    current_grid = source_grid

    h = 0
    while h < total_hours:
        if h not in event_by_hour:
            segments.append((float(h), float(h + 1), f"grid_{current_grid}"))
            h += 1
            continue

        evt = event_by_hour[h]
        src_grid_h = evt["source_grid"]
        dst_grid_h = evt["target_grid"]
        # Defensive: the captured source_grid at decision time should equal
        # the local current_grid we've been tracking. If not, the events
        # cannot represent a valid hour-by-hour trace.
        if src_grid_h != current_grid:
            raise AssertionError(
                f"[BREAKDOWN] event source_grid={src_grid_h!r} != tracked "
                f"current_grid={current_grid!r} at hour {h}; event list "
                f"inconsistent with hour-by-hour state reconstruction."
            )

        ck_min, sn_min, rs_min = synthesize_phase_durations(
            hw_table[src_grid_h], hw_table[dst_grid_h],
            app_size_mb, float(overhead_min),
        )
        # Convert minutes to fractional hours within the hour-axis.
        ck_h = ck_min / 60.0
        sn_h = sn_min / 60.0
        rs_h = rs_min / 60.0
        total_h = ck_h + sn_h + rs_h  # equals overhead_min/60.0

        if overhead_min <= 60.0:
            # Sub-hour migration: hour h has [pre-run on src | ck | sn | rs]
            # filling the 60-min window.
            t_pre = 1.0 - total_h  # >= 0 for overhead <= 60
            t0 = float(h)
            t1 = t0 + t_pre
            t2 = t1 + ck_h
            t3 = t2 + sn_h
            t4 = t3 + rs_h  # equals h + 1
            if t_pre > 0.0:
                segments.append((t0, t1, f"grid_{src_grid_h}"))
            segments.append((t1, t2, "ckpt"))
            segments.append((t2, t3, "send"))
            segments.append((t3, t4, "restore"))
            current_grid = dst_grid_h
            h += 1
        else:
            # Multi-hour migration (forward-compat path; NOT exercised by the
            # locked 30-min overhead). Migration starts immediately at the
            # decision hour and spans ``total_h`` hours; the destination grid
            # fills the remainder of the migration-end hour. Subsequent
            # full hours run on the destination grid.
            t0 = float(h)
            t1 = t0 + ck_h
            t2 = t1 + sn_h
            t3 = t2 + rs_h
            segments.append((t0, t1, "ckpt"))
            segments.append((t1, t2, "send"))
            segments.append((t2, t3, "restore"))
            current_grid = dst_grid_h
            # Determine how many full hours have elapsed since hour h.
            consumed_full_hours = int(t3) - h  # floor(t3) - h
            frac_end = t3 - (h + consumed_full_hours)
            if frac_end > 0.0:
                # Mid-hour remainder of the migration-end hour: destination.
                segments.append((
                    h + consumed_full_hours + frac_end,
                    float(h + consumed_full_hours + 1),
                    f"grid_{current_grid}",
                ))
                h += consumed_full_hours + 1
            else:
                h += consumed_full_hours

    return segments


def plot_one_cell(
    direction: Tuple[str, str],
    start_ts: int,
    policies: Tuple[int, ...],
    overhead_min: int,
    full_lookup: Dict[Tuple[str, int], float],
    out_dir: Path,
    app_size_mb: float,
    dpi: int,
    total_sim_hours: Optional[int] = None,
) -> Tuple[Path, List[Dict[str, Any]]]:
    """Run the per-policy sims for one (direction, start_ts) cell, render PNG.

    260512-kfc: ``total_sim_hours`` is now optional and used only as a plot
    x-axis overhead. When omitted (default), the x-axis upper bound is computed
    from ``max(out["completed_hours"] for out in all_policy_outs)`` so policies
    that extend past 48 hours (because they migrated and migration minutes no
    longer count toward useful completion) are NOT visually truncated. Each
    policy's swimlane is rendered out to its own ``completed_hours`` so the
    Gantt chart visibly shows different end times per policy.

    Returns:
        (png_path, rows) where ``rows`` is a list of dicts (one per policy)
        suitable for appending to ``runs_summary.csv``.
    """
    # Local matplotlib import keeps Task 1's data-producing core import-free
    # of mpl unless plotting is actually requested.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Patch

    src_grid, dst_grid = direction
    pair_lookup = _build_two_grid_lookup(full_lookup, src_grid, dst_grid)

    iso_date = datetime.fromtimestamp(start_ts, tz=timezone.utc).date().isoformat()

    fig, ax = plt.subplots(figsize=(12, 9), dpi=dpi)

    rows: List[Dict[str, Any]] = []

    # 260512-kfc: run ALL policy sims first so we can compute the max
    # completed_hours and size the x-axis to fit the longest swimlane.
    policy_outs: List[Dict[str, Any]] = []
    for p in policies:
        cfg = RunConfig(
            start_ts=start_ts,
            source_grid=src_grid,
            policy_id=p,
            app_size_mb=app_size_mb,
            expected_migration_min=int(overhead_min),
            use_hw=True,
            # 260513-dkb: 10x cap matches the sweep harness so Gantt plots can
            # render high-overhead policies that would otherwise hit the default
            # 2x cap (96h).
            max_wall_clock_multiplier=10.0,
            sweep_kind="runtime_breakdown",
        )
        out = simulate_with_decisions(pair_lookup, cfg)
        policy_outs.append(out)

    # 260512-kfc: derive plot x-axis from longest policy. If caller passed an
    # explicit total_sim_hours (legacy), use max(explicit, observed) so legacy
    # callers don't shrink the axis below what's actually needed.
    observed_max = max(out["completed_hours"] for out in policy_outs)
    if total_sim_hours is None:
        plot_hours = int(observed_max)
    else:
        plot_hours = max(int(total_sim_hours), int(observed_max))

    for p, out in zip(policies, policy_outs):
        # Render each policy's swimlane out to ITS OWN completed_hours so the
        # Gantt chart visibly distinguishes policies that took longer (because
        # migration minutes extended their wall-clock duration).
        policy_hours = int(out["completed_hours"])
        segments = reconstruct_state_segments(
            events=out["migration_events"],
            total_hours=policy_hours,
            source_grid=src_grid,
            overhead_min=float(overhead_min),
            hw_table=HW_TABLE,
            app_size_mb=app_size_mb,
        )

        y_idx = policies.index(p)  # 0..len(policies)-1, top-down via invert
        for x0, x1, key in segments:
            ax.add_patch(Rectangle(
                (x0, y_idx - 0.4),
                x1 - x0,
                0.8,
                facecolor=COLOR_MAP[key],
                edgecolor="none",
            ))

        # Right-edge annotation anchored to the SHARED plot edge so all
        # annotations line up vertically. Include hours_tracked so the
        # variable-end-time effect is also reported numerically.
        ax.text(
            plot_hours + 0.3,
            y_idx,
            f"{out['total_carbon_gco2']:.0f} gCO2 · "
            f"{out['migration_count']} migr · "
            f"{policy_hours}h",
            va="center", ha="left", fontsize=9,
        )

        # CSV row for this run.
        mig_hours = "|".join(str(e["hour"]) for e in out["migration_events"])
        dest_grids = "|".join(out["dest_grids_visited"])
        rows.append({
            "direction": f"{src_grid}-{dst_grid}",
            "start_ts_iso": iso_date,
            "start_ts_unix": start_ts,
            "policy": p,
            "overhead_min": overhead_min,
            "app_size_mb": app_size_mb,
            "total_carbon_gco2": out["total_carbon_gco2"],
            "migration_count": out["migration_count"],
            "migration_hours": mig_hours,
            "dest_grids_visited": dest_grids,
        })

    # Axes formatting. 260512-kfc: x-axis upper bound from observed/explicit max.
    ax.set_xlim(0, plot_hours + 6)  # leave right margin for annotations
    ax.set_xlabel(f"hour of {plot_hours}-hour simulation (wall-clock; "
                  f"variable per policy under 260512-kfc useful-work termination)")
    ax.set_yticks(list(range(len(policies))))
    ax.set_yticklabels([f"P{p}" for p in policies])
    ax.invert_yaxis()  # P1 at top, P6 at bottom
    ax.set_ylim(len(policies) - 0.5, -0.5)
    ax.grid(True, axis="x", linestyle=":", alpha=0.35)
    ax.set_axisbelow(True)

    # Title + subtitle.
    title_main = (
        f"Runtime breakdown — {src_grid}→{dst_grid}, start {iso_date} UTC, "
        f"overhead={overhead_min} min, app={app_size_mb} MB"
    )
    ax.set_title(title_main, fontsize=12, pad=12)
    # Subtitle as a fig.text just below the axes title (anchored to fig).
    fig.text(
        0.5, 0.92,
        SUBTITLE_LOCKED,
        ha="center", va="bottom", fontsize=9, style="italic", color="#444",
    )

    # Shared legend across all 5 categories.
    legend_handles = [
        Patch(facecolor=COLOR_MAP["grid_BANC"], label="running on BANC"),
        Patch(facecolor=COLOR_MAP["grid_CISO"], label="running on CISO"),
        Patch(facecolor=COLOR_MAP["ckpt"],      label="checkpoint"),
        Patch(facecolor=COLOR_MAP["send"],      label="send"),
        Patch(facecolor=COLOR_MAP["restore"],   label="restore"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=5,
        frameon=False,
        bbox_to_anchor=(0.5, 0.01),
    )

    # Leave room for the subtitle (top) and legend (bottom).
    fig.subplots_adjust(top=0.88, bottom=0.10)

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{overhead_min}min_{iso_date}_{src_grid}-{dst_grid}.png"
    # ``metadata={"Software": "matplotlib"}`` keeps PNG metadata
    # version-independent (some matplotlib versions embed a timestamp in the
    # default metadata).
    fig.savefig(
        png_path,
        dpi=dpi,
        bbox_inches="tight",
        metadata={"Software": "matplotlib"},
    )
    plt.close(fig)
    return png_path, rows


def write_runs_summary(rows: List[Dict[str, Any]], csv_path: Path) -> None:
    """Emit the locked-schema ``runs_summary.csv`` at ``csv_path``."""
    header = [
        "direction", "start_ts_iso", "start_ts_unix", "policy", "overhead_min",
        "app_size_mb", "total_carbon_gco2", "migration_count",
        "migration_hours", "dest_grids_visited",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in header})


# ── CLI ──────────────────────────────────────────────────────────────

def _parse_starts(arg: Optional[str]) -> Tuple[int, ...]:
    """Parse ``--starts`` either as comma-separated ISO dates or quarter aliases.

    Default (None) returns the 4 seasonal anchor timestamps.
    """
    if arg is None:
        return SEASONAL_STARTS_2020
    raw = [tok.strip() for tok in arg.split(",") if tok.strip()]
    if not raw:
        return SEASONAL_STARTS_2020
    out: List[int] = []
    aliases = {
        "JAN": 0, "Q1": 0,
        "APR": 1, "Q2": 1,
        "JUL": 2, "Q3": 2,
        "OCT": 3, "Q4": 3,
    }
    for tok in raw:
        upper = tok.upper()
        if upper in aliases:
            out.append(SEASONAL_STARTS_2020[aliases[upper]])
            continue
        # Try ISO date YYYY-MM-DD.
        try:
            dt = datetime.fromisoformat(tok).replace(tzinfo=timezone.utc)
            out.append(int(dt.timestamp()))
        except ValueError:
            raise SystemExit(
                f"[BREAKDOWN] bad --starts token {tok!r}; expected one of "
                f"{{JAN,APR,JUL,OCT,Q1..Q4}} or ISO date YYYY-MM-DD"
            )
    return tuple(out)


def _parse_pairs(arg: Optional[str]) -> Tuple[Tuple[str, str], ...]:
    """Parse ``--pair SRC:DST,SRC:DST`` (default: BANC↔CISO bidirectional)."""
    if arg is None:
        return DIRECTIONAL_PAIRS
    pairs: List[Tuple[str, str]] = []
    for tok in arg.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            s, d = tok.split(":")
        except ValueError:
            raise SystemExit(
                f"[BREAKDOWN] bad --pair token {tok!r}; expected SRC:DST"
            )
        pairs.append((s, d))
    if not pairs:
        return DIRECTIONAL_PAIRS
    return tuple(pairs)


def _parse_policies(arg: Optional[str]) -> Tuple[int, ...]:
    """Parse ``--policies 1,2,3,4,5,6`` (default: all 6)."""
    if arg is None:
        return POLICIES_DEFAULT
    raw = [tok.strip() for tok in arg.split(",") if tok.strip()]
    try:
        out = tuple(int(t) for t in raw)
    except ValueError:
        raise SystemExit(
            f"[BREAKDOWN] --policies must be integers (got {raw!r})"
        )
    bad = [p for p in out if p not in VALID_POLICY_IDS]
    if bad:
        raise SystemExit(
            f"[BREAKDOWN] unknown policy ids {bad}; valid: "
            f"{sorted(VALID_POLICY_IDS)}"
        )
    if len(set(out)) != len(out):
        raise SystemExit(f"[BREAKDOWN] --policies contains duplicates: {out}")
    return out


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Gantt-style runtime-breakdown plot per policy "
                    "(quick task 260512-j87).",
    )
    p.add_argument(
        "--starts", default=None,
        help="Comma-separated ISO dates or quarter aliases "
             "(JAN,APR,JUL,OCT). Default: all 4 seasonal anchors.",
    )
    p.add_argument(
        "--all-seasonal", action="store_true",
        help="Alias for the default 4-seasonal-anchor start set.",
    )
    p.add_argument(
        "--overhead", type=int, default=OVERHEAD_MIN_DEFAULT,
        help=f"Migration overhead in minutes (default: "
             f"{OVERHEAD_MIN_DEFAULT}).",
    )
    p.add_argument(
        "--pair", default=None,
        help="Comma-separated SRC:DST directional pairs "
             "(default: BANC:CISO,CISO:BANC).",
    )
    p.add_argument(
        "--policies", default=None,
        help="Comma-separated policy ids "
             "(default: 1,2,3,4,5,6).",
    )
    p.add_argument(
        "--out-dir", default=str(OUT_DIR_DEFAULT),
        help=f"Output directory (default: {OUT_DIR_DEFAULT}).",
    )
    p.add_argument(
        "--app-size-mb", type=float, default=ANCHOR_APP_SIZE_MB,
        help=f"Application checkpoint size in MB (default: "
             f"{ANCHOR_APP_SIZE_MB}).",
    )
    p.add_argument(
        "--dpi", type=int, default=100,
        help="Figure DPI (default: 100 → 1200x900).",
    )
    p.add_argument(
        "--smoke-only", action="store_true",
        help="Run the Task 1 smoke test only (no artifacts produced).",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    if args.smoke_only:
        _smoke_test()
        return 0

    starts = _parse_starts(args.starts)
    pairs = _parse_pairs(args.pair)
    policies = _parse_policies(args.policies)
    overhead_min = int(args.overhead)
    out_dir = Path(args.out_dir)
    app_size_mb = float(args.app_size_mb)
    dpi = int(args.dpi)

    print(
        f"[BREAKDOWN] starts={[datetime.fromtimestamp(s, tz=timezone.utc).date().isoformat() for s in starts]}\n"
        f"[BREAKDOWN] pairs={list(pairs)}\n"
        f"[BREAKDOWN] policies={list(policies)}\n"
        f"[BREAKDOWN] overhead_min={overhead_min}\n"
        f"[BREAKDOWN] app_size_mb={app_size_mb}\n"
        f"[BREAKDOWN] out_dir={out_dir}"
    )

    t0 = time.time()
    # Resolve the union of grids referenced by --pair so the loader picks
    # up exactly the CSVs needed.
    pair_grids = tuple(sorted({g for pair in pairs for g in pair}))
    full_lookup = build_full_lookup(
        regions_root=DEFAULT_REGIONS_TREE_DIR,
        allowed_grids=pair_grids,
    )
    print(
        f"[BREAKDOWN] full_lookup loaded: {len(full_lookup)} (grid, ts) "
        f"entries across {pair_grids}"
    )

    all_rows: List[Dict[str, Any]] = []
    n_pngs = 0
    for direction in pairs:
        for start_ts in starts:
            png_path, rows = plot_one_cell(
                direction=direction,
                start_ts=start_ts,
                policies=policies,
                overhead_min=overhead_min,
                full_lookup=full_lookup,
                out_dir=out_dir,
                app_size_mb=app_size_mb,
                dpi=dpi,
            )
            all_rows.extend(rows)
            n_pngs += 1
            iso_date = datetime.fromtimestamp(
                start_ts, tz=timezone.utc,
            ).date().isoformat()
            print(
                f"[BREAKDOWN] {iso_date} {direction[0]}→{direction[1]} → "
                f"{png_path} ({len(rows)} sims)"
            )

    csv_path = out_dir / "runs_summary.csv"
    write_runs_summary(all_rows, csv_path)
    elapsed = time.time() - t0
    print(
        f"[BREAKDOWN] Done. {n_pngs} PNGs + runs_summary.csv at {out_dir} "
        f"(wall={elapsed:.2f}s, total sims={len(all_rows)})"
    )
    return 0


# ── Smoke test (Task 1 acceptance) ───────────────────────────────────

def _smoke_test() -> None:
    """Task 1 smoke test: exercise simulate_with_decisions + synthesize_phase_durations.

    Run a single ``simulate_with_decisions`` for (start_ts=Jan 16, source=CISO,
    policy_id=2) with the BANC↔CISO two-grid lookup and assert the documented
    invariants. Print the events list and totals so the developer can
    eyeball-verify before Task 2.
    """
    print("[SMOKE] Loading full BANC+CISO intensity lookup...")
    full = build_intensity_lookup_from_regions_tree(
        Path(DEFAULT_REGIONS_TREE_DIR), allowed_grids=("BANC", "CISO"),
    )
    pair = _build_two_grid_lookup(full, "CISO", "BANC")
    cfg = RunConfig(
        start_ts=SEASONAL_STARTS_2020[0],  # 2020-01-16 00:00 UTC
        source_grid="CISO",
        policy_id=2,
        app_size_mb=ANCHOR_APP_SIZE_MB,
        expected_migration_min=OVERHEAD_MIN_DEFAULT,
        use_hw=True,
        # 260513-dkb: 10x cap matches the main runner.
        max_wall_clock_multiplier=10.0,
        sweep_kind="runtime_breakdown_smoke",
    )
    print(f"[SMOKE] simulate_with_decisions(cfg={cfg})")
    out = simulate_with_decisions(pair, cfg)

    assert out["migration_count"] > 0, (
        "[SMOKE] P2 CISO→BANC at Jan 16 should produce migrations; "
        f"got migration_count={out['migration_count']}"
    )
    assert len(out["migration_events"]) == out["migration_count"]
    for e in out["migration_events"]:
        assert e["target_grid"] in {"BANC", "CISO"}, (
            f"[SMOKE] bad target_grid in event {e}"
        )
        assert 0 <= e["hour"] < 48, f"[SMOKE] hour out of range in event {e}"

    ck, sn, rs = synthesize_phase_durations(
        HW_TABLE["CISO"], HW_TABLE["BANC"],
        ANCHOR_APP_SIZE_MB, float(OVERHEAD_MIN_DEFAULT),
    )
    assert ck > 0 and sn > 0 and rs > 0, (
        f"[SMOKE] phases must all be positive; got ({ck}, {sn}, {rs})"
    )
    assert abs((ck + sn + rs) - OVERHEAD_MIN_DEFAULT) < 1e-9, (
        f"[SMOKE] phases must sum to {OVERHEAD_MIN_DEFAULT}; "
        f"got ck={ck} sn={sn} rs={rs} sum={ck+sn+rs}"
    )

    print(f"[SMOKE] migration_count = {out['migration_count']}")
    print(f"[SMOKE] migration_events = {out['migration_events']}")
    print(f"[SMOKE] dest_grids_visited = {out['dest_grids_visited']}")
    print(f"[SMOKE] total_carbon_gco2 = {out['total_carbon_gco2']}")
    print(
        f"[SMOKE] phase_durations(CISO->BANC, 64MB, 30min): "
        f"ckpt={ck:.4f} min  send={sn:.4f} min  restore={rs:.4f} min  "
        f"sum={ck+sn+rs:.6f} min"
    )
    print("[SMOKE] all Task 1 assertions PASSED.")


if __name__ == "__main__":
    # Default (no args): run the full 8-PNG batch. ``--smoke-only`` runs the
    # Task 1 smoke test only.
    sys.exit(main(sys.argv[1:]))
