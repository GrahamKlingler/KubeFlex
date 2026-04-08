#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# CRIU same-pod checkpoint/restore test for N-body
#
# Deploys a pod, starts the nbody simulation, checkpoints it with CRIU
# (which kills the original), then restores from checkpoint — all inside
# the same pod. Pure CRIU sanity check, no migration machinery involved.
#
# Key design: the pod runs "run_nbody.sh & sleep infinity" so that PID 1
# (tini -> bash) stays alive after CRIU kills the nbody subtree during
# dump. This lets us exec back in to run the restore.
# ---------------------------------------------

NAMESPACE="test-namespace"
POD_NAME="${POD_NAME:-nbody-criu-test}"
CHECKPOINT_DIR="/tmp/checkpoints/criu-test"
IMAGE="${IMAGE:-nbody-mpi:local}"

# Simulation params — needs to run long enough to checkpoint mid-run
BODIES="${BODIES:-5000}"
ITERS="${ITERS:-500}"
CHECKPOINT="${CHECKPOINT:-50}"

# How many seconds to let the simulation run before checkpointing
SLEEP_BEFORE_DUMP="${SLEEP_BEFORE_DUMP:-5}"

# Node to schedule on
NODE="${NODE:-kind-worker}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --bodies=*)  BODIES="${1#*=}"; shift ;;
    --bodies)    BODIES="$2"; shift 2 ;;
    --iters=*)   ITERS="${1#*=}"; shift ;;
    --iters)     ITERS="$2"; shift 2 ;;
    --sleep=*)   SLEEP_BEFORE_DUMP="${1#*=}"; shift ;;
    --sleep)     SLEEP_BEFORE_DUMP="$2"; shift 2 ;;
    --node=*)    NODE="${1#*=}"; shift ;;
    --node)      NODE="$2"; shift 2 ;;
    --pod=*)     POD_NAME="${1#*=}"; shift ;;
    --pod)       POD_NAME="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 [--bodies N] [--iters N] [--sleep SECS] [--node NODE] [--pod NAME]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

echo "=== CRIU Same-Pod Checkpoint/Restore Test ==="
echo "Pod:         $POD_NAME"
echo "Node:        $NODE"
echo "Bodies:      $BODIES"
echo "Iterations:  $ITERS"
echo "Sleep before dump: ${SLEEP_BEFORE_DUMP}s"
echo ""

# ---------------------------------------------
# Helpers
# ---------------------------------------------
k() { kubectl "$@" 2>/dev/null; }
kexec() { kubectl exec -n "$NAMESPACE" "$POD_NAME" -- "$@"; }

pod_exists() { k get pod "$1" -n "$NAMESPACE" >/dev/null 2>&1; }

wait_for_running() {
  local pod="$1" timeout="${2:-120}"
  local start now ph
  start="$(date +%s)"
  while true; do
    ph="$(k get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
    if [[ "$ph" == "Running" ]]; then
      return 0
    fi
    if [[ "$ph" == "Succeeded" || "$ph" == "Failed" ]]; then
      echo "Pod $pod already finished (phase=$ph)" >&2
      return 1
    fi
    now="$(date +%s)"
    if (( now - start > timeout )); then
      echo "Timed out waiting for $pod to reach Running (current=$ph)" >&2
      return 1
    fi
    sleep 1
  done
}

cleanup() {
  echo ""
  echo "--- Cleanup ---"
  pod_exists "$POD_NAME" && kubectl delete pod "$POD_NAME" -n "$NAMESPACE" --wait=false >/dev/null 2>&1 || true
}
# trap cleanup EXIT

# ---------------------------------------------
# Step 1: Deploy the pod
# ---------------------------------------------
k delete pods --all -n "$NAMESPACE"
echo "--- Step 1: Deploy pod ---"

pod_exists "$POD_NAME" && kubectl delete pod "$POD_NAME" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true

