#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# CRIU two-pod MPI dump/restore test
#
# Starts a 2-rank MPI N-body job, then CRIU dumps the ORTED PROCESS TREE
# (orted + elastic_nbody) on BOTH worker pods sequentially, and restores them.
#
# Architecture (MPI Operator):
#   Launcher pod: runs mpirun, SSH's into workers
#   Worker-0 pod: sshd -> orted -> elastic_nbody (rank 0)
#   Worker-1 pod: sshd -> orted -> elastic_nbody (rank 1)
#   Ranks communicate via TCP (MPI over SSH tunnels)
#
# Why dump orted (not elastic_nbody directly):
#   elastic_nbody's stdout/stderr are PTY slaves created by orted. The PTY
#   master lives in orted. If we only dump elastic_nbody, CRIU fails on
#   restore with "Found slave peer index 0 without correspond master peer".
#   Dumping the orted tree captures both master and slave in one tree.
#
# Why the launcher doesn't matter:
#   orted's connection to sshd/launcher are pipes (sshd shows root@notty).
#   These pipe FDs are handled by --shell-job during dump and replaced with
#   /dev/null via --inherit-fd during restore.
# ---------------------------------------------

NAMESPACE="test-namespace"
MPIJOB_YAML="${MPIJOB_YAML:-./tests/antibody-sim/nbody-mpijob-long.yml}"
CHECKPOINT_DIR="/tmp/checkpoints/criu-mpi-test"

# How long to let the simulation run before attempting dump
SLEEP_BEFORE_DUMP="${SLEEP_BEFORE_DUMP:-5}"

# TCP mode: "close" or "established"
TCP_MODE="${TCP_MODE:-close}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --sleep=*)     SLEEP_BEFORE_DUMP="${1#*=}"; shift ;;
    --sleep)       SLEEP_BEFORE_DUMP="$2"; shift 2 ;;
    --tcp-mode=*)  TCP_MODE="${1#*=}"; shift ;;
    --tcp-mode)    TCP_MODE="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 [--sleep SECS] [--tcp-mode close|established]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

TCP_FLAG="--tcp-close"
if [[ "$TCP_MODE" == "established" ]]; then
  TCP_FLAG="--tcp-established"
fi

echo "=== CRIU Two-Pod MPI Dump/Restore Test ==="
echo "TCP mode:    $TCP_MODE ($TCP_FLAG)"
echo "Sleep before dump: ${SLEEP_BEFORE_DUMP}s"
echo ""

# ---------------------------------------------
# Helpers
# ---------------------------------------------
k() { kubectl "$@" 2>/dev/null; }

