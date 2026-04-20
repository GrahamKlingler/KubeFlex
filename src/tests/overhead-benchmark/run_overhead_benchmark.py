#!/usr/bin/env python3
"""
CRIU Migration Overhead Benchmark

Drives 54 live migrations (3 workloads x 6 region pairs x 3 repetitions)
through the migration service REST API, collects per-phase timing
(checkpoint, transfer, restore) from kubectl logs, and writes structured
CSV + JSON output to data/overhead-benchmark/.

Usage:
    python3 run_overhead_benchmark.py [--out-dir DIR] [--repetitions N]
        [--migration-service-url URL] [--namespace NS]

Prerequisites:
    - KIND cluster running on a Linux host with CRIU support
    - Migration service deployed and port-forwarded to localhost:8000
      (kubectl port-forward -n test-namespace svc/migration-service 8000:8000)
    - Migrator daemon pods running on each worker node (monitor namespace)
    - Workload images available in KIND cluster:
        grahamklingler26/sysbench-testpod:latest
        salamander1223/testpod:latest
"""

import argparse
import csv
import json
import logging
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


# ── Logging setup (per project convention) ─────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)


# ── Constants (module-level UPPER_CASE) ────────────────────────────────────

NAMESPACE = "test-namespace"
MONITOR_NAMESPACE = "monitor"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent

REGION_TO_NODE = {"NE": "kind-worker", "TEN": "kind-worker2", "CENT": "kind-worker3"}
NODE_TO_REGION = {v: k for k, v in REGION_TO_NODE.items()}

WORKLOADS = {
    "sysbench_cpu": "sysbench-cpu-pod",
    "sysbench_memory": "sysbench-memory-pod",
    "memcount": "memcount-pod",
}
WORKLOAD_YAMLS = {
    "sysbench_cpu": "workloads/sysbench-cpu.yml",
    "sysbench_memory": "workloads/sysbench-memory.yml",
    "memcount": "workloads/memcount.yml",
}
REGION_PAIRS = [
    ("NE", "TEN"), ("NE", "CENT"),
    ("TEN", "NE"), ("TEN", "CENT"),
    ("CENT", "NE"), ("CENT", "TEN"),
]
CSV_FIELDS = [
    "run_id", "migration_num", "workload",
    "source_region", "target_region", "repetition",
    "checkpoint_ms", "transfer_ms", "restore_ms", "total_ms",
    "success", "timestamp_utc",
]

# Pod name labels for cleanup (matches metadata.labels.name in workload YAMLs)
WORKLOAD_LABELS = {
    "sysbench_cpu": "sysbench-cpu-pod",
    "sysbench_memory": "sysbench-memory-pod",
    "memcount": "memcount-pod",
}

# Checkpoint directory path used by perform_criu_dump() (hardcoded in live_migration.py)
CHECKPOINT_DIR = "/tmp/checkpoints/migration_checkpoint"


# ── Globals ─────────────────────────────────────────────────────────────────

_all_rows = []
_csv_path = None
_json_path = None
_run_id = None


# ── Kubernetes helpers ───────────────────────────────────────────────────────