# Generate YAML inline. The command runs run_nbody.sh in the BACKGROUND
# alongside "sleep infinity". This keeps PID 1 (tini -> bash) alive after
# CRIU kills the nbody subtree during dump, so we can still kubectl exec
# to run the restore.
TMPYAML="$(mktemp)"
cat > "$TMPYAML" <<YAMLEOF
apiVersion: v1
kind: Pod
metadata:
  name: ${POD_NAME}
  namespace: ${NAMESPACE}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${NODE}
  containers:
  - name: test-container
    image: ${IMAGE}
    imagePullPolicy: IfNotPresent
    command: ["/usr/bin/tini", "--"]
    args:
    - /bin/bash
    - -c
    - |
      echo 'Test pod started'
      /tmp/run_nbody.sh --bodies=${BODIES} --iters=${ITERS} --checkpoint-interval=${CHECKPOINT} --results-folder=/results/ &
      NBODY_PID=\$!
      echo "nbody background PID: \$NBODY_PID"
      # Keep the container alive regardless of nbody's fate
      wait \$NBODY_PID 2>/dev/null || true
      echo "nbody process finished or was killed"
      sleep infinity
    securityContext:
      privileged: true
      capabilities:
        add:
        - SYS_PTRACE
        - SYS_RESOURCE
        - NET_ADMIN
        - SYS_ADMIN
        - SYS_TIME
        - CHECKPOINT_RESTORE
        - SYS_CHROOT
        - SETPCAP
        - SETGID
        - SETUID
      seccompProfile:
        type: Unconfined
      allowPrivilegeEscalation: true
    resources:
      requests:
        memory: "256Mi"
        cpu: "500m"
      limits:
        memory: "512Mi"
        cpu: "1000m"
    volumeMounts:
    - name: checkpoint-volume
      mountPath: /tmp/checkpoints
    - name: script-data
      mountPath: /script-data
    - name: results
      mountPath: /results
  volumes:
  - name: checkpoint-volume
    hostPath:
      path: /tmp/checkpoints
      type: DirectoryOrCreate
  - name: script-data
    emptyDir: {}
  - name: results
    emptyDir: {}
YAMLEOF

kubectl apply -f "$TMPYAML" -n "$NAMESPACE" >/dev/null
rm -f "$TMPYAML"

echo "Waiting for pod to be Running..."
wait_for_running "$POD_NAME"
echo "Pod $POD_NAME is Running on node $(k get pod "$POD_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}')"

# ---------------------------------------------
# Step 2: Let simulation run, then find the PID
# ---------------------------------------------
echo ""
echo "--- Step 2: Let simulation run for ${SLEEP_BEFORE_DUMP}s ---"
sleep "$SLEEP_BEFORE_DUMP"

echo "Process tree inside pod:"
kexec ps auxf || kexec ps aux || true
echo ""

# Find the elastic_nbody_nompi PID directly. No MPI runtime, no orted —
# clean process tree for CRIU. Falls back to elastic_nbody if nompi
# binary isn't found (e.g., old image).
NBODY_PID="$(kexec sh -c "pgrep -f elastic_nbody_nompi | head -1" || true)"
if [[ -z "$NBODY_PID" ]]; then
  NBODY_PID="$(kexec sh -c "pgrep -f elastic_nbody | head -1" || true)"
fi

if [[ -z "$NBODY_PID" ]]; then
  echo "ERROR: Could not find elastic_nbody PID" >&2
  echo "Full process list:"
  kexec ps aux || true
  exit 1
fi
echo "elastic_nbody PID: $NBODY_PID"
kexec ps -p "$NBODY_PID" -o pid,ppid,comm || true

# ---------------------------------------------
# Step 3: CRIU dump (checkpoint + kill)
# ---------------------------------------------
echo ""
echo "--- Step 3: CRIU dump (no --leave-running, kills process after dump) ---"

kexec rm -rf "$CHECKPOINT_DIR"
kexec mkdir -p "$CHECKPOINT_DIR"

DUMP_CMD="criu dump -t $NBODY_PID -D $CHECKPOINT_DIR"
DUMP_CMD+=" --shell-job"
DUMP_CMD+=" --tcp-close"
DUMP_CMD+=" -o /tmp/dump.log -v4"

echo "Running: $DUMP_CMD"
if kexec sh -c "$DUMP_CMD"; then
  echo "CRIU dump SUCCEEDED (process tree killed by CRIU)"
else
  dump_rc=$?
  echo "CRIU dump FAILED (rc=$dump_rc)"
  echo ""
  echo "--- Dump log (last 50 lines) ---"
  kexec sh -c "tail -50 /tmp/dump.log" 2>/dev/null || echo "(no dump log)"
  exit 1
