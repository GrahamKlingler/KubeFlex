#!/usr/bin/env python3
"""
CRIU Migration Overhead Visualization

Reads overhead_raw.csv and produces:
1. Stacked bar chart — checkpoint/transfer/restore per migration
2. Box plots — timing distributions by workload type
3. Summary statistics table — mean, median, std, min, max, p25, p75

Usage:
    python3 graph_overhead.py <run_dir>
    python3 graph_overhead.py --validate  # generate sample data and test
"""

import argparse
import csv
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# CSV field names produced by run_overhead_benchmark.py
CSV_FIELDS = [
    "run_id", "migration_num", "workload",
    "source_region", "target_region", "repetition",
    "checkpoint_ms", "transfer_ms", "restore_ms", "total_ms",
    "success", "timestamp_utc",
]

# Phase colors (consistent across all charts)
COLOR_CHECKPOINT = "#2196F3"  # blue
COLOR_TRANSFER   = "#FF9800"  # orange
COLOR_RESTORE    = "#4CAF50"  # green


def load_overhead_csv(csv_path):
    """Load overhead_raw.csv, filtering to successful rows only.

    Returns a list of dicts with numeric fields converted to float/int.
    """
    rows = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("success", "").lower() != "true":
                continue
            rows.append({
                "run_id":        r["run_id"],
                "migration_num": int(r["migration_num"]),
                "workload":      r["workload"],
                "source_region": r["source_region"],
                "target_region": r["target_region"],
                "repetition":    int(r["repetition"]),
                "checkpoint_ms": float(r["checkpoint_ms"]),
                "transfer_ms":   float(r["transfer_ms"]),
                "restore_ms":    float(r["restore_ms"]),
                "total_ms":      float(r["total_ms"]),
                "timestamp_utc": r["timestamp_utc"],
            })
    return rows


