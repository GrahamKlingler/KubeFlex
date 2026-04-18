#!/usr/bin/env python3
"""
Carbon-Aware Single-Pod Migration Test Harness (Python)

Controller-driven mode: deploys a long-running pod, lets the controller
drive migrations based on carbon-aware scheduling policies, and records
carbon usage IN REAL TIME at every migration and sim-time advance.

Unlike the bash version, this script logs carbon intensity readings as
they happen, so you get intermediate results without waiting for completion.

Requirements:
  - nbody-mpi:local image loaded into Kind
  - Controller deployed and configured
  - Metadata service running (for carbon queries)
  - YAML template with placeholders
"""

import argparse
import csv
import json
import math
import re
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add heuristics package to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
from heuristics.hardware import HW_TABLE, get_hardware


# ── Configuration defaults ──────────────────────────────────────────

NAMESPACE = "test-namespace"
CONTROLLER_NAMESPACE = "monitor"
SCRIPT_DIR = Path(__file__).parent
YAML_TEMPLATE = SCRIPT_DIR / "carbon-testpod.yml"
OUT_DIR_BASE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "carbon-single-pod"
POD_BASENAME = "carbon-pod"
METADATA_URL = "http://localhost:8008"

# ── Globals ─────────────────────────────────────────────────────────

portfwd_proc = None


def cleanup():
    """Kill port-forward on exit."""
    global portfwd_proc
    if portfwd_proc and portfwd_proc.poll() is None:
        portfwd_proc.terminate()
        try:
            portfwd_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            portfwd_proc.kill()


signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(1)))
signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(1)))


# ── Kubernetes helpers ──────────────────────────────────────────────

