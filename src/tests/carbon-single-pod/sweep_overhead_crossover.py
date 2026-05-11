#!/usr/bin/env python3
"""Policy 2 vs Policy 6 BANC<->CISO overhead-crossover sweep (quick task 260511-jce, extends 260511-gnm).

This is a one-shot orchestrator that answers the thesis question:
    "At what migration overhead does the naive always-migrate-to-best policy
    (Policy 2) start to beat the heuristic (Policy 6)?"

The default sweep is now BANC<->CISO **directional**: both grids are CAL-region
neighbors with genuinely competitive carbon intensities, unlike the prior
ISNE->SCL pair (260511-gnm) where SCL was ~44x cleaner so Policy 6 migrated
regardless of overhead. The combination of (a) the minute-granular sim-core
(260511-jce) and (b) a competitive grid pair yields a well-posed crossover
question. See
``.planning/quick/260511-jce-extend-policy-2-vs-policy-6-overhead-swe/260511-jce-CONTEXT.md``
for the locked decisions.

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
restores the originals on exit.

Outputs (under ``data/quick/260511-jce-banc-ciso-overhead-crossover/``):
  - ``curves.csv``           -- long-format per-run results (one row per
                                (overhead, direction, policy, start_ts)).
  - ``curves.png``           -- two-subplot mean-carbon-vs-overhead line plot
                                (BANC->CISO and CISO->BANC).
  - ``crossover_summary.md`` -- per-direction crossover value (or "no crossover
                                in swept range") plus methodology + per-overhead
                                carbon + mig_count table.

Reference: .planning/quick/260511-jce-extend-policy-2-vs-policy-6-overhead-swe/260511-jce-CONTEXT.md
"""

import argparse
import csv
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

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
from evaluation_plots import POLICY_COLORS  # noqa: E402

# Module references whose *bound* symbols we will patch / read.
from heuristics import policy_heuristic as ph  # noqa: E402
from heuristics import overhead as oh_mod  # noqa: E402


# ── Constants (LOCKED by CONTEXT.md) ─────────────────────────────────

# 13-value grid up to 360 min (260511-jce locked). Denser at the low end where
# crossovers are likely; coarser past 60 min where multi-hour overhead regimes
# only matter qualitatively.
OVERHEAD_GRID_MIN = (0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360)
POLICIES = (2, 6)
OUT_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "quick" / "260511-jce-banc-ciso-overhead-crossover"
)
# BANC and CISO are both CAL-region grids with competitive carbon intensities;
# the directional pairs let us answer the crossover question in both
# directions on a single sweep run.
DIRECTIONAL_PAIRS = (("BANC", "CISO"), ("CISO", "BANC"))  # LOCKED
ANCHOR_APP_SIZE_MB = 64.0  # canonical app size used for the baseline anchor


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