def plot_stacked_bars(rows, out_dir):
    """Chart 1: Stacked bar chart showing checkpoint/transfer/restore per migration.

    Each bar is one successful migration labeled as:
        "<workload>\\n<src>-><tgt>\\nR<rep>"

    Saves: out_dir/stacked_bar_overhead.png
    """
    if not rows:
        print("WARNING: No rows to plot for stacked bar chart")
        return

    n = len(rows)
    x = np.arange(n)

    checkpoint = np.array([r["checkpoint_ms"] for r in rows])
    transfer   = np.array([r["transfer_ms"]   for r in rows])
    restore    = np.array([r["restore_ms"]    for r in rows])

    labels = [
        f"{r['workload']}\n{r['source_region']}->{r['target_region']}\nR{r['repetition']}"
        for r in rows
    ]

    fig_width = max(16, n * 0.4)
    fig, ax = plt.subplots(figsize=(fig_width, 8))

    ax.bar(x, checkpoint, width=0.6, color=COLOR_CHECKPOINT,
           edgecolor="black", linewidth=0.5, label="Checkpoint")
    ax.bar(x, transfer, bottom=checkpoint, width=0.6, color=COLOR_TRANSFER,
           edgecolor="black", linewidth=0.5, label="Transfer")
    ax.bar(x, restore, bottom=checkpoint + transfer, width=0.6, color=COLOR_RESTORE,
           edgecolor="black", linewidth=0.5, label="Restore")

    ax.set_title("CRIU Migration Overhead by Component", fontsize=14, fontweight="bold")
    ax.set_ylabel("Duration (ms)")
    ax.set_xlabel("Migration")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.legend(loc="upper right")
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()

    out_path = out_dir / "stacked_bar_overhead.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_boxplots(rows, out_dir):
    """Chart 2: Box plots showing timing distributions by workload type.

    Three subplots side by side (one per workload); each subplot has three
    box plots (Checkpoint, Transfer, Restore).

    Saves: out_dir/boxplot_distributions.png
    """
    if not rows:
        print("WARNING: No rows to plot for box plots")
        return

    # Group by workload
    workloads = list(dict.fromkeys(r["workload"] for r in rows))  # preserve order

    ncols = max(len(workloads), 1)
    fig, axes = plt.subplots(1, ncols, figsize=(16, 6), squeeze=False)

    for col, workload in enumerate(workloads):
        wrows = [r for r in rows if r["workload"] == workload]
        checkpoint_data = [r["checkpoint_ms"] for r in wrows]
        transfer_data   = [r["transfer_ms"]   for r in wrows]
        restore_data    = [r["restore_ms"]    for r in wrows]

        ax = axes[0][col]
        bp = ax.boxplot(
            [checkpoint_data, transfer_data, restore_data],
            tick_labels=["Checkpoint", "Transfer", "Restore"],
            patch_artist=True,
        )

        # Apply consistent colors to box faces
        for patch, color in zip(bp["boxes"], [COLOR_CHECKPOINT, COLOR_TRANSFER, COLOR_RESTORE]):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax.set_title(workload, fontweight="bold")
        ax.set_ylabel("Duration (ms)")
        ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle("Migration Phase Duration Distributions by Workload",
                 fontsize=13, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.95])

    out_path = out_dir / "boxplot_distributions.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def print_summary_table(rows, out_dir):
    """Chart 3: Summary statistics table printed to stdout and saved as CSV.

    Groups by (workload, phase) and computes n, mean, median, std, min, max,
    p25, p75. Also adds aggregate 'all_workloads' rows.

    Saves: out_dir/summary_stats.csv
    """
    phases = ["checkpoint", "transfer", "restore", "total"]
    phase_keys = {
        "checkpoint": "checkpoint_ms",
        "transfer":   "transfer_ms",
        "restore":    "restore_ms",
        "total":      "total_ms",
    }

    workloads = list(dict.fromkeys(r["workload"] for r in rows))  # preserve order
    groups = workloads + ["all_workloads"]

    stat_rows = []

    for workload in groups:
        if workload == "all_workloads":
            wrows = rows
        else:
            wrows = [r for r in rows if r["workload"] == workload]

        if not wrows:
            continue

        for phase in phases:
            key = phase_keys[phase]
            vals = np.array([r[key] for r in wrows])
            stat_rows.append({
                "workload":   workload,
                "phase":      phase,
                "n":          len(vals),
                "mean_ms":    float(np.mean(vals)),
                "median_ms":  float(np.median(vals)),
                "std_ms":     float(np.std(vals)),
                "min_ms":     float(np.min(vals)),
                "max_ms":     float(np.max(vals)),
                "p25_ms":     float(np.percentile(vals, 25)),
                "p75_ms":     float(np.percentile(vals, 75)),
            })

    # Print table to stdout
    col_widths = {
        "workload": 18, "phase": 11, "n": 5,
        "mean_ms": 10, "median_ms": 10, "std_ms": 10,
        "min_ms": 10, "max_ms": 10, "p25_ms": 10, "p75_ms": 10,
    }
    header_keys = list(col_widths.keys())
    header = "  ".join(k.ljust(col_widths[k]) for k in header_keys)
    sep    = "  ".join("-" * col_widths[k] for k in header_keys)

    print("\n" + "=" * 80)
    print("MIGRATION OVERHEAD SUMMARY STATISTICS")
    print("=" * 80)
    print(header)
    print(sep)

    prev_workload = None
    for sr in stat_rows:
        if prev_workload is not None and sr["workload"] != prev_workload:
            print(sep)
        prev_workload = sr["workload"]

        row_str = (
            sr["workload"].ljust(col_widths["workload"]) + "  " +
            sr["phase"].ljust(col_widths["phase"]) + "  " +
            str(sr["n"]).ljust(col_widths["n"]) + "  " +
            f"{sr['mean_ms']:.1f}".ljust(col_widths["mean_ms"]) + "  " +
            f"{sr['median_ms']:.1f}".ljust(col_widths["median_ms"]) + "  " +
            f"{sr['std_ms']:.1f}".ljust(col_widths["std_ms"]) + "  " +
            f"{sr['min_ms']:.1f}".ljust(col_widths["min_ms"]) + "  " +
            f"{sr['max_ms']:.1f}".ljust(col_widths["max_ms"]) + "  " +
            f"{sr['p25_ms']:.1f}".ljust(col_widths["p25_ms"]) + "  " +
            f"{sr['p75_ms']:.1f}".ljust(col_widths["p75_ms"])
        )
        print(row_str)

    print("=" * 80 + "\n")

    # Save CSV
    out_path = out_dir / "summary_stats.csv"
    csv_fields = ["workload", "phase", "n", "mean_ms", "median_ms",
                  "std_ms", "min_ms", "max_ms", "p25_ms", "p75_ms"]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(stat_rows)

    print(f"Saved: {out_path}")
    return stat_rows


