#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# MPI two-pod run-to-completion test
#
# Deploys a 2-rank MPI N-body simulation across two worker pods, waits for
# it to finish, and collects results. No checkpoint/restore — this verifies
# that the distributed workload runs correctly end-to-end.
#
# Architecture (MPI Operator):
#   Launcher pod: runs mpirun, SSH's into workers
#   Worker-0 pod: sshd -> orted -> elastic_nbody (rank 0)
#   Worker-1 pod: sshd -> orted -> elastic_nbody (rank 1)
#   Ranks communicate via TCP
#
# Output (saved to ../data/mpi-run-test/<timestamp>/):
#   - launcher_logs.log         launcher pod stdout/stderr
#   - worker0_logs.log          worker 0 kubectl logs (if still available)
#   - worker1_logs.log          worker 1 kubectl logs (if still available)
#   - worker0_results/          per-rank CSV files from worker 0 (if pods survive)
#   - worker1_results/          per-rank CSV files from worker 1 (if pods survive)
#   - results.csv               summary row (timestamp, bodies, iters, etc.)
# ---------------------------------------------

NAMESPACE="test-namespace"
MPIJOB_YAML="${MPIJOB_YAML:-./tests/antibody-sim/nbody-mpijob.yml}"

# Job timeout (seconds) — how long to wait for the launcher to finish
JOB_TIMEOUT="${JOB_TIMEOUT:-600}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --yaml=*)     MPIJOB_YAML="${1#*=}"; shift ;;
    --yaml)       MPIJOB_YAML="$2"; shift 2 ;;
    --timeout=*)  JOB_TIMEOUT="${1#*=}"; shift ;;
    --timeout)    JOB_TIMEOUT="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 [--yaml PATH] [--timeout SECS]"
      echo ""
      echo "  --yaml PATH     MPIJob manifest (default: ./tests/antibody-sim/nbody-mpijob.yml)"
      echo "  --timeout SECS  Max wait for launcher completion (default: 600)"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

echo "=== MPI Two-Pod Run-to-Completion Test ==="
echo "YAML:    $MPIJOB_YAML"
echo "Timeout: ${JOB_TIMEOUT}s"
echo ""

# ---------------------------------------------
# Helpers
# ---------------------------------------------
k() { kubectl "$@" 2>/dev/null; }

kexec_worker() {
  local worker="$1"; shift
  kubectl exec -n "$NAMESPACE" "$worker" -c worker -- "$@"
}

ts() { date +"%Y%m%d_%H%M%S"; }

OUT_DIR="../data/mpi-run-test/$(ts)"
mkdir -p "$OUT_DIR"

# ---------------------------------------------
# Step 1: Deploy the MPIJob
# ---------------------------------------------
echo "--- Step 1: Deploy MPIJob ---"

# Clean up any existing job
k delete mpijob nbody-sim -n "$NAMESPACE" 2>/dev/null || true
# Wait for pods to terminate
for i in $(seq 1 30); do
  COUNT="$(k get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$COUNT" == "0" ]]; then break; fi
  sleep 1
done

JOB_START="$(date +%s)"
kubectl apply -f "$MPIJOB_YAML" -n "$NAMESPACE" >/dev/null
echo "MPIJob applied."

# ---------------------------------------------
# Step 2: Wait for worker pods and record placement
# ---------------------------------------------
echo ""
echo "--- Step 2: Wait for worker pods ---"