def _resolve_timestamps(all_ts, num):
    """Sub-sample ``all_ts`` to roughly ``num`` evenly-spaced timestamps."""
    if num <= 0:
        raise SystemExit("[SWEEP] --num-timestamps must be >= 1")
    if num >= len(all_ts):
        return list(all_ts)
    step = max(1, len(all_ts) // num)
    return list(all_ts[::step])[:num]


def run_sweep(full_lookup, directional_pairs, timestamps, anchor_grid):
    """Execute the 13 x len(directional_pairs) x 2 x len(timestamps) cell sweep.

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
        policy_id=2,
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
        sweep_kind="overhead_crossover",
    )

    rows = []
    baseline_total_min_seen = None

    for m in OVERHEAD_GRID_MIN:
        # The scaled_overhead context manager patches Policy 6's bound
        # overhead helpers. Policy 2 doesn't call them, so the patch is a
        # no-op for Policy 2 runs -- Policy 2 only feels overhead via
        # cfg.expected_migration_min, which we set below.
        with scaled_overhead(float(m), anchor_grid) as so:
            baseline_total_min_seen = so.baseline_total_min  # constant across m
            print(
                f"[PATCH] overhead_min={m:>3d} scale={so.scale:.4f} "
                f"(baseline={so.baseline_total_min:.3f} min, anchor={anchor_grid})"
            )
            for src, dst in directional_pairs:
                pair_lookup = _build_two_grid_lookup(full_lookup, src, dst)
                for ts in timestamps:
                    for p in POLICIES:
                        cfg = replace(
                            template,
                            start_ts=ts,
                            source_grid=src,
                            policy_id=p,
                            expected_migration_min=int(m),
                        )
                        out = simulate_one_run(pair_lookup, cfg)
                        rows.append({
                            "overhead_min": m,
                            "policy": p,
                            "source_grid": src,
                            "dest_grid": dst,
                            "start_ts": ts,
                            "total_carbon_gco2": out["total_carbon_gco2"],
                            "baseline_carbon_gco2": out["baseline_carbon_gco2"],
                            "migration_count": out["migration_count"],
                        })

    return rows, baseline_total_min_seen if baseline_total_min_seen is not None else 0.0


# ── Aggregation & crossover detection ────────────────────────────────

def per_cell_means(rows):
    """Return (p2_means, p6_means) lists indexed by OVERHEAD_GRID_MIN.

    Each value is the mean ``total_carbon_gco2`` across samples for that
    (overhead, policy) cell. ``float('nan')`` when no samples exist.

    Kept for backward compatibility; the 260511-jce sweep uses
    :func:`per_cell_means_by_direction` which preserves the (source, dest)
    dimension.
    """
    p2_means, p6_means = [], []
    for m in OVERHEAD_GRID_MIN:
        v2 = [r["total_carbon_gco2"] for r in rows
              if r["overhead_min"] == m and r["policy"] == 2]
        v6 = [r["total_carbon_gco2"] for r in rows
              if r["overhead_min"] == m and r["policy"] == 6]
        p2_means.append(mean(v2) if v2 else float("nan"))
        p6_means.append(mean(v6) if v6 else float("nan"))
    return p2_means, p6_means


def per_cell_means_by_direction(rows, directional_pairs):
    """Return per-(src, dst) total-carbon and migration-count mean dicts.

    Output structure::

        carbon[(src, dst)][policy_id] -> list aligned to OVERHEAD_GRID_MIN
        mig_count[(src, dst)][policy_id] -> list aligned to OVERHEAD_GRID_MIN

    Where each list element is the mean across the per-timestamp samples for
    that (overhead, direction, policy) cell. NaN when no samples exist.
    """
    out_carbon = {pair: {p: [] for p in POLICIES} for pair in directional_pairs}
    out_mig = {pair: {p: [] for p in POLICIES} for pair in directional_pairs}
    for m in OVERHEAD_GRID_MIN:
        for src, dst in directional_pairs:
            for p in POLICIES:
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


def find_crossover(p2_means, p6_means):
    """Locate the first overhead at which Policy 2 stops being worse than Policy 6.

    Definition: ``diff[i] = P2[i] - P6[i]``. Positive means Policy 2 is worse.
    Crossover is the smallest ``i >= 1`` where ``sign(diff[i-1]) != sign(diff[i])``
    AND ``diff[i] <= 0`` (P2 now equal or better). Linear interpolation between
    the bracketing grid points gives the crossover minute, rounded to 0.1.

    Returns:
        Tuple[Optional[float], Optional[int]] -- (crossover_min, i) where i is
        the right-side grid index used. Both are None when no crossover exists
        in the swept range.
    """
    diff = [p2 - p6 for p2, p6 in zip(p2_means, p6_means)]
    for i in range(1, len(OVERHEAD_GRID_MIN)):
        y0, y1 = diff[i - 1], diff[i]
        # Sign-change AND P2 now wins-or-ties.
        if (y0 > 0 and y1 <= 0):
            x0, x1 = OVERHEAD_GRID_MIN[i - 1], OVERHEAD_GRID_MIN[i]
            if y1 == y0:
                # Degenerate flat segment; skip this segment, keep scanning.
                continue
            x_cross = x0 - y0 * (x1 - x0) / (y1 - y0)
            return round(x_cross, 1), i
    return None, None


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


def write_plot(carbon_by_dir, crossovers_by_dir, directional_pairs,
               timestamps, path):
    """Two-subplot figure: one direction per axes.

    Each subplot shows mean total carbon vs migration overhead for Policy 2
    and Policy 6, with the per-direction crossover annotated (when present).
    """
    fig, axes = plt.subplots(
        1, len(directional_pairs), figsize=(14, 6), sharey=True
    )
    if len(directional_pairs) == 1:
        axes = [axes]
    for ax, pair in zip(axes, directional_pairs):
        src, dst = pair
        p2_means = carbon_by_dir[pair][2]
        p6_means = carbon_by_dir[pair][6]
        ax.plot(
            OVERHEAD_GRID_MIN, p2_means,
            marker="o", linewidth=1.8, color=POLICY_COLORS[2],
            label="Policy 2 (always-best)",
        )
        ax.plot(
            OVERHEAD_GRID_MIN, p6_means,
            marker="o", linewidth=1.8, color=POLICY_COLORS[6],
            label="Policy 6 (heuristic)",
        )
        cross = crossovers_by_dir.get(pair)
        if cross is not None:
            cm, _idx = cross
            ax.axvline(x=cm, linestyle="--", color="gray", linewidth=1.0)
            y_top = max(
                max(v for v in p2_means if v == v),
                max(v for v in p6_means if v == v),
            )
            ax.text(
                cm, y_top, f" crossover ~ {cm:g} min",
                color="gray", va="top", ha="left",
            )
        ax.set_title(f"{src} -> {dst}")
        ax.set_xlabel("Migration overhead (minutes)")
        ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.6)
        ax.legend(loc="lower left")
    axes[0].set_ylabel("Mean total carbon (gCO2eq, HW-scaled)")
    fig.suptitle(
        "Policy 2 vs Policy 6 -- carbon vs migration overhead "
        "(BANC<->CISO, linked knob)"
    )
    fig.text(
        0.99, 0.02,
        f"{len(timestamps)} starts; 48 h jobs; --use-hw",
        ha="right", va="bottom", fontsize=8, color="dimgray",
    )
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
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
    path, crossovers_by_dir, carbon_by_dir, mig_count_by_dir,
    directional_pairs, baseline_total_min, anchor_grid, timestamps,
):
    """Render the per-direction crossover summary markdown.

    For each directional pair, emit:
      - The crossover overhead (interpolated to 0.1 min) or "none in [0, 360]".
      - A per-overhead table of (P2 carbon, P6 carbon, diff, P2 mig_count,
        P6 mig_count) so the user can sanity-check the linked-knob effect
        on Policy 6's migration count.
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = _git_short_sha()

    md = [
        "# Policy 2 vs Policy 6 -- BANC<->CISO Overhead Crossover",
        "",
        "**Quick task:** 260511-jce",
        f"**Generated:** {now_iso}",
        f"**Git SHA:** {sha}",
        "",
        "## Sim-core formula (260511-jce)",
        "",
        "Migration carbon at decision hour: "
        "`(expected_migration_min / 60) * source_intensity_at_h` "
        "(HW-scaled iff `use_hw=True`).",
        "Cooldown: `max(0, ceil((expected_migration_min - 60) / 60))` hours.",
        "During cooldown, intensity accumulates on the target grid.",
        "",
        "## Methodology",
        "",
        "- Linked-knob sweep: `expected_migration_min` AND Policy 6's bound "
        "overhead helpers "
        "(`ckpt_overhead`/`send_overhead`/`restore_overhead` in "
        "`heuristics.policy_heuristic`) scaled by "
        "`target_minutes / baseline_total_min`.",
        f"- Baseline total: `{baseline_total_min:.3f}` min "
        f"(linear fit at {ANCHOR_APP_SIZE_MB:g} MB, anchor `{anchor_grid}`).",
        f"- Grid: {list(OVERHEAD_GRID_MIN)}",
        f"- Samples: {len(timestamps)} 2020 hourly starts per direction.",
        f"- Directions: {[f'{s}->{d}' for s, d in directional_pairs]}",
        "- Settings: app_size_mb=64, expected_completion_min=2880 (48 h), "
        "use_hw=True.",
        "",
    ]

    for pair in directional_pairs:
        src, dst = pair
        cross = crossovers_by_dir.get(pair)
        md.append(f"## {src} -> {dst}")
        md.append("")
        if cross is None:
            md.append(
                f"**Crossover:** none in swept range "
                f"[0, {OVERHEAD_GRID_MIN[-1]}] min for this direction."
            )
        else:
            cm, idx = cross
            x0, x1 = OVERHEAD_GRID_MIN[idx - 1], OVERHEAD_GRID_MIN[idx]
            md.append(
                f"**Crossover:** Policy 2 beats Policy 6 at overhead >= "
                f"{cm} min (interpolated between {x0} and {x1} min)."
            )
        md.append("")
        md.append(
            "| overhead_min | P2 carbon | P6 carbon | P2 - P6 | "
            "P2 mig_count | P6 mig_count |"
        )
        md.append("| --- | --- | --- | --- | --- | --- |")
        c = carbon_by_dir[pair]
        mc = mig_count_by_dir[pair]
        for i, m in enumerate(OVERHEAD_GRID_MIN):
            md.append(
                f"| {m} | {c[2][i]:.1f} | {c[6][i]:.1f} | "
                f"{c[2][i] - c[6][i]:+.1f} | "
                f"{mc[2][i]:.2f} | {mc[6][i]:.2f} |"
            )
        md.append("")

    md.extend([
        "## Files",
        "",
        "- `curves.csv` -- long-format per-run results (one row per "
        "(overhead, direction, policy, start_ts)).",
        "- `curves.png` -- two-subplot P2 vs P6 line plot with per-direction "
        "crossover annotation.",
        "",
    ])

    with open(path, "w") as f:
        f.write("\n".join(md))


# ── CLI ───────────────────────────────────────────────────────────────

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Policy 2 vs Policy 6 BANC<->CISO overhead-crossover sweep "
                    "(260511-jce, extends 260511-gnm)"
    )
    p.add_argument("--regions-dir", default=None,
                   help="Override regions tree root (default: data/regions/)")
    p.add_argument("--pairs", nargs="+", default=None,
                   help="Directional pairs as SRC:DST tokens, e.g. BANC:CISO. "
                        "Default: BANC:CISO and CISO:BANC.")
    p.add_argument("--num-timestamps", type=int, default=24,
                   help="Number of sub-sampled 2020 hourly starts per direction "
                        "(default: 24)")
    p.add_argument("--smoke", action="store_true",
                   help="Smoke run with N=4 starts for <60 s sanity check")
    p.add_argument("--out-dir", default=None,
                   help="Override output directory")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    t0 = time.time()

    regions_root = Path(args.regions_dir) if args.regions_dir else DEFAULT_REGIONS_TREE_DIR
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
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

    # Resolve directional pairs (default BANC<->CISO bidirectional).
    directional_pairs = _resolve_directional_pairs(usable, args.pairs)
    # Anchor grid is one shared scalar for the linked-knob baseline. Prefer
    # BANC because it's an endpoint of both default pairs.
    pair_grids = tuple({g for pair in directional_pairs for g in pair})
    anchor_grid = _pick_anchor_grid(usable, preferred=("BANC", "CISO", "ISNE"))

    # Validate both pair endpoints are usable.
    missing = [g for g in pair_grids if g not in usable]
    if missing:
        print(
            f"[SWEEP] ERROR: directional pair endpoints {missing} not in "
            f"usable grid set ({usable})",
            file=sys.stderr,
        )
        return 1

    # Sub-sampled timestamps from Phase 4's main-sweep 2020 set.
    all_ts = _main_sweep_timestamps(2020)
    n = 4 if args.smoke else int(args.num_timestamps)
    timestamps = _resolve_timestamps(all_ts, n)

    print(
        f"[SWEEP] regions_root={regions_root}\n"
        f"[SWEEP] usable_grids={usable}\n"
        f"[SWEEP] directional_pairs={directional_pairs} anchor={anchor_grid}\n"
        f"[SWEEP] timestamps: {len(timestamps)} starts "
        f"(first={timestamps[0]}, last={timestamps[-1]})\n"
        f"[SWEEP] overhead_grid={list(OVERHEAD_GRID_MIN)} min\n"
        f"[SWEEP] policies={list(POLICIES)}\n"
        f"[SWEEP] out_dir={out_dir}"
    )

    # Build the intensity lookup once, restricted to the directional-pair
    # endpoints to keep memory small (D-23 enforced inside the helper).
    lookup = build_intensity_lookup_from_regions_tree(
        regions_root, allowed_grids=tuple(sorted(pair_grids)),
    )
    print(f"[SWEEP] intensity_lookup: {len(lookup)} (grid, ts) entries")

    rows, baseline_total_min = run_sweep(
        lookup, directional_pairs, timestamps, anchor_grid,
    )
    print(
        f"[SWEEP] completed {len(rows)} simulated runs in "
        f"{time.time() - t0:.2f} s"
    )

    carbon_by_dir, mig_count_by_dir = per_cell_means_by_direction(
        rows, directional_pairs,
    )
    crossovers_by_dir = {}
    for pair in directional_pairs:
        cm, idx = find_crossover(
            carbon_by_dir[pair][2], carbon_by_dir[pair][6],
        )
        if cm is None:
            crossovers_by_dir[pair] = None
        else:
            crossovers_by_dir[pair] = (cm, idx)

    # Write artifacts.
    csv_path = out_dir / "curves.csv"
    png_path = out_dir / "curves.png"
    md_path = out_dir / "crossover_summary.md"

    write_csv(rows, csv_path)
    print(f"[PLOT] wrote {csv_path}")
    write_plot(
        carbon_by_dir, crossovers_by_dir, directional_pairs,
        timestamps, png_path,
    )
    print(f"[PLOT] wrote {png_path}")
    write_summary_md(
        md_path, crossovers_by_dir, carbon_by_dir, mig_count_by_dir,
        directional_pairs, baseline_total_min, anchor_grid, timestamps,
    )
    print(f"[PLOT] wrote {md_path}")

    for pair in directional_pairs:
        cross = crossovers_by_dir.get(pair)
        src, dst = pair
        if cross is None:
            print(
                f"[SWEEP] RESULT {src}->{dst}: no crossover in swept range "
                f"[0, {OVERHEAD_GRID_MIN[-1]}] min."
            )
        else:
            cm, _idx = cross
            print(
                f"[SWEEP] RESULT {src}->{dst}: crossover at overhead ~ "
                f"{cm} min."
            )

    print(f"[SWEEP] total wall-clock: {time.time() - t0:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