def kubectl(*args, capture=True, timeout=60):
    """Run a kubectl command, returning (returncode, stdout, stderr)."""
    cmd = ["kubectl"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "kubectl timed out"


def pod_exists(name):
    rc, _, _ = kubectl("get", "pod", name, "-n", NAMESPACE)
    return rc == 0


def pod_phase(name):
    rc, out, _ = kubectl("get", "pod", name, "-n", NAMESPACE,
                         "-o", "jsonpath={.status.phase}")
    return out.strip() if rc == 0 else ""


def pod_node(name):
    rc, out, _ = kubectl("get", "pod", name, "-n", NAMESPACE,
                         "-o", "jsonpath={.spec.nodeName}")
    return out.strip() if rc == 0 else ""


def node_region(node_name):
    rc, out, _ = kubectl("get", "node", node_name,
                         "-o", "jsonpath={.metadata.labels.REGION}")
    return out.strip() if rc == 0 else "unknown"


def wait_for_phase(name, *targets, timeout=600):
    """Wait until pod reaches one of the target phases."""
    start = time.time()
    while True:
        ph = pod_phase(name)
        if ph in targets:
            return ph
        if time.time() - start > timeout:
            print(f"  Timed out waiting for {name} to reach {targets}. Current={ph}")
            return ph
        time.sleep(2)


def find_active_pod(basename):
    """Find the latest Running pod in the migration chain."""
    latest = None
    if pod_exists(basename) and pod_phase(basename) == "Running":
        latest = basename
    for i in range(1, 51):
        candidate = f"{basename}-{i}"
        if pod_exists(candidate) and pod_phase(candidate) == "Running":
            latest = candidate
    return latest


def any_pod_alive(basename):
    """Check if any pod in the chain is Running or Pending."""
    for i in range(0, 51):
        name = basename if i == 0 else f"{basename}-{i}"
        if pod_exists(name):
            ph = pod_phase(name)
            if ph in ("Running", "Pending"):
                return True
    return False


def render_yaml(bodies, iters, checkpoint, pod_name, node, expected_dur, out_path):
    """Render the YAML template with substitutions and nodeSelector."""
    with open(YAML_TEMPLATE) as f:
        content = f.read()

    content = content.replace("__BODIES__", str(bodies))
    content = content.replace("__ITERS__", str(iters))
    content = content.replace("__CHECKPOINT__", str(checkpoint))
    content = content.replace("__EXPECTED_DURATION__", str(expected_dur))
    content = re.sub(r"^  name: .*$", f"  name: {pod_name}", content, flags=re.MULTILINE)

    # Inject nodeSelector after restartPolicy
    lines = content.split("\n")
    out_lines = []
    for line in lines:
        out_lines.append(line)
        if line.strip() == "restartPolicy: Never":
            out_lines.append("  nodeSelector:")
            out_lines.append(f"    kubernetes.io/hostname: {node}")

    with open(out_path, "w") as f:
        f.write("\n".join(out_lines))


def delete_pod(name):
    kubectl("delete", "pod", name, "-n", NAMESPACE, "--wait=true",
            "--ignore-not-found=true", timeout=120)


# ── Metadata / carbon helpers ──────────────────────────────────────

def start_port_forward():
    """Start kubectl port-forward to the metadata service, or reuse existing one."""
    global portfwd_proc
    # Check if port 8008 is already reachable
    import urllib.request
    try:
        req = urllib.request.Request(METADATA_URL, method="GET")
        urllib.request.urlopen(req, timeout=2)
        print("Metadata service already reachable on localhost:8008 (reusing existing port-forward).")
        return True
    except Exception:
        pass

    # Kill any stale process on port 8008
    subprocess.run(["bash", "-c", "lsof -ti :8008 | xargs kill 2>/dev/null"], capture_output=True)
    time.sleep(1)

    portfwd_proc = subprocess.Popen(
        ["kubectl", "port-forward", "-n", CONTROLLER_NAMESPACE,
         "svc/metadata-service", "8008:8008"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    if portfwd_proc.poll() is not None:
        print("WARNING: Port-forward failed to start. Carbon data may be unavailable.")
        portfwd_proc = None
        return False
    print("Metadata port-forward started (localhost:8008).")
    return True


def fetch_forecast(duration_hours, metadata_url, cache_path, start_time=None):
    """Fetch full forecast from the metadata service."""
    import urllib.request
    try:
        payload = {"duration": duration_hours}
        if start_time is not None:
            payload["start_time"] = start_time
        req = urllib.request.Request(
            metadata_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        with open(cache_path, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"WARNING: Failed to fetch forecast: {e}")
        return None


def query_intensity(forecast_data, region, sim_timestamp):
    """Look up carbon intensity for a given region and simulation timestamp."""
    if not forecast_data:
        return None

    # Search in region_forecasts
    region_data = forecast_data.get("region_forecasts", {}).get(region, {})
    points = region_data.get("forecast_data", [])

    best_intensity = None
    best_diff = float("inf")

    for point in points:
        if len(point) < 3:
            continue
        ts_str = point[0].split("+")[0].strip()
        try:
            pt_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            diff = abs(pt_dt.timestamp() - sim_timestamp)
            if diff < best_diff:
                best_diff = diff
                best_intensity = float(point[2])
        except Exception:
            continue

    if best_intensity is not None and best_diff <= 7200:
        return best_intensity

    # Fallback: check min_forecast
    for point in forecast_data.get("min_forecast", {}).get("forecast_data", []):
        if len(point) >= 3 and point[1] == region:
            ts_str = point[0].split("+")[0].strip()
            try:
                pt_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if abs(pt_dt.timestamp() - sim_timestamp) <= 7200:
                    return float(point[2])
            except Exception:
                continue

    return None


def set_policy_and_restart(policy, scheduler_time):
    """Update scheduler-config ConfigMap and restart the controller."""
    print(f"--- Setting scheduler policy={policy}, time={scheduler_time} ---")
    for ns in (CONTROLLER_NAMESPACE, NAMESPACE):
        rc, yaml_out, _ = kubectl("create", "configmap", "scheduler-config",
                                  f"--from-literal=scheduler-time={scheduler_time}",
                                  f"--from-literal=scheduling-policy={policy}",
                                  "-n", ns, "--dry-run=client", "-o", "yaml")
        if rc == 0:
            subprocess.run(["kubectl", "apply", "-f", "-"],
                           input=yaml_out, capture_output=True, text=True)

    print("  Restarting controller...")
    kubectl("rollout", "restart", "deployment", "controller",
            "-n", CONTROLLER_NAMESPACE, timeout=30)
    kubectl("rollout", "status", "deployment", "controller",
            "-n", CONTROLLER_NAMESPACE, "--timeout=120s", timeout=150)
    print("  Controller restarted.")
    print()


# ── Expected simulation helpers ───────────────────────────────────

def build_intensity_lookup(forecast_data):
    """Build a dict mapping (region, sim_timestamp) -> intensity from forecast data."""
    lookup = {}  # (region, timestamp) -> intensity
    for region, rdata in forecast_data.get("region_forecasts", {}).items():
        for point in rdata.get("forecast_data", []):
            if len(point) < 3:
                continue
            ts_str = point[0].split("+")[0].strip()
            try:
                pt_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                lookup[(region, int(pt_dt.timestamp()))] = float(point[2])
            except Exception:
                continue
    return lookup


def lookup_intensity(intensity_lookup, region, sim_timestamp):
    """Look up intensity for a region at a given timestamp, with fuzzy matching."""
    val = intensity_lookup.get((region, sim_timestamp))
    if val is not None:
        return val
    # Fuzzy: find closest within 2 hours
    best_val, best_diff = None, float("inf")
    for (r, ts), v in intensity_lookup.items():
        if r == region:
            d = abs(ts - sim_timestamp)
            if d < best_diff:
                best_diff = d
                best_val = v
    return best_val if best_diff <= 7200 else None


def get_all_regions(forecast_data):
    """Get list of all regions from forecast data."""
    return list(forecast_data.get("region_forecasts", {}).keys())



def get_min_region_at(intensity_lookup, regions, sim_timestamp, hw=None):
    """Find the region with minimum carbon at a given timestamp (for Policy 2/5).
    When hw is provided, compares power_per_core * intensity instead of raw intensity."""
    best_region, best_score = None, float("inf")
    for region in regions:
        val = lookup_intensity(intensity_lookup, region, sim_timestamp)
        if val is None:
            continue
        score = val * hw[region].power_per_core if hw else val
        if score < best_score:
            best_score = score
            best_region = region
    return best_region, best_score


def simulate_policy_decision(policy, intensity_lookup, regions, current_region,
                             sim_timestamp, expected_duration_hours, forecast_window=24,
                             cost_multiplier=3.0, migration_seconds=7.0, use_hw=False):
    """Simulate a policy's migration decision for one timestep.

    Returns (should_migrate: bool, target_region: str or None).
    """
    def calculate_carbon(carbon_intensity, hw_usage, core_usage=1, hours=1):
        return carbon_intensity*hw_usage*hours*core_usage

    hw_vals = HW_TABLE

    if policy == 1:
        # No migration after initial placement
        return False, None

    elif policy == 2:
        # Migrate to the region with minimum intensity this hour
        min_region, _ = get_min_region_at(intensity_lookup, regions, sim_timestamp,
                                          hw_vals if use_hw else None)
        if min_region and min_region != current_region:
            return True, min_region
        return False, None

    elif policy == 3:
        # Forecast-based: sum intensity over remaining expected_duration, pick lowest total
        region_totals = {}
        for region in regions:
            total = 0.0
            for h in range(expected_duration_hours):
                ts = sim_timestamp + h * 3600
                val = lookup_intensity(intensity_lookup, region, ts)
                if val is not None:
                    total += val
            region_totals[region] = total
        if not region_totals:
            return False, None
        optimal = min(region_totals, key=region_totals.get)
        if optimal != current_region:
            return True, optimal
        return False, None

    elif policy == 4:
        # Forecast-aware adaptive with migration cost threshold
        region_scores = {}
        all_carbon = []
        for region in regions:
            score = 0.0
            for h in range(forecast_window):
                ts = sim_timestamp + h * 3600
                val = lookup_intensity(intensity_lookup, region, ts)
                if val is not None:
                    hour_carbon = calculate_carbon(val, hw_vals[region].power_per_core) if use_hw else val
                    score += hour_carbon
                    all_carbon.append(hour_carbon)
            region_scores[region] = score
        if not region_scores:
            return False, None

        best_region = min(region_scores, key=region_scores.get)
        best_score = region_scores[best_region]
        current_score = region_scores.get(current_region, float("inf"))
        benefit = current_score - best_score

        # Migration cost
        current_intensity = current_score / max(forecast_window, 1)
        target_intensity = best_score / max(forecast_window, 1)
        migration_carbon = (migration_seconds / 3600.0) * max(current_intensity, target_intensity)
        threshold = migration_carbon * cost_multiplier

        if benefit > threshold and best_region != current_region:
            return True, best_region
        return False, None

    elif policy == 5:
        # Always-best: migrate to best region for the NEXT hour
        next_ts = sim_timestamp + 3600
        hw = hw_vals if use_hw else None
        min_region, min_score = get_min_region_at(intensity_lookup, regions, next_ts, hw)
        current_next = lookup_intensity(intensity_lookup, current_region, next_ts)
        if current_next is None:
            return False, None
        current_score = current_next * hw_vals[current_region].power_per_core if use_hw else current_next
        if min_region and min_region != current_region and min_score < current_score:
            return True, min_region
        return False, None

    return False, None


def run_expected_simulation(args):
    """Run a fast expected simulation using forecast data only (no Kubernetes needed)."""
    # Output directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR_BASE / f"{ts}_policy{args.policy}_expected"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_sim_hours = int(math.ceil(args.expected_completion / 60.0))
    migration_hours = max(1, int(math.ceil(args.expected_migration / 60.0)))
    forecast_hours = total_sim_hours + 72  # extra buffer for policy lookahead

    print("=" * 60)
    print("  Expected Simulation (no cluster required)")
    print("=" * 60)
    print(f"  Policy:              {args.policy}")
    print(f"  Using Hardware:      {args.use_hw}")
    print(f"  Scheduler start:     {args.scheduler_time}")
    print(f"  Expected completion: {args.expected_completion} min ({total_sim_hours} hours)")
    print(f"  Migration time:      {args.expected_migration} min ({migration_hours} hours)")
    print(f"  Source region:       {args.source_region}")
    print(f"  Output:              {out_dir}")
    print()

    # ── Fetch or load forecast data ──────────────────────────────
    forecast_cache = out_dir / "forecast_cache.json"
    forecast_data = None

    # Try loading from a provided cache first
    if args.forecast_cache and Path(args.forecast_cache).exists():
        print(f"Loading forecast from cache: {args.forecast_cache}")
        with open(args.forecast_cache) as f:
            forecast_data = json.load(f)
        # Copy to output dir
        with open(forecast_cache, "w") as f:
            json.dump(forecast_data, f)
    else:
        # Fetch from metadata service
        print(f"Fetching forecast ({forecast_hours}h) from metadata service...")
        start_port_forward()
        forecast_data = fetch_forecast(forecast_hours, args.metadata_url, forecast_cache,
                                       start_time=args.scheduler_time)

    if not forecast_data:
        print("ERROR: No forecast data available. Provide --forecast-cache or run with metadata service.")
        cleanup()
        sys.exit(1)

    regions = get_all_regions(forecast_data)
    intensity_lookup = build_intensity_lookup(forecast_data)
    print(f"  Regions available: {', '.join(regions)}")
    print()

    # Validate source region
    if args.source_region not in regions:
        print(f"WARNING: Source region '{args.source_region}' not in forecast data. "
              f"Available: {', '.join(regions)}")
        print(f"  Using first region: {regions[0]}")
        args.source_region = regions[0]

    # ── Simulate migration decisions hour by hour ─────────────────
    current_region = args.source_region
    initial_region = args.source_region
    current_sim_time = args.scheduler_time
    migration_seconds_real = args.expected_migration * 60.0

    migration_count = 0
    total_carbon = 0.0
    baseline_carbon = 0.0
    hours_tracked = 0
    migrating_cooldown = 0  # hours remaining in migration (pod unavailable)

    carbon_rows = []
    migration_events = []
    sim_timestamps = []

    print("--- Simulating hour by hour ---")
    print()

    for hour in range(total_sim_hours):
        sim_ts = current_sim_time + hour * 3600
        sim_dt = datetime.fromtimestamp(sim_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        sim_timestamps.append(sim_ts)

        # Current region intensity
        raw_intensity = lookup_intensity(intensity_lookup, current_region, sim_ts)
        raw_baseline = lookup_intensity(intensity_lookup, initial_region, sim_ts)

        # Apply hardware scaling when --use-hw is set
        if args.use_hw and raw_intensity is not None:
            intensity = raw_intensity * HW_TABLE[current_region].power_per_core
        else:
            intensity = raw_intensity

        if args.use_hw and raw_baseline is not None:
            baseline_intensity = raw_baseline * HW_TABLE[initial_region].power_per_core
        else:
            baseline_intensity = raw_baseline

        if intensity is not None:
            total_carbon += intensity
        if baseline_intensity is not None:
            baseline_carbon += baseline_intensity
        hours_tracked += 1

        # Log carbon
        carbon_rows.append({
            "sim_time": sim_ts,
            "sim_datetime": sim_dt,
            "region": current_region,
            "intensity": f"{intensity:.1f}" if intensity is not None else "N/A",
            "cumulative": f"{total_carbon:.1f}",
            "migrations": migration_count,
            "pod": f"carbon-pod" if migration_count == 0 else f"carbon-pod-{migration_count}",
        })

        status = ""
        if migrating_cooldown > 0:
            migrating_cooldown -= 1
            status = f"  [MIGRATING - {migrating_cooldown}h remaining]"
        else:
            # Check if policy wants to migrate
            remaining_hours = max(1, total_sim_hours - hour)
            should_migrate, target_region = simulate_policy_decision(
                args.policy, intensity_lookup, regions, current_region, sim_ts,
                expected_duration_hours=remaining_hours,
                forecast_window=24,
                cost_multiplier=3.0,
                migration_seconds=migration_seconds_real,
                use_hw=args.use_hw,
            )

            if should_migrate and target_region:
                migration_count += 1
                old_region = current_region
                old_intensity = intensity  # already hw-adjusted if use_hw

                raw_new = lookup_intensity(intensity_lookup, target_region, sim_ts)
                if args.use_hw and raw_new is not None:
                    new_intensity = raw_new * HW_TABLE[target_region].power_per_core
                else:
                    new_intensity = raw_new
                migration_events.append({
                    "event_num": migration_count,
                    "timestamp": sim_dt.replace(" ", "T") + "Z",
                    "sim_time": sim_ts,
                    "pod_name": f"carbon-pod-{migration_count}",
                    "source_node": f"node-{old_region}",
                    "source_region": old_region,
                    "target_node": f"node-{target_region}",
                    "target_region": target_region,
                    "intensity_before": f"{old_intensity:.1f}" if old_intensity is not None else "N/A",
                    "intensity_after": f"{new_intensity:.1f}" if new_intensity is not None else "N/A",
                    "migration_duration_ms": int(migration_seconds_real * 1000),
                })

                migrating_cooldown = migration_hours - 1  # current hour counts as 1
                current_region = target_region
                status = f"  >>> MIGRATE to {target_region}"

        int_str = f"{intensity:.1f}" if intensity is not None else "N/A"
        unit = "gCO2" if args.use_hw else "gCO2/kWh"
        print(f"  [Hour {hour + 1:3d}] sim={sim_dt}  region={current_region:6s}  "
              f"intensity={int_str:>7s} {unit}  cumulative={total_carbon:.1f}{status}")

    print()

    # ── Compute derived metrics ───────────────────────────────────
    total_runtime_ms = total_sim_hours * 3600 * 1000
    migration_overhead_ms = migration_count * int(migration_seconds_real * 1000)
    migration_fraction = migration_overhead_ms / total_runtime_ms if total_runtime_ms > 0 else 0
    migration_carbon_est = total_carbon * migration_fraction
    job_time_carbon = total_carbon - migration_carbon_est

    # ── Write output files ────────────────────────────────────────
    # carbon_log.csv
    carbon_log_path = out_dir / "carbon_log.csv"
    with open(carbon_log_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sim_time", "sim_datetime", "region", "intensity_gco2kwh",
                     "cumulative_carbon_gco2", "migrations_so_far", "active_pod"])
        for row in carbon_rows:
            w.writerow([row["sim_time"], row["sim_datetime"], row["region"],
                        row["intensity"], row["cumulative"], row["migrations"], row["pod"]])

    # migration_events.csv
    migration_log_path = out_dir / "migration_events.csv"
    with open(migration_log_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_num", "timestamp", "sim_time", "pod_name",
                     "source_node", "source_region", "target_node", "target_region",
                     "intensity_before", "intensity_after", "migration_duration_ms"])
        for evt in migration_events:
            w.writerow([evt["event_num"], evt["timestamp"], evt["sim_time"],
                        evt["pod_name"], evt["source_node"], evt["source_region"],
                        evt["target_node"], evt["target_region"],
                        evt["intensity_before"], evt["intensity_after"],
                        evt["migration_duration_ms"]])

    # results.csv
    results_csv = out_dir / "results.csv"
    migration_events_str = ";".join(
        f"{e['event_num']},{e['timestamp']},{e['sim_time']},{e['pod_name']},"
        f"{e['source_node']},{e['source_region']},{e['target_node']},{e['target_region']},"
        f"{e['intensity_before']},{e['intensity_after']}"
        for e in migration_events
    )

    with open(results_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "policy", "bodies", "iters", "expected_duration_min",
                     "baseline_ms", "total_runtime_ms", "workload_reported_ms",
                     "migration_overhead_ms", "num_migrations",
                     "total_carbon_gco2", "baseline_carbon_gco2",
                     "job_time_carbon_gco2", "migration_carbon_gco2",
                     "hours_tracked", "migration_events"])
        w.writerow([ts, args.policy, "", "", args.expected_completion,
                     "", total_runtime_ms, "",
                     migration_overhead_ms, migration_count,
                     f"{total_carbon:.1f}", f"{baseline_carbon:.1f}",
                     f"{job_time_carbon:.1f}", f"{migration_carbon_est:.1f}",
                     hours_tracked, migration_events_str])

    # ── Summary ───────────────────────────────────────────────────
    print("=" * 60)
    print("  Expected Simulation Results")
    print("=" * 60)
    print(f"  Policy:              {args.policy}")
    print(f"  Duration:            {total_sim_hours} hours")
    print(f"  Migrations:          {migration_count}")
    print(f"  Hours tracked:       {hours_tracked}")
    if hours_tracked > 0:
        print(f"  Avg intensity:       {total_carbon / hours_tracked:.1f} gCO2/kWh")
    print(f"  --- Carbon ---")
    print(f"  Total carbon:        {total_carbon:.1f} gCO2")
    print(f"  Baseline carbon:     {baseline_carbon:.1f} gCO2  (stay in {initial_region})")
    print(f"  Job-time carbon:     {job_time_carbon:.1f} gCO2")
    print(f"  Migration carbon:    {migration_carbon_est:.1f} gCO2")
    if baseline_carbon > 0:
        savings = baseline_carbon - total_carbon
        pct = (savings / baseline_carbon) * 100
        print(f"  Carbon savings:      {savings:.1f} gCO2  ({pct:.1f}% vs baseline)")
    print()
    print(f"  Results CSV:         {results_csv}")
    print(f"  Carbon log:          {carbon_log_path}")
    print(f"  Migration log:       {migration_log_path}")
    print(f"  Forecast cache:      {forecast_cache}")
    print(f"  Output directory:    {out_dir}")
    print()
    print("  Run graph_results.py on this directory to visualize.")
    print("  DONE.")

    cleanup()


# ── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Carbon-aware single-pod migration test (Python, live logging)")
    parser.add_argument("--bodies", type=int, default=10000)
    parser.add_argument("--iters", type=int, default=5000)
    parser.add_argument("--checkpoint", type=int, default=None, help="Checkpoint interval (default: same as iters)")
    parser.add_argument("--policy", type=int, choices=[1, 2, 3, 4, 5], default=4)
    parser.add_argument("--scheduler-time", type=int, default=1609459200, help="Unix timestamp for scheduler start")
    parser.add_argument("--expected-duration", type=int, default=360, help="Expected duration in minutes")
    parser.add_argument("--source-node", default="kind-worker")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--metadata-url", default=METADATA_URL)
    parser.add_argument("--check-interval", type=int, default=30, help="Controller check interval in seconds")
    parser.add_argument("--sim-hours-per-check", type=int, default=1)
    parser.add_argument("--poll-interval", type=int, default=10, help="Seconds between pod status polls")

    # Expected simulation mode (no cluster required)
    parser.add_argument("--expected", action="store_true",
                        help="Run expected simulation instead of real cluster test")
    parser.add_argument("--expected-completion", type=int, default=None,
                        help="Expected workload completion time in minutes (for --expected mode)")
    parser.add_argument("--expected-migration", type=int, default=None,
                        help="Expected migration time in minutes (for --expected mode)")
    parser.add_argument("--source-region", default="NE",
                        help="Initial region for expected simulation (default: NE)")
    parser.add_argument("--forecast-cache", default=None,
                        help="Path to existing forecast_cache.json (skip metadata fetch)")
    parser.add_argument("--use-hw", action="store_true",
                        help="Toggle use of hardware data in migration decisions")

    args = parser.parse_args()

    # ── Dispatch: expected simulation or real test ────────────────
    if args.expected:
        if args.expected_completion is None or args.expected_migration is None:
            parser.error("--expected requires --expected-completion and --expected-migration (both in minutes)")
        run_expected_simulation(args)
        return

    if args.checkpoint is None:
        args.checkpoint = args.iters

    # Output directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR_BASE / f"{ts}_policy{args.policy}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Carbon-Aware Single-Pod Migration Test (Python, live)")
    print("=" * 60)
    print(f"  Policy:            {args.policy}")
    print(f"  Bodies:            {args.bodies}")
    print(f"  Iterations:        {args.iters}")
    print(f"  Checkpoint:        {args.checkpoint}")
    print(f"  Expected duration: {args.expected_duration} min")
    print(f"  Scheduler time:    {args.scheduler_time}")
    print(f"  Source node:       {args.source_node}")
    print(f"  Check interval:    {args.check_interval}s  ({args.sim_hours_per_check}h sim/check)")
    print(f"  Output:            {out_dir}")
    print()

    # ── Start port-forward early for live carbon queries ───────────
    start_port_forward()

    # ── Fetch forecast upfront ─────────────────────────────────────
    # Estimate total simulated hours: each check_interval real seconds advances
    # sim_hours_per_check simulated hours. For a workload expected to run
    # expected_duration real minutes, the simulated span is:
    #   (expected_duration * 60 / check_interval) * sim_hours_per_check
    # Add a generous buffer since workloads often run longer than expected.
    forecast_hours = 250  # fixed: covers long simulation runs from the specified start time
    forecast_cache = out_dir / "forecast_cache.json"
    print(f"Fetching forecast ({forecast_hours}h) from metadata service (start_time={args.scheduler_time})...")
    forecast_data = fetch_forecast(forecast_hours, args.metadata_url, forecast_cache,
                                   start_time=args.scheduler_time)
    if forecast_data:
        n_regions = len(forecast_data.get("region_forecasts", {}))
        print(f"  Forecast cached: {n_regions} regions, {forecast_hours}h window")
    else:
        print("  WARNING: No forecast data — carbon readings will be unavailable")
    print()

    # ── Open CSV writers ───────────────────────────────────────────
    results_csv = out_dir / "results.csv"
    migration_log = out_dir / "migration_events.csv"
    carbon_log_path = out_dir / "carbon_log.csv"

    mig_f = open(migration_log, "w", newline="")
    mig_writer = csv.writer(mig_f)
    mig_writer.writerow(["event_num", "timestamp", "sim_time", "pod_name",
                         "source_node", "source_region", "target_node", "target_region",
                         "intensity_before", "intensity_after", "migration_duration_ms"])

    carbon_f = open(carbon_log_path, "w", newline="")
    carbon_writer = csv.writer(carbon_f)
    carbon_writer.writerow(["sim_time", "sim_datetime", "region", "intensity_gco2kwh",
                            "cumulative_carbon_gco2", "migrations_so_far", "active_pod"])

    # ── Clean up existing test pods ────────────────────────────────
    for i in range(0, 21):
        name = POD_BASENAME if i == 0 else f"{POD_BASENAME}-{i}"
        if pod_exists(name):
            delete_pod(name)

    # ── Phase 1: Baseline (optional) ──────────────────────────────
    baseline_ms = None
    if not args.skip_baseline:
        # Set policy 1 (no migration) so the baseline pod doesn't get migrated
        set_policy_and_restart(1, args.scheduler_time)

        print("--- Phase 1: Baseline run (no controller migration) ---")
        baseline_pod = f"{POD_BASENAME}-baseline"
        baseline_yaml = out_dir / f"{baseline_pod}.yaml"
        delete_pod(baseline_pod)

        render_yaml(args.bodies, args.iters, args.checkpoint, baseline_pod,
                    args.source_node, args.expected_duration, baseline_yaml)
        kubectl("apply", "-f", str(baseline_yaml), "-n", NAMESPACE)

        print("  Waiting for baseline pod to start...")
        wait_for_phase(baseline_pod, "Running", "Succeeded", timeout=120)

        print("  Waiting for baseline pod to complete...")
        wait_for_phase(baseline_pod, "Succeeded", "Failed", timeout=86400)

        # Try to extract SUMMARY
        rc, logs, _ = kubectl("logs", "-n", NAMESPACE, baseline_pod, timeout=30)
        if rc == 0:
            (out_dir / "baseline_kubectl_logs.log").write_text(logs)
            for line in logs.split("\n"):
                m = re.search(r"avg_ms=(\d+)", line)
                if m:
                    baseline_ms = int(m.group(1))

        if baseline_ms:
            print(f"  Baseline completed: {baseline_ms} ms")
        else:
            print("  WARNING: Baseline SUMMARY not found/parsable")

        delete_pod(baseline_pod)
    else:
        print("--- Phase 1: Skipped (--skip-baseline) ---")
    print()

    # ── Switch to requested policy before Phase 2 ───────────────
    set_policy_and_restart(args.policy, args.scheduler_time)

    # ── Phase 2: Controller-Driven Migration Run ──────────────────
    print("--- Phase 2: Controller-driven migration run ---")

    mig_yaml = out_dir / f"{POD_BASENAME}.yaml"
    render_yaml(args.bodies, args.iters, args.checkpoint, POD_BASENAME,
                args.source_node, args.expected_duration, mig_yaml)
    kubectl("apply", "-f", str(mig_yaml), "-n", NAMESPACE)

    print("  Waiting for pod to start running...")
    wait_for_phase(POD_BASENAME, "Running", "Succeeded", timeout=120)

    start_ms = int(time.time() * 1000)
    last_known_pod = POD_BASENAME
    last_known_node = pod_node(POD_BASENAME)
    last_known_region = node_region(last_known_node)
    migration_count = 0
    current_sim_time = args.scheduler_time

    initial_region = last_known_region  # remember for baseline carbon calculation
    sim_timestamps = []  # collect all sim timestamps for baseline recomputation

    print(f"  Initial placement: {POD_BASENAME} on {last_known_node} (region: {last_known_region})")

    # ── Log initial carbon intensity ──────────────────────────────
    total_carbon = 0.0
    hours_tracked = 0

    sim_timestamps.append(current_sim_time)
    initial_intensity = query_intensity(forecast_data, last_known_region, current_sim_time)
    sim_dt = datetime.fromtimestamp(current_sim_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    if initial_intensity is not None:
        total_carbon += initial_intensity
        hours_tracked += 1
        carbon_writer.writerow([current_sim_time, sim_dt, last_known_region,
                                f"{initial_intensity:.1f}", f"{total_carbon:.1f}",
                                migration_count, last_known_pod])
        carbon_f.flush()
        print(f"  [Hour {hours_tracked}] sim={sim_dt}  region={last_known_region}  "
              f"intensity={initial_intensity:.1f} gCO2/kWh  cumulative={total_carbon:.1f} gCO2")
    else:
        hours_tracked += 1
        carbon_writer.writerow([current_sim_time, sim_dt, last_known_region,
                                "N/A", f"{total_carbon:.1f}", migration_count, last_known_pod])
        carbon_f.flush()
        print(f"  [Hour {hours_tracked}] sim={sim_dt}  region={last_known_region}  "
              f"intensity=N/A  cumulative={total_carbon:.1f} gCO2")

    # ── Polling loop ──────────────────────────────────────────────
    poll_start = time.time()
    last_sim_advance = time.time()
    last_active_time = time.time()  # last time we confirmed the active pod was running
    measured_migration_overhead_ms = 0  # sum of all per-migration durations
    max_poll_time = 86400  # 24h

    print()
    print("  Monitoring for controller-driven migrations...")
    print("  (Carbon readings logged in real time)")
    print()

    try:
        while True:
            active_pod = find_active_pod(POD_BASENAME)

            # Check if all pods are done
            if active_pod is None:
                if not any_pod_alive(POD_BASENAME):
                    print("\n  All pods completed.")
                    break

            # Detect migration
            if active_pod and active_pod != last_known_pod:
                # Measure migration duration: time from last confirmed running to new pod detected
                mig_duration_ms = int((time.time() - last_active_time) * 1000)
                measured_migration_overhead_ms += mig_duration_ms

                migration_count += 1
                new_node = pod_node(active_pod)
                new_region = node_region(new_node)

                old_intensity = query_intensity(forecast_data, last_known_region, current_sim_time)
                new_intensity = query_intensity(forecast_data, new_region, current_sim_time)

                old_str = f"{old_intensity:.1f}" if old_intensity is not None else "N/A"
                new_str = f"{new_intensity:.1f}" if new_intensity is not None else "N/A"

                print(f"  >>> Migration #{migration_count}: {last_known_pod} ({last_known_node}/{last_known_region}) "
                      f"-> {active_pod} ({new_node}/{new_region})")
                print(f"      Intensity: {old_str} -> {new_str} gCO2/kWh  Duration: {mig_duration_ms}ms")

                mig_writer.writerow([migration_count,
                                     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     current_sim_time, active_pod,
                                     last_known_node, last_known_region,
                                     new_node, new_region,
                                     old_str, new_str, mig_duration_ms])
                mig_f.flush()

                last_known_pod = active_pod
                last_known_node = new_node
                last_known_region = new_region
                last_active_time = time.time()  # reset: new pod is now running

            elif active_pod:
                # Pod still running — update last active time
                last_active_time = time.time()

            # Advance simulation time in sync with controller
            now = time.time()
            elapsed = now - last_sim_advance
            if elapsed >= args.check_interval:
                for _ in range(args.sim_hours_per_check):
                    current_sim_time += 3600
                    hours_tracked += 1
                    sim_timestamps.append(current_sim_time)

                    intensity = query_intensity(forecast_data, last_known_region, current_sim_time)
                    sim_dt = datetime.fromtimestamp(current_sim_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

                    if intensity is not None:
                        total_carbon += intensity
                        carbon_writer.writerow([current_sim_time, sim_dt, last_known_region,
                                                f"{intensity:.1f}", f"{total_carbon:.1f}",
                                                migration_count, last_known_pod])
                        print(f"  [Hour {hours_tracked}] sim={sim_dt}  region={last_known_region}  "
                              f"intensity={intensity:.1f} gCO2/kWh  cumulative={total_carbon:.1f} gCO2")
                    else:
                        carbon_writer.writerow([current_sim_time, sim_dt, last_known_region,
                                                "N/A", f"{total_carbon:.1f}",
                                                migration_count, last_known_pod])
                        print(f"  [Hour {hours_tracked}] sim={sim_dt}  region={last_known_region}  "
                              f"intensity=N/A  cumulative={total_carbon:.1f} gCO2")

                    carbon_f.flush()

                last_sim_advance = now

            # Timeout
            if now - poll_start > max_poll_time:
                print("\n  WARNING: Poll timeout reached (24h)")
                # break
                print("Continuing after timeout...")

            time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        print("\n  Interrupted by user.")

    end_ms = int(time.time() * 1000)
    STARTUP_OVERHEAD_MS = 15  # measured overhead between pod Running and process start
    total_runtime_ms = end_ms - start_ms - STARTUP_OVERHEAD_MS

    # ── Collect logs from all pods and extract workload-reported runtime ──
    workload_reported_ms = None
    for i in range(0, migration_count + 6):
        name = POD_BASENAME if i == 0 else f"{POD_BASENAME}-{i}"
        if pod_exists(name):
            rc, logs, _ = kubectl("logs", "-n", NAMESPACE, name, timeout=30)
            if rc == 0:
                (out_dir / f"{name}_logs.log").write_text(logs)
                # Extract SUMMARY avg_ms from the last pod that reports it
                for line in logs.split("\n"):
                    m = re.search(r"avg_ms=(\d+)", line)
                    if m:
                        workload_reported_ms = int(m.group(1))

    # If SUMMARY not found in logs (old pods deleted), check /script-data/ on the last surviving pod
    if workload_reported_ms is None:
        for i in range(migration_count + 5, -1, -1):
            name = POD_BASENAME if i == 0 else f"{POD_BASENAME}-{i}"
            if pod_exists(name):
                for fpath in ["/script-data/container.log", "/tmp/checkpoints/summary.txt"]:
                    rc, out, _ = kubectl("exec", "-n", NAMESPACE, name, "--",
                                         "cat", fpath, timeout=15)
                    if rc == 0:
                        for line in out.split("\n"):
                            m = re.search(r"avg_ms=(\d+)", line)
                            if m:
                                workload_reported_ms = int(m.group(1))
                                break
                    if workload_reported_ms is not None:
                        break
            if workload_reported_ms is not None:
                break

    # Migration overhead: measured directly from polling (time old pod disappeared to new pod running)
    migration_overhead_ms = measured_migration_overhead_ms

    # ── Carbon accounting: baseline, job-time, and migration ─────
    # Baseline carbon: what carbon would have been with no migrations (stay in initial region)
    baseline_carbon = 0.0
    for st in sim_timestamps:
        intensity = query_intensity(forecast_data, initial_region, st)
        if intensity is not None:
            baseline_carbon += intensity

    # Job-time carbon: carbon attributable to actual computation
    # Migration carbon: carbon attributable to migration overhead (measured)
    job_time_carbon = None
    migration_carbon = None
    if total_runtime_ms > 0 and migration_overhead_ms > 0:
        migration_fraction = migration_overhead_ms / total_runtime_ms
        migration_carbon = total_carbon * migration_fraction
        job_time_carbon = total_carbon * (1.0 - migration_fraction)

    # ── Clean up pods ─────────────────────────────────────────────
    for i in range(0, migration_count + 6):
        name = POD_BASENAME if i == 0 else f"{POD_BASENAME}-{i}"
        if pod_exists(name):
            delete_pod(name)

    # ── Write results CSV ─────────────────────────────────────────
    mig_f.close()
    carbon_f.close()

    # Read back migration events for summary
    migration_events_str = ""
    if migration_log.exists():
        with open(migration_log) as f:
            lines = f.readlines()[1:]  # skip header
            migration_events_str = ";".join(l.strip() for l in lines)

    def fmt(v, decimals=1):
        """Format a numeric value or return empty string for None."""
        if v is None:
            return ""
        return f"{v:.{decimals}f}" if isinstance(v, float) else str(v)

    with open(results_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "policy", "bodies", "iters", "expected_duration_min",
                     "baseline_ms", "total_runtime_ms", "workload_reported_ms",
                     "migration_overhead_ms", "num_migrations",
                     "total_carbon_gco2", "baseline_carbon_gco2",
                     "job_time_carbon_gco2", "migration_carbon_gco2",
                     "hours_tracked", "migration_events"])
        w.writerow([ts, args.policy, args.bodies, args.iters, args.expected_duration,
                     baseline_ms or "", total_runtime_ms,
                     fmt(workload_reported_ms, 0) if workload_reported_ms is not None else "",
                     fmt(migration_overhead_ms, 0) if migration_overhead_ms is not None else "",
                     migration_count,
                     fmt(total_carbon), fmt(baseline_carbon),
                     fmt(job_time_carbon), fmt(migration_carbon),
                     hours_tracked, migration_events_str])

    # ── Final summary ─────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  Results Summary")
    print("=" * 60)
    print(f"  Policy:              {args.policy}")
    print(f"  Baseline (time):     {baseline_ms or 'N/A'} ms")
    print(f"  Total runtime:       {total_runtime_ms} ms ({total_runtime_ms / 1000 / 60:.1f} min)")
    print(f"  Workload reported:   {workload_reported_ms or 'N/A'} ms")
    print(f"  Migration overhead:  {migration_overhead_ms} ms (measured)")
    if migration_count > 0:
        print(f"  Avg per migration:   {migration_overhead_ms // migration_count} ms")
    print(f"  Migrations:          {migration_count}")
    print(f"  Hours tracked:       {hours_tracked}")
    if hours_tracked > 0:
        print(f"  Avg intensity:       {total_carbon / hours_tracked:.1f} gCO2/kWh")
    print(f"  --- Carbon ---")
    print(f"  Total carbon:        {total_carbon:.1f} gCO2")
    print(f"  Baseline carbon:     {baseline_carbon:.1f} gCO2  (no-migration scenario)")
    print(f"  Job-time carbon:     {fmt(job_time_carbon)} gCO2  (compute only)")
    print(f"  Migration carbon:    {fmt(migration_carbon)} gCO2  (migration overhead)")
    if baseline_carbon > 0:
        savings = baseline_carbon - total_carbon
        pct = (savings / baseline_carbon) * 100
        print(f"  Carbon savings:      {savings:.1f} gCO2  ({pct:.1f}% vs baseline)")
    print()
    print(f"  Results CSV:         {results_csv}")
    print(f"  Migration log:       {migration_log}")
    print(f"  Carbon log:          {carbon_log_path}")
    print(f"  Artifacts:           {out_dir}")
    print("  DONE.")

    cleanup()


if __name__ == "__main__":
    main()
