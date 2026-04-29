#!/usr/bin/env python3
"""
Phase 4 evaluation plotter.

Reads data/evaluation/run_<ts>/results.csv (D-18, D-19) and produces three
PNG files in the same directory:
  1. comparison.png — boxplot of savings_pct by policy across sweep_kind='main'
  2. ablation.png  — 8-cell heatmap of mean savings_pct for sweep_kind='ablation'
  3. horizon.png   — line plot of mean savings_pct vs lookahead_hours for
                     sweep_kind='horizon' (Policy 6 line + Policy 1-5 reference axhlines)

Usage:
    python3 evaluation_plots.py <run_directory>
    python3 evaluation_plots.py data/evaluation/run_20260428_193000/ --kind all
    python3 evaluation_plots.py data/evaluation/run_20260428_193000/ --kind ablation

Implements INFR-05 and EVAL-03. Pure transform/read-only — no imports
from the implementation modules (evaluate_policies, _simulation_core, policy classes).

Plot helpers (boxplot, heatmap) are copied VERBATIM from
.planning/phases/04-evaluation-harness-simulation-results/04-RESEARCH.md
lines 681-768; the line-plot helper is derived from D-15.
"""

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# Mirrored from RESEARCH.md lines 690-697 — extends graph_results.py's color
# choices (#FF9800, #4CAF50) with a per-policy 6-entry palette.
POLICY_COLORS = {
    1: "#9E9E9E",   # gray   — no-migration baseline
    2: "#FF9800",   # orange
    3: "#FFC107",   # amber
    4: "#03A9F4",   # light blue
    5: "#3F51B5",   # indigo
    6: "#4CAF50",   # green  — heuristic
}

# Mirrored from RESEARCH.md line 736-737 — 8-cell HEUR-10 ablation order.
# Tuple = (hw_weighting, overhead_cost, deadline_gate); 0=off, 1=on.
ABLATION_AXES = [(0, 0, 0), (0, 0, 1), (0, 1, 0), (0, 1, 1),
                 (1, 0, 0), (1, 0, 1), (1, 1, 0), (1, 1, 1)]

# D-13 / Plan 03 horizon sweep values.
HORIZON_VALUES = (1, 2, 4, 8, 12, 24, 48)


def load_results(path, sweep_kind=None):
    """Load results.csv into a list of dict rows, optionally filtered by sweep_kind.

    PATTERNS.md "CSV reader pattern". Returns the raw string-valued dicts;
    callers cast individual columns as needed.
    """
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if sweep_kind and r.get("sweep_kind") != sweep_kind:
                continue
            rows.append(r)
    return rows


def plot_savings_comparison(results_csv, out_path):
    """Boxplot of savings_pct by policy. VERBATIM from RESEARCH.md lines 699-727.

    [PLOT] tag log convention per CLAUDE.md.
    """
    by_policy = {p: [] for p in range(1, 7)}
    with open(results_csv) as f:
        for row in csv.DictReader(f):
            if row["sweep_kind"] != "main":
                continue
            by_policy[int(row["policy"])].append(float(row["savings_pct"]))

    if not any(by_policy[p] for p in range(1, 7)):
        print("[PLOT] No main rows found — skipping comparison.png", file=sys.stderr)
        return

    n_main = sum(len(by_policy[p]) for p in range(1, 7))

    fig, ax = plt.subplots(figsize=(10, 6))
    box = ax.boxplot(
        [by_policy[p] for p in range(1, 7)],
        labels=[f"P{p}" for p in range(1, 7)],
        patch_artist=True,
        showmeans=True, meanline=True,
        medianprops=dict(color="black", linewidth=1.5),
    )
    for patch, p in zip(box["boxes"], range(1, 7)):
        patch.set_facecolor(POLICY_COLORS[p])
        patch.set_alpha(0.7)

    ax.axhline(0, color="red", linestyle="--", alpha=0.5,
               label="Baseline (no savings)")
    ax.set_ylabel("Carbon savings vs baseline (%)")
    ax.set_xlabel("Policy")
    ax.set_title(f"Carbon savings distribution — {n_main} runs across sweep")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[PLOT] Saved {out_path}")


