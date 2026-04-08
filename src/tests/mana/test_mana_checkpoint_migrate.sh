#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# MANA checkpoint + migrate test for N-body MPI simulation
#
# Unlike the CRIU-based tests which checkpoint at the OS/kernel level,
# MANA uses DMTCP to transparently checkpoint MPI applications at the
# application level. This means:
#   - No privileged containers needed for checkpointing
#   - MPI state (communicators, buffers) handled transparently
#   - Checkpoint images are portable across nodes
#
# Flow:
#   1. Deploy MPIJob running nbody under mana_launch
#   2. Wait for simulation to start running
#   3. Trigger MANA checkpoint via dmtcp_command
#   4. Transfer checkpoint images to target node
#   5. Restart via mana_restart on target node
#   6. Collect results and compare
# ---------------------------------------------

NAMESPACE="test-namespace"
MPIJOB_YAML="${MPIJOB_YAML:-./tests/mana/mana-mpijob.yml}"
CKPT_DIR="/tmp/mana-ckpt"

# How long to let the simulation run before checkpointing
SLEEP_BEFORE_CKPT="${SLEEP_BEFORE_CKPT:-10}"

# Target node for migration (Kind default)
TARGET_NODE="${TARGET_NODE:-kind-worker2}"
SOURCE_NODE="${SOURCE_NODE:-kind-worker}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --sleep=*)         SLEEP_BEFORE_CKPT="${1#*=}"; shift ;;
    --sleep)           SLEEP_BEFORE_CKPT="$2"; shift 2 ;;
    --target-node=*)   TARGET_NODE="${1#*=}"; shift ;;
    --target-node)     TARGET_NODE="$2"; shift 2 ;;
    --source-node=*)   SOURCE_NODE="${1#*=}"; shift ;;
    --source-node)     SOURCE_NODE="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 [--sleep SECS] [--target-node NODE] [--source-node NODE]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

echo "=== MANA Checkpoint + Migrate Test ==="
echo "Sleep before checkpoint: ${SLEEP_BEFORE_CKPT}s"
echo "Source node:  $SOURCE_NODE"
echo "Target node:  $TARGET_NODE"
echo ""

# ---------------------------------------------
# Helpers
# ---------------------------------------------
k() { kubectl "$@" 2>/dev/null; }

kexec() {
  local pod="$1"; shift
  kubectl exec -n "$NAMESPACE" "$pod" -- "$@"
}

wait_for_running() {
  local pod="$1" timeout="${2:-120}"
  local start now ph
  start="$(date +%s)"
  while true; do
    ph="$(k get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
    if [[ "$ph" == "Running" ]]; then return 0; fi
    if [[ "$ph" == "Succeeded" || "$ph" == "Failed" ]]; then
      echo "Pod $pod already finished (phase=$ph)" >&2; return 1
    fi
    now="$(date +%s)"
    if (( now - start > timeout )); then
      echo "Timed out waiting for $pod (current=$ph)" >&2; return 1
    fi
    sleep 1
  done
}

ts() { date +"%Y%m%d_%H%M%S"; }

OUT_DIR="../data/mana-test/$(ts)"
mkdir -p "$OUT_DIR"

# ---------------------------------------------
# Step 1: Deploy the MPIJob
# ---------------------------------------------
echo "--- Step 1: Deploy MPIJob ---"

k delete mpijob nbody-mana -n "$NAMESPACE" 2>/dev/null || true
k delete pods --all -n "$NAMESPACE" 2>/dev/null || true
sleep 3

kubectl apply -f "$MPIJOB_YAML" -n "$NAMESPACE" >/dev/null
echo "MPIJob applied. Waiting for worker pods..."

WORKER_0=""
WORKER_1=""
for attempt in $(seq 1 60); do
  WORKER_0="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=worker -o jsonpath='{.items[0].metadata.name}' || true)"
  WORKER_1="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=worker -o jsonpath='{.items[1].metadata.name}' || true)"
  if [[ -n "$WORKER_0" && -n "$WORKER_1" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "$WORKER_0" || -z "$WORKER_1" ]]; then
  echo "ERROR: Worker pods did not appear" >&2
  k get pods -n "$NAMESPACE" || true
  exit 1
fi

echo "Worker 0: $WORKER_0"
echo "Worker 1: $WORKER_1"

wait_for_running "$WORKER_0" 120
wait_for_running "$WORKER_1" 120

LAUNCHER="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=launcher -o jsonpath='{.items[0].metadata.name}' || true)"
echo "Launcher: ${LAUNCHER:-not found}"

W0_NODE="$(k get pod "$WORKER_0" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}')"
W1_NODE="$(k get pod "$WORKER_1" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}')"
echo "Worker 0 on node: $W0_NODE"
echo "Worker 1 on node: $W1_NODE"

# ---------------------------------------------
# Step 2: Wait for elastic_nbody to start
# ---------------------------------------------
echo ""
echo "--- Step 2: Wait for elastic_nbody processes ---"