fi

echo ""
echo "Checkpoint files:"
kexec ls -lh "$CHECKPOINT_DIR" | head -20 || true

# Verify the processes are gone and pod is still alive
echo ""
echo "Process tree after dump (nbody should be gone):"
kexec ps auxf || kexec ps aux || true

POD_PHASE="$(k get pod "$POD_NAME" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
echo "Pod phase: $POD_PHASE"
if [[ "$POD_PHASE" != "Running" ]]; then
  echo "ERROR: Pod is no longer Running (phase=$POD_PHASE). Cannot restore." >&2
  exit 1
fi

# ---------------------------------------------
# Step 4: CRIU restore
# ---------------------------------------------
echo ""
echo "--- Step 4: CRIU restore ---"

RESTORE_CMD="criu restore -D $CHECKPOINT_DIR --restore-detached"
RESTORE_CMD+=" --shell-job"
RESTORE_CMD+=" --tcp-close"
RESTORE_CMD+=" --pidfile /tmp/restored.pid"
RESTORE_CMD+=" -o /tmp/restore.log -v4"

echo "Running: $RESTORE_CMD"
if kexec sh -c "$RESTORE_CMD"; then
  echo "CRIU restore SUCCEEDED"
else
  restore_rc=$?
  echo "CRIU restore FAILED (rc=$restore_rc)"
  echo ""
  echo "--- Restore log (last 50 lines) ---"
  kexec sh -c "tail -50 /tmp/restore.log" 2>/dev/null || echo "(no restore log)"
  exit 1
fi

sleep 2

# Show what's running now
RESTORED_PID="$(kexec cat /tmp/restored.pid 2>/dev/null || echo '')"
echo "Restored PID: ${RESTORED_PID:-unknown}"
echo ""
echo "Process tree after restore:"
kexec ps auxf || kexec ps aux || true

# ---------------------------------------------
# Step 5: Wait for restored process to finish
# ---------------------------------------------
echo ""
echo "--- Step 5: Wait for restored process to complete ---"

if [[ -n "$RESTORED_PID" ]]; then
  WAIT_TIMEOUT=600
  ELAPSED=0
  while kexec sh -c "kill -0 $RESTORED_PID 2>/dev/null" && (( ELAPSED < WAIT_TIMEOUT )); do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if (( ELAPSED % 30 == 0 )); then
      echo "  Still waiting... (${ELAPSED}s elapsed)"
      kexec ps -p "$RESTORED_PID" -o pid,ppid,comm,etime 2>/dev/null || echo "  (process gone)"
    fi
  done

  if (( ELAPSED >= WAIT_TIMEOUT )); then
    echo "TIMEOUT: Restored process still running after ${WAIT_TIMEOUT}s"
    echo "Process state:"
    kexec ps auxf || kexec ps aux || true
    exit 1
  fi

  echo "Restored process finished after ~${ELAPSED}s"
else
  echo "WARNING: No restored PID found, cannot wait"
fi

# ---------------------------------------------
# Step 6: Check results
# ---------------------------------------------
echo ""
echo "--- Step 6: Results ---"

echo ""
echo "=== Pod logs (kubectl logs) ==="
kubectl logs -n "$NAMESPACE" "$POD_NAME" 2>/dev/null | tail -20 || echo "(no logs)"

echo ""
echo "=== Container log file ==="
kexec cat /script-data/container.log 2>/dev/null | tail -20 || echo "(no container.log)"

echo ""
echo "=== Summary file ==="
kexec cat /tmp/checkpoints/summary.txt 2>/dev/null || echo "(no summary.txt)"

# Check for SUMMARY line
SUMMARY="$(kexec cat /script-data/container.log 2>/dev/null | grep 'SUMMARY ' | tail -1 || true)"
if [[ -z "$SUMMARY" ]]; then
  SUMMARY="$(kexec cat /tmp/checkpoints/summary.txt 2>/dev/null | grep 'SUMMARY ' | tail -1 || true)"
fi

echo ""
if [[ -n "$SUMMARY" ]]; then
  echo "SUCCESS: Found SUMMARY line:"
  echo "  $SUMMARY"
else
  echo "FAILURE: No SUMMARY line found — simulation did not complete after restore"
fi

echo ""
echo "DONE."