def plot_ablation(results_csv, out_path):
    """8-cell heatmap of mean savings_pct. VERBATIM from RESEARCH.md lines 739-767.

    Boolean columns parsed as `int(row[col] == "True")` per RESEARCH.md line 745
    (do NOT use bool(row[col]) — string "False" is truthy).
    """
    cells = {tup: [] for tup in ABLATION_AXES}
    with open(results_csv) as f:
        for row in csv.DictReader(f):
            if row["sweep_kind"] != "ablation":
                continue
            tup = (int(row["hw_weighting"] == "True"),
                   int(row["overhead_cost"] == "True"),
                   int(row["deadline_gate"] == "True"))
            cells[tup].append(float(row["savings_pct"]))

    if not any(cells[t] for t in ABLATION_AXES):
        print("[PLOT] No ablation rows found — skipping ablation.png", file=sys.stderr)
        return

    means = np.array([np.mean(cells[t]) if cells[t] else np.nan
                      for t in ABLATION_AXES]).reshape(2, 2, 2)
    # Display as 2 rows × 4 cols (HW × OH×DL flat).
    fig, ax = plt.subplots(figsize=(9, 4))
    flat = means.reshape(2, 4)
    im = ax.imshow(flat, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(4))
    ax.set_xticklabels(["OH0_DL0", "OH0_DL1", "OH1_DL0", "OH1_DL1"])
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["HW0", "HW1"])
    for i in range(2):
        for j in range(4):
            val = flat[i, j]
            label = f"{val:.2f}%" if not np.isnan(val) else "n/a"
            ax.text(j, i, label, ha="center", va="center",
                    color="black", fontsize=11, fontweight="bold")
    fig.colorbar(im, ax=ax, label="Mean savings_pct")
    ax.set_title("HEUR-10: Ablation — mean savings_pct per Policy 6 cell")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[PLOT] Saved {out_path}")


def plot_horizon(results_csv, out_path):
    """Line plot: mean savings_pct vs lookahead_hours for Policy 6 (HEUR-11),
    with Policy 1-5 horizontal reference baselines (D-15).

    Plan 03 emits horizon-sweep rows for Policy 6 (one per HORIZON_VALUE) and
    one row per Policy 1-5 baseline (lookahead_hours empty). This plot draws
    Policy 6 as a line and Policies 1-5 as axhlines colored by POLICY_COLORS.
    """
    p6_by_horizon = {h: [] for h in HORIZON_VALUES}
    baselines = {p: [] for p in range(1, 6)}

    with open(results_csv) as f:
        for row in csv.DictReader(f):
            if row["sweep_kind"] != "horizon":
                continue
            policy = int(row["policy"])
            savings = float(row["savings_pct"])
            if policy == 6:
                # Policy 6 horizon-sweep row — lookahead_hours is populated.
                lh_str = row.get("lookahead_hours", "")
                if not lh_str:
                    continue
                lh = int(lh_str)
                if lh in p6_by_horizon:
                    p6_by_horizon[lh].append(savings)
            elif 1 <= policy <= 5:
                baselines[policy].append(savings)

    if not any(p6_by_horizon[h] for h in HORIZON_VALUES):
        print("[PLOT] No horizon rows found — skipping horizon.png", file=sys.stderr)
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    # Policy 6 line (mean over timestamps × source regions per horizon).
    xs = list(HORIZON_VALUES)
    ys = [np.mean(p6_by_horizon[h]) if p6_by_horizon[h] else np.nan for h in xs]
    ax.plot(xs, ys, marker="o", linewidth=2.0, color=POLICY_COLORS[6],
            label="Policy 6 (heuristic)")

    # Policies 1-5 reference baselines.
    for p in range(1, 6):
        if not baselines[p]:
            continue
        mean_baseline = float(np.mean(baselines[p]))
        ax.axhline(mean_baseline, color=POLICY_COLORS[p], linestyle="--",
                   alpha=0.6, label=f"Policy {p} baseline")

    ax.axhline(0, color="black", linestyle=":", alpha=0.4,
               label="No savings")
    ax.set_xscale("log", base=2)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(x) for x in xs])
    ax.set_xlabel("Lookahead horizon (hours)")
    ax.set_ylabel("Mean carbon savings vs baseline (%)")
    ax.set_title("HEUR-11: Forecast horizon sensitivity — Policy 6 vs baselines")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[PLOT] Saved {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot Phase 4 evaluation results "
                    "(comparison / ablation / horizon)"
    )
    parser.add_argument(
        "run_dir",
        help="Path to a Phase 4 sweep directory containing results.csv "
             "(e.g. data/evaluation/run_20260428_193000/)",
    )
    parser.add_argument(
        "--kind",
        choices=["comparison", "ablation", "horizon", "all"],
        default="all",
        help="Which plot(s) to generate (default: all)",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    results_csv = run_dir / "results.csv"
    if not results_csv.is_file():
        print(f"[PLOT] ERROR: {results_csv} not found", file=sys.stderr)
        return 1

    kinds = (["comparison", "ablation", "horizon"]
             if args.kind == "all" else [args.kind])

    if "comparison" in kinds:
        plot_savings_comparison(results_csv, run_dir / "comparison.png")
    if "ablation" in kinds:
        plot_ablation(results_csv, run_dir / "ablation.png")
    if "horizon" in kinds:
        plot_horizon(results_csv, run_dir / "horizon.png")

    return 0


if __name__ == "__main__":
    sys.exit(main())