NBODY_PID_0=""
NBODY_PID_1=""
for attempt in $(seq 1 30); do
  NBODY_PID_0="$(kexec "$WORKER_0" sh -c "pgrep -x elastic_nbody | tail -1" 2>/dev/null || true)"
  NBODY_PID_1="$(kexec "$WORKER_1" sh -c "pgrep -x elastic_nbody | tail -1" 2>/dev/null || true)"
  if [[ -n "$NBODY_PID_0" && -n "$NBODY_PID_1" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "$NBODY_PID_0" || -z "$NBODY_PID_1" ]]; then
  echo "ERROR: elastic_nbody not found on both workers" >&2
  echo "Worker 0 processes:"
  kexec "$WORKER_0" ps aux 2>/dev/null || true
  echo "Worker 1 processes:"
  kexec "$WORKER_1" ps aux 2>/dev/null || true
  exit 1
fi

echo "Worker 0 elastic_nbody PID: $NBODY_PID_0"
echo "Worker 1 elastic_nbody PID: $NBODY_PID_1"

# Check for DMTCP coordinator (started by mana_launch on the launcher pod)
echo ""
echo "DMTCP coordinator status:"
if [[ -n "$LAUNCHER" ]]; then
  kexec "$LAUNCHER" sh -c "dmtcp_command -s 2>/dev/null || echo 'coordinator not reachable'" || true
fi

echo ""
echo "Letting simulation run for ${SLEEP_BEFORE_CKPT}s..."
sleep "$SLEEP_BEFORE_CKPT"

# Verify processes are still running
for w in "$WORKER_0" "$WORKER_1"; do
  ph="$(k get pod "$w" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
  if [[ "$ph" != "Running" ]]; then
    echo "ERROR: $w is no longer Running (phase=$ph). Job may have finished." >&2
    exit 1
  fi
done

# ---------------------------------------------
# Step 3: Trigger MANA checkpoint
# ---------------------------------------------
echo ""
echo "--- Step 3: Trigger MANA checkpoint ---"

# dmtcp_command -c tells the DMTCP coordinator to initiate a coordinated
# checkpoint across all ranks. Each rank writes its checkpoint image to
# CKPT_DIR. The coordinator waits for all ranks to reach a consistent
# state (outside MPI calls) before checkpointing.
CKPT_START_MS=$(( $(date +%s) * 1000 ))

set +e
if [[ -n "$LAUNCHER" ]]; then
  echo "Sending checkpoint command via launcher pod..."
  kexec "$LAUNCHER" sh -c "dmtcp_command -c" \
    >"${OUT_DIR}/ckpt_stdout.log" 2>"${OUT_DIR}/ckpt_stderr.log"
  CKPT_RC=$?
else
  # Fallback: try from worker 0
  echo "Sending checkpoint command via worker 0..."
  kexec "$WORKER_0" sh -c "dmtcp_command -c" \
    >"${OUT_DIR}/ckpt_stdout.log" 2>"${OUT_DIR}/ckpt_stderr.log"
  CKPT_RC=$?
fi
set -e

CKPT_END_MS=$(( $(date +%s) * 1000 ))
CKPT_TIME_MS=$((CKPT_END_MS - CKPT_START_MS))

echo "Checkpoint command: rc=$CKPT_RC time=${CKPT_TIME_MS}ms"

if [[ $CKPT_RC -ne 0 ]]; then
  echo "Checkpoint stdout:"
  cat "${OUT_DIR}/ckpt_stdout.log" 2>/dev/null || true
  echo "Checkpoint stderr:"
  cat "${OUT_DIR}/ckpt_stderr.log" 2>/dev/null || true
  echo ""
  echo "CHECKPOINT FAILED. See logs in $OUT_DIR"
  exit 1
fi

echo "CHECKPOINT SUCCEEDED"

# List checkpoint files
echo ""
echo "Checkpoint files (Worker 0):"
kexec "$WORKER_0" ls -lh "$CKPT_DIR" 2>/dev/null | head -15 || true
echo ""
echo "Checkpoint files (Worker 1):"
kexec "$WORKER_1" ls -lh "$CKPT_DIR" 2>/dev/null | head -15 || true

# ---------------------------------------------
# Step 4: Transfer checkpoint images to target node
# ---------------------------------------------
echo ""
echo "--- Step 4: Transfer checkpoint images ---"

# Since CKPT_DIR is a hostPath volume, checkpoint images are already on
# the node's filesystem. For cross-node migration we need to copy them.
#
# Strategy: copy checkpoint images from source workers to a staging area,
# then into the target pod.

STAGING_DIR="${OUT_DIR}/ckpt-staging"
mkdir -p "$STAGING_DIR/worker-0" "$STAGING_DIR/worker-1"

echo "Copying checkpoint images from workers..."
kubectl cp "$NAMESPACE/$WORKER_0:$CKPT_DIR" "$STAGING_DIR/worker-0/" 2>/dev/null || true
kubectl cp "$NAMESPACE/$WORKER_1:$CKPT_DIR" "$STAGING_DIR/worker-1/" 2>/dev/null || true