kexec_worker() {
  local worker="$1"; shift
  kubectl exec -n "$NAMESPACE" "$worker" -c worker -- "$@"
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

OUT_DIR="../data/mpi-criu-test/$(ts)"
mkdir -p "$OUT_DIR"

# ---------------------------------------------
# Step 1: Deploy the MPIJob
# ---------------------------------------------
echo "--- Step 1: Deploy MPIJob ---"

# Clean up any existing job
k delete mpijob nbody-sim -n "$NAMESPACE" 2>/dev/null || true
k delete pods --all -n "$NAMESPACE" 2>/dev/null || true
sleep 3

kubectl apply -f "$MPIJOB_YAML" -n "$NAMESPACE" >/dev/null
echo "MPIJob applied. Waiting for worker pods..."

# Wait for worker pods to appear and be running
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

W0_NODE="$(k get pod "$WORKER_0" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}')"
W1_NODE="$(k get pod "$WORKER_1" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}')"
echo "Worker 0 on node: $W0_NODE"
echo "Worker 1 on node: $W1_NODE"

# Also find the launcher
LAUNCHER="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=launcher -o jsonpath='{.items[0].metadata.name}' || true)"
echo "Launcher: ${LAUNCHER:-not found}"

# ---------------------------------------------
# Step 2: Wait for elastic_nbody to start on both workers
# ---------------------------------------------
echo ""
echo "--- Step 2: Wait for elastic_nbody processes ---"

# mpirun takes a moment to SSH in and start the processes
NBODY_PID_0=""
NBODY_PID_1=""
for attempt in $(seq 1 30); do
  # Use pgrep -x for exact process name match. pgrep -f matches the full
  # cmdline which also hits orted (whose cmdline includes "elastic_nbody"
  # as the binary it launches), giving us the wrong PID.
  NBODY_PID_0="$(kexec_worker "$WORKER_0" sh -c "pgrep -x elastic_nbody | tail -1" 2>/dev/null || true)"
  NBODY_PID_1="$(kexec_worker "$WORKER_1" sh -c "pgrep -x elastic_nbody | tail -1" 2>/dev/null || true)"
  if [[ -n "$NBODY_PID_0" && -n "$NBODY_PID_1" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "$NBODY_PID_0" || -z "$NBODY_PID_1" ]]; then
  echo "ERROR: elastic_nbody not found on both workers" >&2
  echo "Worker 0 processes:"
  kexec_worker "$WORKER_0" ps aux 2>/dev/null || true
  echo "Worker 1 processes:"
  kexec_worker "$WORKER_1" ps aux 2>/dev/null || true
  exit 1
fi

echo "Worker 0 elastic_nbody PID: $NBODY_PID_0"
echo "Worker 1 elastic_nbody PID: $NBODY_PID_1"

echo ""
echo "Worker 0 process tree:"
kexec_worker "$WORKER_0" ps auxf 2>/dev/null || kexec_worker "$WORKER_0" ps aux || true

echo ""
echo "Worker 1 process tree:"
kexec_worker "$WORKER_1" ps auxf 2>/dev/null || kexec_worker "$WORKER_1" ps aux || true

# Let the simulation run for a bit before dumping
echo ""
echo "Letting simulation run for ${SLEEP_BEFORE_DUMP}s..."
sleep "$SLEEP_BEFORE_DUMP"

# Verify processes are still running
for w in "$WORKER_0" "$WORKER_1"; do
  ph="$(k get pod "$w" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
  if [[ "$ph" != "Running" ]]; then
    echo "ERROR: $w is no longer Running (phase=$ph). Job may have finished." >&2
    exit 1
  fi
done

# Check network connections between ranks
echo ""
echo "--- Network connections (Worker 0) ---"
kexec_worker "$WORKER_0" sh -c "ss -tnp 2>/dev/null | head -20 || netstat -tnp 2>/dev/null | head -20" || true

echo ""
echo "--- Network connections (Worker 1) ---"
kexec_worker "$WORKER_1" sh -c "ss -tnp 2>/dev/null | head -20 || netstat -tnp 2>/dev/null | head -20" || true

# ---------------------------------------------
# Step 3: CRIU dump on both workers
# ---------------------------------------------
echo ""
echo "--- Step 3: CRIU dump on both workers (tcp_mode=$TCP_MODE) ---"

# Prepare checkpoint directories
kexec_worker "$WORKER_0" rm -rf "$CHECKPOINT_DIR" 2>/dev/null || true
kexec_worker "$WORKER_0" mkdir -p "$CHECKPOINT_DIR" 2>/dev/null || true
kexec_worker "$WORKER_1" rm -rf "$CHECKPOINT_DIR" 2>/dev/null || true
kexec_worker "$WORKER_1" mkdir -p "$CHECKPOINT_DIR" 2>/dev/null || true

# Strategy: SIGSTOP orted on both workers, then dump the orted tree sequentially.
#
# Why dump orted tree (not just elastic_nbody):
#   - elastic_nbody's stdout/stderr are PTY slaves; the PTY master is in orted.
#   - Dumping only elastic_nbody fails on restore: "Found slave peer index 0
#     without correspond master peer". Dumping orted captures both ends.
#
# Why SIGSTOP + sequential works:
#   - SIGSTOP on orted freezes orted + elastic_nbody (same process group).
#     CRIU handles already-stopped processes fine.
#   - When CRIU dumps worker 0 (kills orted tree), the TCP connection to
#     worker 1 breaks. But worker 1 is frozen so nothing reacts.
#   - orted's connection to sshd/launcher are pipes, handled by --shell-job
#     during dump and --inherit-fd during restore.
#
# Previous approaches that failed:
#   - Parallel dumps: kernel race condition ("stopped by 5 unexpectedly")
#   - SIGSTOP elastic_nbody: orted detects stopped child and kills it
#   - --leave-running + --tcp-close: CRIU drops TCP, process crashes immediately
#   - Dump elastic_nbody only: PTY slave/master split causes restore failure

# Step 3a: Freeze orted on both workers to prevent MPI failure cascading
echo "Freezing orted on both workers..."
ORTED_PID_0="$(kexec_worker "$WORKER_0" pgrep -x orted 2>/dev/null || true)"
ORTED_PID_1="$(kexec_worker "$WORKER_1" pgrep -x orted 2>/dev/null || true)"
echo "  Worker 0 orted PID: ${ORTED_PID_0:-not found}"
echo "  Worker 1 orted PID: ${ORTED_PID_1:-not found}"

if [[ -n "$ORTED_PID_0" ]]; then
  kexec_worker "$WORKER_0" kill -STOP "$ORTED_PID_0" 2>/dev/null || true
fi
if [[ -n "$ORTED_PID_1" ]]; then
  kexec_worker "$WORKER_1" kill -STOP "$ORTED_PID_1" 2>/dev/null || true
fi
echo "orted frozen on both workers."

# Step 3b: Sequential dumps of orted tree (no --leave-running — CRIU kills the tree after dump)
DUMP_CMD_0="criu dump -t $ORTED_PID_0 -D $CHECKPOINT_DIR --shell-job $TCP_FLAG -o /tmp/dump.log -v4"
DUMP_CMD_1="criu dump -t $ORTED_PID_1 -D $CHECKPOINT_DIR --shell-job $TCP_FLAG -o /tmp/dump.log -v4"

echo "Dumping workers sequentially..."
echo "  Worker 0: $DUMP_CMD_0"
echo "  Worker 1: $DUMP_CMD_1"

set +e
echo "Dumping worker 0..."
kexec_worker "$WORKER_0" sh -c "$DUMP_CMD_0" >"${OUT_DIR}/dump_w0_stdout.log" 2>"${OUT_DIR}/dump_w0_stderr.log"
DUMP_RC_0=$?
echo "  Worker 0 dump: rc=$DUMP_RC_0"

# Brief pause: worker 1's elastic_nbody has a broken TCP socket now but
# OpenMPI ignores SIGPIPE so it stays alive.
sleep 1

echo "Dumping worker 1..."
kexec_worker "$WORKER_1" sh -c "$DUMP_CMD_1" >"${OUT_DIR}/dump_w1_stdout.log" 2>"${OUT_DIR}/dump_w1_stderr.log"
DUMP_RC_1=$?
echo "  Worker 1 dump: rc=$DUMP_RC_1"
set -e

# No explicit orted kill needed — CRIU dump without --leave-running kills the
# entire dumped process tree (orted + elastic_nbody).

echo ""
echo "Dump results:"
echo "  Worker 0: rc=$DUMP_RC_0"
echo "  Worker 1: rc=$DUMP_RC_1"

# Capture dump logs
kexec_worker "$WORKER_0" sh -c "cat /tmp/dump.log" > "${OUT_DIR}/dump_w0_criu.log" 2>/dev/null || true
kexec_worker "$WORKER_1" sh -c "cat /tmp/dump.log" > "${OUT_DIR}/dump_w1_criu.log" 2>/dev/null || true

if [[ $DUMP_RC_0 -ne 0 ]]; then
  echo ""
  echo "--- Worker 0 dump log (last 30 lines) ---"
  tail -30 "${OUT_DIR}/dump_w0_criu.log" 2>/dev/null || true
fi

if [[ $DUMP_RC_1 -ne 0 ]]; then
  echo ""
  echo "--- Worker 1 dump log (last 30 lines) ---"
  tail -30 "${OUT_DIR}/dump_w1_criu.log" 2>/dev/null || true
fi

if [[ $DUMP_RC_0 -ne 0 || $DUMP_RC_1 -ne 0 ]]; then
  echo ""
  echo "DUMP FAILED on one or both workers. See logs in $OUT_DIR"
  echo ""
  echo "Worker 0 stderr:"
  cat "${OUT_DIR}/dump_w0_stderr.log" 2>/dev/null || true
  echo "Worker 1 stderr:"
  cat "${OUT_DIR}/dump_w1_stderr.log" 2>/dev/null || true
  exit 1
fi

echo "BOTH DUMPS SUCCEEDED"
echo ""
echo "Checkpoint files (Worker 0):"
kexec_worker "$WORKER_0" ls -lh "$CHECKPOINT_DIR" 2>/dev/null | head -15 || true
echo ""
echo "Checkpoint files (Worker 1):"
kexec_worker "$WORKER_1" ls -lh "$CHECKPOINT_DIR" 2>/dev/null | head -15 || true

# Processes are already dead (no --leave-running). Wait for zombie reaping
# and verify the dumped PIDs are free before attempting restore.
echo ""
echo "--- Verifying process cleanup before restore ---"

# Wait for zombies to be reaped by tini (PID 1)
sleep 3

echo "Worker 0 processes after dump:"
kexec_worker "$WORKER_0" ps auxf 2>/dev/null || kexec_worker "$WORKER_0" ps aux || true
echo ""
echo "Worker 1 processes after dump:"
kexec_worker "$WORKER_1" ps auxf 2>/dev/null || kexec_worker "$WORKER_1" ps aux || true

# Verify the dumped PIDs (orted) are free
for w_info in "$WORKER_0:$ORTED_PID_0" "$WORKER_1:$ORTED_PID_1"; do
  w="${w_info%%:*}"
  pid="${w_info##*:}"
  if kexec_worker "$w" sh -c "test -d /proc/$pid" 2>/dev/null; then
    echo "WARNING: PID $pid still exists on $w (zombie?), force-killing..."
    kexec_worker "$w" sh -c "kill -9 $pid 2>/dev/null; sleep 2" || true
  fi
  echo "$w PID $pid: $(kexec_worker "$w" sh -c "test -d /proc/$pid && echo 'STILL EXISTS' || echo 'free'" 2>/dev/null)"
done

# Check both pods are still Running (tini/sshd should keep them alive)
for w in "$WORKER_0" "$WORKER_1"; do
  ph="$(k get pod "$w" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || true)"
  echo "Pod $w phase: $ph"
  if [[ "$ph" != "Running" ]]; then
    echo "ERROR: $w is no longer Running. Cannot restore." >&2
    exit 1
  fi
done

# ---------------------------------------------
# Step 4: CRIU restore on both workers
# ---------------------------------------------
echo ""
echo "--- Step 4: CRIU restore on both workers ---"

# Use --inherit-fd instead of --shell-job for restore to avoid TTY issues.
# During dump, --shell-job marked fds 0/1/2 as terminal-inherited.
# During restore, --inherit-fd overrides them so CRIU doesn't need a real PTY.
RESTORE_CMD_0="criu restore -D $CHECKPOINT_DIR --restore-detached $TCP_FLAG --inherit-fd fd[0]:/dev/null --inherit-fd fd[1]:/dev/null --inherit-fd fd[2]:/dev/null --pidfile /tmp/restored.pid -o /tmp/restore.log -v4"
RESTORE_CMD_1="criu restore -D $CHECKPOINT_DIR --restore-detached $TCP_FLAG --inherit-fd fd[0]:/dev/null --inherit-fd fd[1]:/dev/null --inherit-fd fd[2]:/dev/null --pidfile /tmp/restored.pid -o /tmp/restore.log -v4"

echo "Restoring BOTH workers simultaneously..."
echo "  Worker 0: $RESTORE_CMD_0"
echo "  Worker 1: $RESTORE_CMD_1"

# Launch restores in parallel
kexec_worker "$WORKER_0" sh -c "$RESTORE_CMD_0" >"${OUT_DIR}/restore_w0_stdout.log" 2>"${OUT_DIR}/restore_w0_stderr.log" &
RESTORE_PID_0=$!

kexec_worker "$WORKER_1" sh -c "$RESTORE_CMD_1" >"${OUT_DIR}/restore_w1_stdout.log" 2>"${OUT_DIR}/restore_w1_stderr.log" &
RESTORE_PID_1=$!

set +e
wait $RESTORE_PID_0
RESTORE_RC_0=$?
wait $RESTORE_PID_1
RESTORE_RC_1=$?
set -e

echo ""
echo "Restore results:"
echo "  Worker 0: rc=$RESTORE_RC_0"
echo "  Worker 1: rc=$RESTORE_RC_1"

# Capture restore logs
kexec_worker "$WORKER_0" sh -c "cat /tmp/restore.log" > "${OUT_DIR}/restore_w0_criu.log" 2>/dev/null || true
kexec_worker "$WORKER_1" sh -c "cat /tmp/restore.log" > "${OUT_DIR}/restore_w1_criu.log" 2>/dev/null || true

if [[ $RESTORE_RC_0 -ne 0 ]]; then
  echo ""
  echo "--- Worker 0 restore log (last 30 lines) ---"
  tail -30 "${OUT_DIR}/restore_w0_criu.log" 2>/dev/null || true
fi

if [[ $RESTORE_RC_1 -ne 0 ]]; then
  echo ""
  echo "--- Worker 1 restore log (last 30 lines) ---"
  tail -30 "${OUT_DIR}/restore_w1_criu.log" 2>/dev/null || true
fi

if [[ $RESTORE_RC_0 -ne 0 || $RESTORE_RC_1 -ne 0 ]]; then
  echo ""
  echo "RESTORE FAILED on one or both workers. See logs in $OUT_DIR"
  exit 1
fi

echo "BOTH RESTORES SUCCEEDED"

# ---------------------------------------------
# Step 5: Monitor restored processes
# ---------------------------------------------
echo ""
echo "--- Step 5: Monitor restored processes ---"

# The restored PID file contains orted's PID. Also check for elastic_nbody
# (child of orted) which is the actual simulation process.
RESTORED_ORTED_0="$(kexec_worker "$WORKER_0" cat /tmp/restored.pid 2>/dev/null || echo '')"
RESTORED_ORTED_1="$(kexec_worker "$WORKER_1" cat /tmp/restored.pid 2>/dev/null || echo '')"
echo "Restored orted PID (Worker 0): ${RESTORED_ORTED_0:-unknown}"
echo "Restored orted PID (Worker 1): ${RESTORED_ORTED_1:-unknown}"

RESTORED_NBODY_0="$(kexec_worker "$WORKER_0" pgrep -x elastic_nbody 2>/dev/null || echo '')"
RESTORED_NBODY_1="$(kexec_worker "$WORKER_1" pgrep -x elastic_nbody 2>/dev/null || echo '')"
echo "Restored elastic_nbody PID (Worker 0): ${RESTORED_NBODY_0:-not found}"
echo "Restored elastic_nbody PID (Worker 1): ${RESTORED_NBODY_1:-not found}"

echo ""
echo "Worker 0 process tree after restore:"
kexec_worker "$WORKER_0" ps auxf 2>/dev/null || kexec_worker "$WORKER_0" ps aux || true

echo ""
echo "Worker 1 process tree after restore:"
kexec_worker "$WORKER_1" ps auxf 2>/dev/null || kexec_worker "$WORKER_1" ps aux || true

# Wait a bit and check if processes are still alive
echo ""
echo "Waiting 30s to see if restored processes survive..."
sleep 30

W0_ALIVE="false"
W1_ALIVE="false"
# Check for elastic_nbody (the simulation) — more meaningful than orted
if kexec_worker "$WORKER_0" pgrep -x elastic_nbody >/dev/null 2>&1; then
  W0_ALIVE="true"
fi
if kexec_worker "$WORKER_1" pgrep -x elastic_nbody >/dev/null 2>&1; then
  W1_ALIVE="true"
fi

echo "After 30s:"
echo "  Worker 0 elastic_nbody alive: $W0_ALIVE"
echo "  Worker 1 elastic_nbody alive: $W1_ALIVE"

echo ""
echo "Worker 0 processes:"
kexec_worker "$WORKER_0" ps auxf 2>/dev/null || kexec_worker "$WORKER_0" ps aux || true
echo ""
echo "Worker 1 processes:"
kexec_worker "$WORKER_1" ps auxf 2>/dev/null || kexec_worker "$WORKER_1" ps aux || true

# ---------------------------------------------
# Summary
# ---------------------------------------------
echo ""
echo "=== Summary ==="
echo "Dump:    Worker 0 rc=$DUMP_RC_0, Worker 1 rc=$DUMP_RC_1"
echo "Restore: Worker 0 rc=$RESTORE_RC_0, Worker 1 rc=$RESTORE_RC_1"
echo "Alive:   Worker 0=$W0_ALIVE, Worker 1=$W1_ALIVE"
echo "Logs:    $OUT_DIR"
echo "DONE."