def graph(run_dir):
    """Main entry point for graphing a benchmark run directory."""
    run_dir = Path(run_dir)
    csv_path = run_dir / "overhead_raw.csv"

    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        sys.exit(1)

    rows = load_overhead_csv(csv_path)

    if not rows:
        print("ERROR: No successful rows found in overhead_raw.csv")
        sys.exit(1)

    print(f"Loaded {len(rows)} successful migration records from {csv_path}")

    plot_stacked_bars(rows, run_dir)
    plot_boxplots(rows, run_dir)
    print_summary_table(rows, run_dir)

    print(f"\nAll outputs written to {run_dir}")


def _make_sample_rows(run_dir):
    """Generate a small sample overhead_raw.csv for validation."""
    import random
    random.seed(42)

    workloads = ["sysbench-cpu", "memcount"]
    regions = [("NE", "TEN"), ("TEN", "CENT"), ("CENT", "NE")]

    sample_rows = []
    migration_num = 1
    for workload in workloads:
        for rep in range(1, 4):  # 3 reps per workload
            src, tgt = regions[(rep - 1) % len(regions)]
            checkpoint_ms = random.uniform(800, 2000)
            transfer_ms   = random.uniform(200, 800)
            restore_ms    = random.uniform(300, 1000)
            total_ms      = checkpoint_ms + transfer_ms + restore_ms
            sample_rows.append({
                "run_id":        "validate-run-001",
                "migration_num": migration_num,
                "workload":      workload,
                "source_region": src,
                "target_region": tgt,
                "repetition":    rep,
                "checkpoint_ms": f"{checkpoint_ms:.2f}",
                "transfer_ms":   f"{transfer_ms:.2f}",
                "restore_ms":    f"{restore_ms:.2f}",
                "total_ms":      f"{total_ms:.2f}",
                "success":       "true",
                "timestamp_utc": "2026-01-01T00:00:00Z",
            })
            migration_num += 1

    csv_path = run_dir / "overhead_raw.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(sample_rows)

    return csv_path


def validate():
    """Generate sample data and validate all three visualization functions."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="graph_overhead_validate_"))
    try:
        print(f"[VALIDATE] Using temp directory: {tmp_dir}")

        csv_path = _make_sample_rows(tmp_dir)
        print(f"[VALIDATE] Generated sample CSV: {csv_path}")

        rows = load_overhead_csv(csv_path)
        assert len(rows) == 6, f"Expected 6 rows, got {len(rows)}"
        print(f"[VALIDATE] Loaded {len(rows)} rows OK")

        plot_stacked_bars(rows, tmp_dir)
        assert (tmp_dir / "stacked_bar_overhead.png").exists(), "stacked_bar_overhead.png not created"
        print("[VALIDATE] stacked_bar_overhead.png OK")

        plot_boxplots(rows, tmp_dir)
        assert (tmp_dir / "boxplot_distributions.png").exists(), "boxplot_distributions.png not created"
        print("[VALIDATE] boxplot_distributions.png OK")

        print_summary_table(rows, tmp_dir)
        assert (tmp_dir / "summary_stats.csv").exists(), "summary_stats.csv not created"
        print("[VALIDATE] summary_stats.csv OK")

        # Verify summary CSV content
        with open(tmp_dir / "summary_stats.csv") as f:
            reader = csv.DictReader(f)
            stat_rows = list(reader)
        assert len(stat_rows) > 0, "summary_stats.csv is empty"
        # Each workload (sysbench-cpu, memcount, all_workloads) x 4 phases = 12 rows
        assert len(stat_rows) == 12, f"Expected 12 stat rows, got {len(stat_rows)}"
        print(f"[VALIDATE] summary_stats.csv has {len(stat_rows)} rows OK")

        # Verify required columns exist
        required_cols = {"workload", "phase", "n", "mean_ms", "median_ms", "std_ms",
                         "min_ms", "max_ms", "p25_ms", "p75_ms"}
        actual_cols = set(stat_rows[0].keys())
        assert required_cols <= actual_cols, f"Missing columns: {required_cols - actual_cols}"
        print("[VALIDATE] summary_stats.csv columns OK")

        print("\nValidation passed")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Graph CRIU overhead benchmark results")
    parser.add_argument("run_dir", nargs="?", help="Path to run directory containing overhead_raw.csv")
    parser.add_argument("--validate", action="store_true",
                        help="Generate sample data and validate visualization")
    args = parser.parse_args()

    if args.validate:
        validate()
    elif args.run_dir:
        graph(Path(args.run_dir))
    else:
        parser.print_help()
        sys.exit(1)
