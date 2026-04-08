#!/usr/bin/env python3
"""
Graph carbon-aware migration test results from CSV output.

Usage:
    python3 graph_results.py <run_directory>
    python3 graph_results.py data/carbon-single-pod/20260320_200439_policy5

Reads carbon_log.csv, migration_events.csv, and results.csv from the
specified run directory and produces a multi-panel figure showing:
  1. Carbon intensity over time with migration events marked
  2. Cumulative carbon: actual vs baseline (no-migration)
  3. Carbon savings breakdown bar chart
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np


def load_carbon_log(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            dt = datetime.strptime(r["sim_datetime"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            intensity = float(r["intensity_gco2kwh"]) if r["intensity_gco2kwh"] != "N/A" else None
            cumulative = float(r["cumulative_carbon_gco2"])
            rows.append({
                "sim_time": int(r["sim_time"]),
                "datetime": dt,
                "region": r["region"],
                "intensity": intensity,
                "cumulative": cumulative,
                "migrations": int(r["migrations_so_far"]),
                "pod": r["active_pod"],
            })
    return rows


def load_migrations(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "event_num": int(r["event_num"]),
                "sim_time": int(r["sim_time"]),
                "datetime": datetime.fromtimestamp(int(r["sim_time"]), tz=timezone.utc),
                "source_region": r["source_region"],
                "target_region": r["target_region"],
                "intensity_before": float(r["intensity_before"]) if r["intensity_before"] != "N/A" else None,
                "intensity_after": float(r["intensity_after"]) if r["intensity_after"] != "N/A" else None,
            })
    return rows


def load_results(path):
    with open(path) as f:
        reader = csv.DictReader(f)
        return next(reader)


def compute_baseline_cumulative(carbon_log, initial_region, forecast_intensities):
    """Compute what cumulative carbon would have been without migrations."""
    cumulative = 0.0
    baseline = []
    for entry in carbon_log:
        # Use the intensity from the initial region at this timestamp
        intensity = forecast_intensities.get(entry["sim_time"])
        if intensity is not None:
            cumulative += intensity
        baseline.append(cumulative)
    return baseline


def graph(run_dir):
    run_dir = Path(run_dir)

    carbon_log_path = run_dir / "carbon_log.csv"
    migration_path = run_dir / "migration_events.csv"
    results_path = run_dir / "results.csv"

    if not carbon_log_path.exists():
        print(f"ERROR: {carbon_log_path} not found")
        sys.exit(1)

    carbon_log = load_carbon_log(carbon_log_path)
    migrations = load_migrations(migration_path) if migration_path.exists() else []
    results = load_results(results_path) if results_path.exists() else {}

    if not carbon_log:
        print("ERROR: carbon_log.csv is empty")
        sys.exit(1)

    # Extract arrays
    times = [e["datetime"] for e in carbon_log]
    intensities = [e["intensity"] for e in carbon_log]
    cumulative = [e["cumulative"] for e in carbon_log]
    regions = [e["region"] for e in carbon_log]

    # Build baseline cumulative (staying in initial region)
    initial_region = carbon_log[0]["region"]
    # We need the forecast data to look up baseline intensities.
    # Load from forecast_cache.json if available, otherwise approximate from results.
    baseline_carbon_total = float(results.get("baseline_carbon_gco2", 0)) if results else 0

    # Reconstruct baseline cumulative by scaling proportionally if we only have the total
    # Better: re-query from forecast cache
    forecast_cache_path = run_dir / "forecast_cache.json"
    baseline_cumulative = []
    if forecast_cache_path.exists():
        import json
        with open(forecast_cache_path) as f:
            forecast_data = json.load(f)

        # Build lookup: sim_timestamp -> intensity for initial region
        region_data = forecast_data.get("region_forecasts", {}).get(initial_region, {})
        points = region_data.get("forecast_data", [])
        intensity_lookup = {}
        for point in points:
            if len(point) >= 3:
                ts_str = point[0].split("+")[0].strip()
                try:
                    pt_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    intensity_lookup[int(pt_dt.timestamp())] = float(point[2])
                except Exception:
                    continue

        # Find closest match for each sim_time
        cum = 0.0
        for entry in carbon_log:
            st = entry["sim_time"]
            val = intensity_lookup.get(st)
            if val is None:
                # find closest within 2 hours
                best_val, best_diff = None, float("inf")
                for ts, v in intensity_lookup.items():
                    d = abs(ts - st)
                    if d < best_diff:
                        best_diff = d
                        best_val = v
                if best_val is not None and best_diff <= 7200:
                    val = best_val
            if val is not None:
                cum += val
            baseline_cumulative.append(cum)
    else:
        # Fallback: linear interpolation from total
        n = len(carbon_log)
        if n > 0 and baseline_carbon_total > 0:
            baseline_cumulative = [baseline_carbon_total * (i + 1) / n for i in range(n)]
        else:
            baseline_cumulative = cumulative[:]  # no baseline data

    # Migration timestamps for vertical lines
    mig_times = [m["datetime"] for m in migrations]
    mig_labels = [f"#{m['event_num']}\n{m['source_region']}\u2192{m['target_region']}" for m in migrations]

    # Assign a color per region
    unique_regions = list(dict.fromkeys(regions))  # preserve order
    cmap = plt.cm.Set2
    region_colors = {r: cmap(i / max(len(unique_regions) - 1, 1)) for i, r in enumerate(unique_regions)}

    # ── Figure setup ──────────────────────────────────────────────
    policy = results.get("policy", "?")
    bodies = results.get("bodies", "?")
    iters = results.get("iters", "?")
    n_mig = results.get("num_migrations", len(migrations))

    fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={"height_ratios": [3, 3, 2]})
    fig.suptitle(f"KubeFlex Carbon-Aware Migration Results  —  Policy {policy}  |  "
                 f"{bodies} bodies, {iters} iters  |  {n_mig} migrations",
                 fontsize=13, fontweight="bold")

    # ── Panel 1: Carbon intensity over time ───────────────────────
    ax1 = axes[0]

    # Color each segment by region
    for i in range(len(times) - 1):
        if intensities[i] is not None and intensities[i + 1] is not None:
            ax1.plot([times[i], times[i + 1]], [intensities[i], intensities[i + 1]],
                     color=region_colors[regions[i]], linewidth=2)

    # Scatter points colored by region
    for region in unique_regions:
        idx = [i for i, r in enumerate(regions) if r == region and intensities[i] is not None]
        ax1.scatter([times[j] for j in idx], [intensities[j] for j in idx],
                    color=region_colors[region], label=region, s=30, zorder=5)

    # Migration vertical lines
    for mt, ml in zip(mig_times, mig_labels):
        ax1.axvline(mt, color="red", linestyle="--", alpha=0.6, linewidth=1)
        ax1.text(mt, ax1.get_ylim()[0] if ax1.get_ylim()[0] != 0 else min(i for i in intensities if i) * 0.95,
                 ml, fontsize=7, color="red", ha="center", va="bottom",
                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="red", alpha=0.8))

    ax1.set_ylabel("Carbon Intensity (gCO\u2082/kWh)")
    ax1.set_title("Hourly Carbon Intensity by Region")
    ax1.legend(title="Region", loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

    # ── Panel 2: Cumulative carbon comparison ─────────────────────
    ax2 = axes[1]
    ax2.plot(times, cumulative, color="#2196F3", linewidth=2.5, label="With Migration")
    ax2.plot(times, baseline_cumulative, color="#FF9800", linewidth=2.5,
             linestyle="--", label="Baseline (no migration)")

    # Fill the savings area
    cum_arr = np.array(cumulative)
    base_arr = np.array(baseline_cumulative)
    ax2.fill_between(times, cum_arr, base_arr,
                     where=(base_arr >= cum_arr), interpolate=True,
                     alpha=0.2, color="green", label="Carbon saved")
    ax2.fill_between(times, cum_arr, base_arr,
                     where=(base_arr < cum_arr), interpolate=True,
                     alpha=0.2, color="red", label="Carbon excess")

    # Migration vertical lines
    for mt in mig_times:
        ax2.axvline(mt, color="red", linestyle="--", alpha=0.4, linewidth=1)

    ax2.set_ylabel("Cumulative Carbon (gCO\u2082)")
    ax2.set_title("Cumulative Carbon Emissions: Migration vs Baseline")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

    # ── Panel 3: Summary bar chart ────────────────────────────────
    ax3 = axes[2]

    total_c = float(results.get("total_carbon_gco2", cumulative[-1]))
    baseline_c = float(results.get("baseline_carbon_gco2", baseline_cumulative[-1]))
    job_c = float(results.get("job_time_carbon_gco2", 0) or 0)
    mig_c = float(results.get("migration_carbon_gco2", 0) or 0)

    # Left group: total comparison
    bars_x = [0, 1]
    bars_h = [baseline_c, total_c]
    bars_color = ["#FF9800", "#2196F3"]
    bars_label = ["Baseline\n(no migration)", "With\nMigration"]

    bar_objs = ax3.bar(bars_x, bars_h, width=0.6, color=bars_color, edgecolor="black", linewidth=0.5)

    # Right group: breakdown of migration run
    if job_c > 0 or mig_c > 0:
        ax3.bar(3, job_c, width=0.6, color="#4CAF50", edgecolor="black", linewidth=0.5,
                label="Compute carbon")
        ax3.bar(3, mig_c, bottom=job_c, width=0.6, color="#F44336", edgecolor="black",
                linewidth=0.5, label="Migration overhead carbon")
        ax3.set_xticks([0, 1, 3])
        ax3.set_xticklabels(["Baseline\n(no migration)", "With\nMigration",
                              "Migration Run\nBreakdown"])
        ax3.legend(loc="upper right", fontsize=9)
    else:
        ax3.set_xticks([0, 1])
        ax3.set_xticklabels(bars_label)

    # Value labels on bars
    for bar in [bar_objs[0], bar_objs[1]]:
        ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + baseline_c * 0.01,
                 f"{bar.get_height():.0f}", ha="center", va="bottom", fontsize=10, fontweight="bold")

    if job_c > 0 or mig_c > 0:
        ax3.text(3, job_c + mig_c + baseline_c * 0.01,
                 f"{job_c + mig_c:.0f}\n({mig_c:.0f} mig)", ha="center", va="bottom",
                 fontsize=9, fontweight="bold")

    # Savings annotation
    if baseline_c > 0:
        savings = baseline_c - total_c
        pct = savings / baseline_c * 100
        sign = "+" if savings < 0 else ""
        ax3.annotate(f"{'Saved' if savings >= 0 else 'Excess'}: {abs(savings):.0f} gCO\u2082 ({abs(pct):.1f}%)",
                     xy=(0.5, max(baseline_c, total_c) * 0.5),
                     fontsize=12, fontweight="bold", ha="center",
                     color="green" if savings >= 0 else "red",
                     bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="gray", alpha=0.9))

    ax3.set_ylabel("Total Carbon (gCO\u2082)")
    ax3.set_title("Carbon Emissions Comparison")
    ax3.grid(True, axis="y", alpha=0.3)

    # ── Finalize ──────────────────────────────────────────────────
    fig.autofmt_xdate()
    plt.tight_layout(rect=[0, 0, 1, 0.95])

    out_path = run_dir / "carbon_results.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved figure to {out_path}")
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Graph carbon migration test results")
    parser.add_argument("run_dir", help="Path to a test run directory containing carbon_log.csv")
    args = parser.parse_args()
    graph(args.run_dir)