echo "Staged checkpoint files:"
ls -lhR "$STAGING_DIR" 2>/dev/null | head -30 || true

# ---------------------------------------------
# Step 5: Kill original job, deploy restart pod
# ---------------------------------------------
echo ""
echo "--- Step 5: Kill original job and deploy restart pod ---"

k delete mpijob nbody-mana -n "$NAMESPACE" 2>/dev/null || true
sleep 5

# Deploy a restart pod on the target node. This pod uses mana_restart
# to resume the simulation from checkpoint images.
RESTART_POD="nbody-mana-restart"

cat > "${OUT_DIR}/restart-pod.yaml" <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${RESTART_POD}
  namespace: ${NAMESPACE}
  labels:
    name: ${RESTART_POD}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${TARGET_NODE}
  containers:
  - name: mana-restart
    image: nbody-mana:local
    imagePullPolicy: IfNotPresent
    command: ["/usr/bin/tini", "--"]
    args: ["/bin/bash", "-c", "/tmp/run_nbody_mana.sh --restart --ckpt-dir=${CKPT_DIR}"]
    resources:
      requests:
        memory: "256Mi"
        cpu: "500m"
      limits:
        memory: "512Mi"
        cpu: "1000m"
    volumeMounts:
    - name: mana-ckpt
      mountPath: ${CKPT_DIR}
    - name: checkpoint-volume
      mountPath: /tmp/checkpoints
    - name: script-data
      mountPath: /script-data
    - name: results
      mountPath: /results
  volumes:
  - name: mana-ckpt
    hostPath:
      path: /tmp/mana-ckpt
      type: DirectoryOrCreate
  - name: checkpoint-volume
    hostPath:
      path: /tmp/checkpoints
      type: DirectoryOrCreate
  - name: script-data
    emptyDir: {}
  - name: results
    emptyDir: {}
YAML

# If cross-node, copy checkpoint images to target node via the restart pod
kubectl apply -f "${OUT_DIR}/restart-pod.yaml" -n "$NAMESPACE" >/dev/null
echo "Restart pod deployed on $TARGET_NODE"

wait_for_running "$RESTART_POD" 120

# Copy staged checkpoint images into the restart pod
if [[ "$SOURCE_NODE" != "$TARGET_NODE" ]]; then
  echo "Cross-node migration: copying checkpoint images to restart pod..."
  kubectl cp "$STAGING_DIR/worker-0/" "$NAMESPACE/$RESTART_POD:$CKPT_DIR/" 2>/dev/null || true
fi

# ---------------------------------------------
# Step 6: Monitor restart
# ---------------------------------------------
echo ""
echo "--- Step 6: Monitor restarted simulation ---"

RESTART_START_MS=$(( $(date +%s) * 1000 ))

echo "Waiting for restart pod to complete (timeout: 600s)..."
for i in $(seq 1 600); do
  ph="$(k get pod "$RESTART_POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
  if [[ "$ph" == "Succeeded" || "$ph" == "Failed" ]]; then
    break
  fi
  if (( i % 30 == 0 )); then
    echo "  Still running... (${i}s elapsed, phase=$ph)"
  fi
  sleep 1
done

RESTART_END_MS=$(( $(date +%s) * 1000 ))
RESTART_TIME_MS=$((RESTART_END_MS - RESTART_START_MS))

RESTART_PHASE="$(k get pod "$RESTART_POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
RESTART_NODE="$(k get pod "$RESTART_POD" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}' || true)"

echo "Restart pod phase: $RESTART_PHASE on node: $RESTART_NODE"
echo "Restart time: ${RESTART_TIME_MS}ms"

# Collect logs
k logs -n "$NAMESPACE" "$RESTART_POD" > "${OUT_DIR}/restart_kubectl_logs.log" 2>&1 || true

echo ""
echo "Restart pod logs (last 20 lines):"
tail -20 "${OUT_DIR}/restart_kubectl_logs.log" 2>/dev/null || true

# ---------------------------------------------
# Summary
# ---------------------------------------------
echo ""
echo "=== Summary ==="
echo "Checkpoint: rc=$CKPT_RC time=${CKPT_TIME_MS}ms"
echo "Restart:    phase=$RESTART_PHASE time=${RESTART_TIME_MS}ms"
echo "Source:     $SOURCE_NODE"
echo "Target:     $RESTART_NODE"
echo "Logs:       $OUT_DIR"

# Write results CSV
results_csv="${OUT_DIR}/results.csv"
echo "timestamp,checkpoint_rc,checkpoint_time_ms,restart_phase,restart_time_ms,source_node,target_node" > "$results_csv"
echo "$(ts),$CKPT_RC,$CKPT_TIME_MS,$RESTART_PHASE,$RESTART_TIME_MS,$SOURCE_NODE,$RESTART_NODE" >> "$results_csv"

echo "Results CSV: $results_csv"
echo "DONE."
