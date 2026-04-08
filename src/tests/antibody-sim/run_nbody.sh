#!/bin/bash
# NOTE: Do NOT use "set -e" here. After CRIU restore, the script's stdout/stderr
# FDs become broken pipes (they were connected to the source container's log
# pipeline via --shell-job, and that PTY is torn down when kubectl exec exits).
# With set -e, the very first echo/log call after restore hits a broken pipe
# and silently kills the script.
#
# SIGPIPE must also be ignored. Writing to the broken stdout pipe delivers
# SIGPIPE which kills the process *before* bash can evaluate "|| true".
# With the signal ignored, the write returns EPIPE and || true handles it.
trap '' SIGPIPE

# Default values
BODIES=1000
ITERS=100
CHECKPOINT_INTERVAL=10
RESULTS_FOLDER="/results/"
LOG_FILE="/script-data/container.log"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --bodies=*)              BODIES="${1#*=}"; shift ;;
    --bodies)                BODIES="$2"; shift 2 ;;
    --iters=*)               ITERS="${1#*=}"; shift ;;
    --iters)                 ITERS="$2"; shift 2 ;;
    --checkpoint-interval=*) CHECKPOINT_INTERVAL="${1#*=}"; shift ;;
    --checkpoint-interval)   CHECKPOINT_INTERVAL="$2"; shift 2 ;;
    --results-folder=*)      RESULTS_FOLDER="${1#*=}"; shift ;;
    --results-folder)        RESULTS_FOLDER="$2"; shift 2 ;;
    --log-file=*)            LOG_FILE="${1#*=}"; shift ;;
    --log-file)              LOG_FILE="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Cache hostname once at startup — avoids spawning cat/subshell on every log
# call (fewer child processes = cleaner CRIU process tree, and /etc/hostname
# might not be accessible after restore on a different node).
HOST="$(cat /etc/hostname 2>/dev/null || hostname 2>/dev/null || echo 'unknown')"

mkdir -p "$(dirname "$LOG_FILE")"
: > "$LOG_FILE"
mkdir -p "$RESULTS_FOLDER"

log() {
  local msg="[INFO][$HOST] $*"
  # Write to both stdout (for kubectl logs) and log file.
  # After CRIU restore stdout is a broken pipe — suppress errors with || true
  # but do NOT use 2>/dev/null (redirecting FDs to /dev/null changes the FD
  # state that CRIU captures during dump, and /dev/null may not be restorable
  # in the target's mount namespace, causing "Task exited, status=1").
  echo "$msg" || true
  echo "$msg" >> "$LOG_FILE" || true
}

# Timing helpers (ms)
now_ms() {
  echo $(( $(date +%s) * 1000 ))
}

log "N-Body CRIU Migration Test"
log "Beginning at $(date)"
log "Running with parameters: BODIES=$BODIES ITERS=$ITERS CHECKPOINT_INTERVAL=$CHECKPOINT_INTERVAL RESULTS_FOLDER=$RESULTS_FOLDER"

start_ms=$(now_ms)

# Run the no-MPI binary. The MPI version spawns orted (singleton daemon)
# which uses PTYs, shared memory in /dev/shm, and sockets that CRIU cannot
# restore across nodes. The no-MPI binary is identical computation but
# without any MPI runtime — clean process tree for CRIU.
log "[TestLogger] Starting N-Body simulation at $(date)"
/app/nbody/elastic_nbody_nompi \
  -b "$BODIES" \
  -i "$ITERS" \
  -c "$CHECKPOINT_INTERVAL" \
  -f "$RESULTS_FOLDER" \
  >> "$LOG_FILE" 2>&1
sim_rc=$?

end_ms=$(now_ms)
dur_ms=$((end_ms - start_ms))

log "[TestLogger] Simulation exited with rc=$sim_rc duration_ms=$dur_ms"

summary="SUMMARY bodies=$BODIES iters=$ITERS checkpoint_interval=$CHECKPOINT_INTERVAL avg_ms=$dur_ms min_ms=$dur_ms max_ms=$dur_ms"
log "$summary"

# Also write to the checkpoint volume (hostPath shared between pods).
# After CRIU restore the script's /script-data mount is in the restored
# mount namespace and invisible to the container's PID 1 / holder script.
# /tmp/checkpoints is a hostPath volume that both namespaces can reach.
echo "[INFO][$HOST] $summary" > /tmp/checkpoints/summary.txt 2>/dev/null || true

log "Finish time: $(date)"