def kubectl(*args, capture=True, timeout=60):
    """Run a kubectl command, returning (returncode, stdout, stderr)."""
    cmd = ["kubectl"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        logger.warning(f"[BENCHMARK] kubectl timed out: {' '.join(cmd)}")
        return 1, "", "kubectl timed out"


def get_migrate_pod_name():
    """Dynamically look up the migration service pod name (robust to pod restarts).
    The migration service always runs in the 'monitor' namespace."""
    rc, stdout, stderr = kubectl(
        "get", "pod",
        "-n", "monitor",
        "-l", "name=python-migrate-service",
        "-o", "jsonpath={.items[0].metadata.name}",
        timeout=30,
    )
    if rc != 0 or not stdout.strip():
        logger.warning(f"[BENCHMARK] Could not find migration service pod: {stderr.strip()}")
        return None
    return stdout.strip()


def wait_for_pod_ready(name, namespace, timeout=120):
    """Block until pod is Ready or timeout expires. Returns True on success."""
    rc, _, _ = kubectl(
        "wait", "--for=condition=Ready",
        f"pod/{name}",
        "-n", namespace,
        f"--timeout={timeout}s",
        timeout=timeout + 10,
    )
    return rc == 0


def cleanup_workload_pods(namespace):
    """
    Delete all workload pods and clean up checkpoint directories on all worker nodes.

    Addresses RESEARCH.md Pitfall 2 (checkpoint dir collision) and
    Pitfall 3 (pod naming counter state after failed migration).
    """
    logger.info("[CLEANUP] Removing leftover workload pods and checkpoint directories...")

    # Delete pods by label (one per workload type)
    for workload_key, label_value in WORKLOAD_LABELS.items():
        rc, stdout, stderr = kubectl(
            "delete", "pod",
            "-n", namespace,
            "-l", f"name={label_value}",
            "--ignore-not-found",
            "--wait=false",
            timeout=30,
        )
        if rc != 0:
            logger.warning(f"[CLEANUP] Pod delete warning for {label_value}: {stderr.strip()}")

    # Also delete any pods that may have been renamed with a numeric suffix
    # by CriuMigrationTracker._get_next_pod_name()
    for workload_key, base_name in WORKLOADS.items():
        for suffix in range(0, 10):
            pod_name = f"{base_name}-{suffix}" if suffix > 0 else base_name
            rc, _, _ = kubectl(
                "delete", "pod", pod_name,
                "-n", namespace,
                "--ignore-not-found",
                "--wait=false",
                timeout=20,
            )

    # Clean up checkpoint directories on all three worker nodes
    # (per RESEARCH.md Pitfall 2 — CRIU checkpoint dir not cleaned between runs)
    for region, node in REGION_TO_NODE.items():
        migrator_pod = f"migrator-{node}"
        rc, stdout, stderr = kubectl(
            "exec", "-n", MONITOR_NAMESPACE, migrator_pod,
            "--",
            "rm", "-rf", CHECKPOINT_DIR,
            timeout=30,
        )
        if rc != 0:
            logger.debug(f"[CLEANUP] Checkpoint cleanup on {node}: {stderr.strip()}")

    # Brief pause to allow pod termination to propagate
    time.sleep(3)
    logger.info("[CLEANUP] Done.")


def deploy_workload(workload_key, source_region):
    """
    Deploy workload pod to the specified source region node.

    Reads the YAML template and substitutes the nodeSelector hostname
    with the correct node for source_region, then applies via kubectl.

    Returns the pod name on success, None on failure.
    """
    yaml_path = SCRIPT_DIR / WORKLOAD_YAMLS[workload_key]
    if not yaml_path.exists():
        logger.error(f"[BENCHMARK] Workload YAML not found: {yaml_path}")
        return None

    with open(yaml_path) as f:
        yaml_content = f.read()

    # Replace the nodeSelector hostname with the correct node for source_region
    target_node = REGION_TO_NODE[source_region]
    # Template uses kind-worker as default; replace with the actual target node
    yaml_content = yaml_content.replace(
        "kubernetes.io/hostname: kind-worker",
        f"kubernetes.io/hostname: {target_node}",
    )

    # Apply via kubectl using stdin
    proc = subprocess.run(
        ["kubectl", "apply", "-f", "-", "-n", NAMESPACE],
        input=yaml_content,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        logger.error(f"[BENCHMARK] kubectl apply failed: {proc.stderr.strip()}")
        return None

    pod_name = WORKLOADS[workload_key]
    logger.info(f"[BENCHMARK] Deployed {workload_key} pod '{pod_name}' to {source_region} ({target_node})")
    return pod_name


def extract_timing_from_logs(pod_name, namespace, since_seconds=60):
    """
    Parse checkpoint/transfer/restore durations from migration service pod logs.

    Uses --since with a relative duration to avoid clock skew issues between
    the local machine and KIND cluster nodes. Defaults to 60s lookback which
    covers any single migration.

    Returns dict mapping event name to duration_ms. Warns if > 3 events found.
    """
    rc, stdout, stderr = kubectl(
        "logs", pod_name,
        "-n", namespace,
        f"--since={since_seconds}s",
        timeout=30,
    )
    if rc != 0:
        logger.warning(f"[TIMING] kubectl logs failed: {stderr.strip()}")
        return {}

    timings = {}
    for line in stdout.splitlines():
        try:
            idx = line.index('{')
            record = json.loads(line[idx:])
            event = record.get("event")
            if event in ("checkpoint_complete", "transfer_complete", "restore_complete"):
                timings[event] = record["duration_ms"]
        except (ValueError, json.JSONDecodeError):
            continue

    if len(timings) > 3:
        logger.warning(f"[TIMING] Found {len(timings)} timing events (expected 3) — possible log contamination. Using last 3.")
        # Keep only the last occurrence of each event type if duplicates exist
        # (dict assignment naturally keeps the last value in the loop above)

    return timings


def perform_single_migration(migration_service_url, pod_name, source_node, target_node,
                              target_region, namespace):
    """
    POST /live-migrate to the migration service REST API.

    Returns (success: bool, response_json: dict).
    Captures ISO timestamp just before the call for use with --since-time log filter.
    """
    body = {
        "namespace": namespace,
        "pod": pod_name,
        "source_node": source_node,
        "target_node": target_node,
        "target_region": target_region,
        "delete_original": True,
    }

    try:
        resp = requests.post(
            f"{migration_service_url}/live-migrate",
            json=body,
            timeout=300,
        )
        resp.raise_for_status()
        resp_json = resp.json()
        success = resp_json.get("status", "failed")
        return success, resp_json
    except requests.exceptions.Timeout:
        logger.error("[MIGRATION] Migration request timed out (300s)")
        return "failed", {"error": "timeout"}
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[MIGRATION] Connection error to migration service: {e}")
        return "failed", {"error": str(e)}
    except Exception as e:
        import traceback
        logger.error(f"[MIGRATION] Unexpected error: {e}")
        logger.error(f"[MIGRATION] Traceback: {traceback.format_exc()}")
        return "failed", {"error": str(e)}


def write_csv_row(csv_path, row_dict):
    """
    Append a single row to the CSV file.

    Opens in append mode so partial runs are recoverable (RESEARCH.md anti-pattern warning).
    Writes header only if file is new/empty.
    """
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(row_dict)


def write_metadata_json(json_path, run_id, config, rows):
    """Write full run metadata including config and all migration records."""
    metadata = {
        "run_id": run_id,
        "config": config,
        "total_migrations": len(rows),
        "successful": sum(1 for r in rows if str(r.get("success", "")).lower() == "true"),
        "failed": sum(1 for r in rows if str(r.get("success", "")).lower() != "true"),
        "migrations": rows,
    }
    with open(json_path, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"[OUTPUT] Wrote metadata JSON to {json_path}")


def make_failure_row(run_id, migration_num, workload, src_region, tgt_region, rep, error_msg=""):
    """Build a failure CSV row with empty timing fields."""
    return {
        "run_id": run_id,
        "migration_num": migration_num,
        "workload": workload,
        "source_region": src_region,
        "target_region": tgt_region,
        "repetition": rep,
        "checkpoint_ms": "",
        "transfer_ms": "",
        "restore_ms": "",
        "total_ms": "",
        "success": "false",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


# ── Signal handler for graceful shutdown ────────────────────────────────────

def _on_interrupt(signum, frame):
    """Write metadata JSON on KeyboardInterrupt before exiting."""
    logger.info("[BENCHMARK] Interrupted — writing partial metadata JSON...")
    if _json_path and _run_id is not None:
        try:
            write_metadata_json(_json_path, _run_id, {}, _all_rows)
        except Exception as e:
            logger.error(f"[BENCHMARK] Failed to write metadata on interrupt: {e}")
    sys.exit(1)


signal.signal(signal.SIGINT, _on_interrupt)
signal.signal(signal.SIGTERM, _on_interrupt)


# ── Main benchmark loop ──────────────────────────────────────────────────────

def run_benchmark(args):
    """Drive 54 migrations and collect timing data into CSV + JSON output."""
    global _all_rows, _csv_path, _json_path, _run_id

    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    _run_id = run_id

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = REPO_ROOT / "data" / "overhead-benchmark" / f"run_{run_id}"

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "overhead_raw.csv"
    json_path = out_dir / "overhead_metadata.json"
    _csv_path = csv_path
    _json_path = json_path

    config = {
        "run_id": run_id,
        "out_dir": str(out_dir),
        "repetitions": args.repetitions,
        "migration_service_url": args.migration_service_url,
        "namespace": args.namespace,
        "workloads": list(WORKLOADS.keys()),
        "region_pairs": REGION_PAIRS,
        "total_planned_migrations": len(WORKLOADS) * len(REGION_PAIRS) * args.repetitions,
    }

    logger.info("=" * 80)
    logger.info(f"[BENCHMARK] Starting overhead benchmark run {run_id}")
    logger.info(f"[BENCHMARK] Output directory: {out_dir}")
    logger.info(f"[BENCHMARK] Planned migrations: {config['total_planned_migrations']} "
                f"({len(WORKLOADS)} workloads x {len(REGION_PAIRS)} pairs x {args.repetitions} reps)")
    logger.info("=" * 80)

    # Look up migration service pod name dynamically
    migrate_pod = get_migrate_pod_name()
    if not migrate_pod:
        logger.error("[BENCHMARK] Could not find migration service pod. "
                     "Ensure the migration service is deployed and "
                     "kubectl port-forward is running on localhost:8000.")
        sys.exit(1)
    logger.info(f"[BENCHMARK] Using migration service pod: {migrate_pod}")

    migration_num = 0
    all_rows = []

    for workload in WORKLOADS:
        for (src_region, tgt_region) in REGION_PAIRS:
            for rep in range(1, args.repetitions + 1):
                migration_num += 1
                logger.info("=" * 80)
                logger.info(f"[BENCHMARK] Migration {migration_num}/{config['total_planned_migrations']}: "
                            f"{workload} {src_region}->{tgt_region} rep {rep}/{args.repetitions}")

                try:
                    # Step 1: Cleanup previous workload pods and checkpoint directories
                    cleanup_workload_pods(args.namespace)

                    # Step 2: Deploy workload pod to source node
                    pod_name = deploy_workload(workload, src_region)
                    if not pod_name:
                        logger.error(f"[BENCHMARK] Failed to deploy {workload} to {src_region}")
                        row = make_failure_row(run_id, migration_num, workload,
                                              src_region, tgt_region, rep, "deploy_failed")
                        write_csv_row(csv_path, row)
                        all_rows.append(row)
                        continue

                    # Step 3: Wait for pod Ready
                    logger.info(f"[BENCHMARK] Waiting for pod {pod_name} to be Ready...")
                    if not wait_for_pod_ready(pod_name, args.namespace):
                        logger.error(f"[BENCHMARK] Pod {pod_name} not ready within timeout")
                        row = make_failure_row(run_id, migration_num, workload,
                                              src_region, tgt_region, rep, "pod_not_ready")
                        write_csv_row(csv_path, row)
                        all_rows.append(row)
                        continue

                    # Step 4: Allow workload to fully start (memcount needs time to allocate 256 MB)
                    logger.info("[BENCHMARK] Waiting 5s for workload to initialize...")
                    time.sleep(5)

                    # Step 5: POST /live-migrate
                    source_node = REGION_TO_NODE[src_region]
                    target_node = REGION_TO_NODE[tgt_region]
                    logger.info(f"[MIGRATION] Posting /live-migrate: "
                                f"{pod_name} {source_node}->{target_node}")
                    success, resp = perform_single_migration(
                        args.migration_service_url,
                        pod_name,
                        source_node,
                        target_node,
                        tgt_region,
                        args.namespace,
                    )
                    logger.info(f"[MIGRATION] Result: status={success}")

                    # Step 7: Brief pause for log flush, then extract timing
                    timings = {}
                    if success == "success":
                        time.sleep(2)
                        timings = extract_timing_from_logs(migrate_pod, "monitor")
                        if len(timings) < 3:
                            logger.warning(f"[TIMING] Only {len(timings)}/3 timing events found in logs")

                    # Step 8: Build and write CSV row
                    total_ms = sum(timings.values()) if len(timings) == 3 else ""
                    row = {
                        "run_id": run_id,
                        "migration_num": migration_num,
                        "workload": workload,
                        "source_region": src_region,
                        "target_region": tgt_region,
                        "repetition": rep,
                        "checkpoint_ms": timings.get("checkpoint_complete", ""),
                        "transfer_ms": timings.get("transfer_complete", ""),
                        "restore_ms": timings.get("restore_complete", ""),
                        "total_ms": total_ms,
                        "success": str(success).lower(),
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    }
                    write_csv_row(csv_path, row)
                    all_rows.append(row)
                    logger.info(f"[BENCHMARK] Written row {migration_num}: timings={timings}")

                except Exception as e:
                    import traceback
                    logger.error(f"[BENCHMARK] Unhandled exception in migration {migration_num}: {e}")
                    logger.error(f"[BENCHMARK] Traceback: {traceback.format_exc()}")
                    row = make_failure_row(run_id, migration_num, workload,
                                          src_region, tgt_region, rep, str(e))
                    try:
                        write_csv_row(csv_path, row)
                    except Exception:
                        pass
                    all_rows.append(row)

    # Final cleanup
    cleanup_workload_pods(args.namespace)

    # Write metadata JSON
    _all_rows = all_rows
    write_metadata_json(json_path, run_id, config, all_rows)

    successful = sum(1 for r in all_rows if str(r.get("success", "")).lower() == "true")
    logger.info("=" * 80)
    logger.info(f"[BENCHMARK] Run complete: {successful}/{len(all_rows)} migrations successful")
    logger.info(f"[BENCHMARK] CSV:  {csv_path}")
    logger.info(f"[BENCHMARK] JSON: {json_path}")
    logger.info("=" * 80)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CRIU migration overhead benchmark — drives 54 migrations and collects timing data"
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory (default: data/overhead-benchmark/run_TIMESTAMP)",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Repetitions per workload/region pair combination (default: 3)",
    )
    parser.add_argument(
        "--migration-service-url",
        default="http://localhost:8000",
        help="Migration service base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--namespace",
        default="test-namespace",
        help="Kubernetes namespace for workload pods (default: test-namespace)",
    )
    args = parser.parse_args()
    run_benchmark(args)