WORKER_0=""
WORKER_1=""
for attempt in $(seq 1 60); do
  WORKER_0="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=worker -o jsonpath='{.items[0].metadata.name}' || true)"
  WORKER_1="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=worker -o jsonpath='{.items[1].metadata.name}' || true)"
  if [[ -n "$WORKER_0" && -n "$WORKER_1" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$WORKER_0" || -z "$WORKER_1" ]]; then
  echo "ERROR: Worker pods did not appear" >&2
  k get pods -n "$NAMESPACE" || true
  exit 1
fi

W0_NODE="$(k get pod "$WORKER_0" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}' || true)"
W1_NODE="$(k get pod "$WORKER_1" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}' || true)"
echo "Worker 0: $WORKER_0 (node: $W0_NODE)"
echo "Worker 1: $WORKER_1 (node: $W1_NODE)"

# Wait for launcher pod
LAUNCHER=""
for attempt in $(seq 1 30); do
  LAUNCHER="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=launcher -o jsonpath='{.items[0].metadata.name}' || true)"
  if [[ -n "$LAUNCHER" ]]; then break; fi
  sleep 1
done
echo "Launcher: ${LAUNCHER:-not found}"

# ---------------------------------------------
# Step 3: Wait for the launcher to complete
# ---------------------------------------------
echo ""
echo "--- Step 3: Waiting for job to complete (timeout=${JOB_TIMEOUT}s) ---"

if [[ -z "$LAUNCHER" ]]; then
  echo "ERROR: Launcher pod not found" >&2
  exit 1
fi

# Poll for launcher completion
LAUNCHER_PHASE=""
start="$(date +%s)"
while true; do
  LAUNCHER_PHASE="$(k get pod "$LAUNCHER" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
  if [[ "$LAUNCHER_PHASE" == "Succeeded" || "$LAUNCHER_PHASE" == "Failed" ]]; then
    break
  fi
  now="$(date +%s)"
  if (( now - start > JOB_TIMEOUT )); then
    echo "Timed out waiting for launcher (current phase=$LAUNCHER_PHASE)" >&2
    break
  fi
  sleep 2
done

JOB_END="$(date +%s)"
JOB_DURATION=$(( JOB_END - JOB_START ))

echo "Launcher phase: $LAUNCHER_PHASE (wall time: ${JOB_DURATION}s)"

# ---------------------------------------------
# Step 4: Collect results
# ---------------------------------------------
echo ""
echo "--- Step 4: Collect results ---"

# Launcher logs (contains avg iteration time from elastic_nbody stdout)
k logs -n "$NAMESPACE" "$LAUNCHER" > "${OUT_DIR}/launcher_logs.log" 2>&1 || true
echo "Saved launcher logs."

# Worker kubectl logs (may already be gone if cleanPodPolicy: Running)
k logs -n "$NAMESPACE" "$WORKER_0" -c worker > "${OUT_DIR}/worker0_logs.log" 2>&1 || true
k logs -n "$NAMESPACE" "$WORKER_1" -c worker > "${OUT_DIR}/worker1_logs.log" 2>&1 || true

# Try to copy per-rank result files from workers. Workers are likely deleted
# already (cleanPodPolicy: Running), so this is best-effort.
for idx in 0 1; do
  eval "w=\$WORKER_$idx"
  result_dir="${OUT_DIR}/worker${idx}_results"
  mkdir -p "$result_dir"

  ph="$(k get pod "$w" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo 'Gone')"
  if [[ "$ph" == "Running" ]]; then
    kexec_worker "$w" sh -c "find /results -type f 2>/dev/null" 2>/dev/null | while read -r fpath; do
      local_path="${result_dir}${fpath#/results}"
      mkdir -p "$(dirname "$local_path")"
      kubectl cp -n "$NAMESPACE" -c worker "${w}:${fpath}" "$local_path" 2>/dev/null || true
    done
    echo "Copied worker $idx result files."
  else
    echo "Worker $idx already gone (phase=$ph), skipping file collection."
    rmdir "$result_dir" 2>/dev/null || true
  fi
done

# Parse the avg iteration time from launcher logs.
# elastic_nbody prints a single float (avg seconds/iteration) to stdout.
# With 2 ranks mpirun may collect two lines — take the first.
AVG_ITER_TIME="$(grep -E '^[0-9]+\.?[0-9]*e?[-+]?[0-9]*$' "${OUT_DIR}/launcher_logs.log" | head -1 || true)"

# Write summary CSV
RESULTS_CSV="${OUT_DIR}/results.csv"
{
  echo "timestamp,launcher_phase,wall_time_s,avg_iter_time_s,worker0_node,worker1_node,yaml"
  echo "$(ts),$LAUNCHER_PHASE,$JOB_DURATION,${AVG_ITER_TIME:-},${W0_NODE:-},${W1_NODE:-},$(basename "$MPIJOB_YAML")"
} > "$RESULTS_CSV"

# ---------------------------------------------
# Summary
# ---------------------------------------------
echo ""
echo "=== Summary ==="
echo "Launcher:        $LAUNCHER_PHASE"
echo "Wall time:       ${JOB_DURATION}s"
echo "Avg iter time:   ${AVG_ITER_TIME:-N/A} s"
echo "Worker 0 node:   ${W0_NODE:-unknown}"
echo "Worker 1 node:   ${W1_NODE:-unknown}"
echo "Results:         $OUT_DIR"

if [[ "$LAUNCHER_PHASE" == "Succeeded" ]]; then
  echo ""
  echo "SUCCESS: MPI job ran to completion across two pods."
else
  echo ""
  echo "FAILURE: Launcher phase=$LAUNCHER_PHASE (expected Succeeded)."
  echo ""
  echo "Launcher logs:"
  cat "${OUT_DIR}/launcher_logs.log" 2>/dev/null || true
  exit 1
fi

echo "DONE."
