#!/bin/bash
# Wrapper script to run the N-body MPI simulation under MANA (DMTCP)
# transparent checkpointing. Unlike the CRIU approach, MANA intercepts
# MPI calls at the application level — no kernel support or privileged
# containers needed for checkpointing.
#
# MANA checkpoint flow:
#   1. mana_launch starts a DMTCP coordinator + wraps mpirun
#   2. dmtcp_command -c triggers a coordinated checkpoint across all ranks
#   3. mana_restart resumes all ranks from checkpoint images

trap '' SIGPIPE

# Default values
BODIES=1000
ITERS=100
CHECKPOINT_INTERVAL=10
NP=2
RESULTS_FOLDER="/results/"
LOG_FILE="/script-data/container.log"
CKPT_DIR="/tmp/mana-ckpt"
MODE="run"  # "run" or "restart"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --bodies=*)              BODIES="${1#*=}"; shift ;;
    --bodies)                BODIES="$2"; shift 2 ;;
    --iters=*)               ITERS="${1#*=}"; shift ;;
    --iters)                 ITERS="$2"; shift 2 ;;
    --checkpoint-interval=*) CHECKPOINT_INTERVAL="${1#*=}"; shift ;;
    --checkpoint-interval)   CHECKPOINT_INTERVAL="$2"; shift 2 ;;
    --np=*)                  NP="${1#*=}"; shift ;;
    --np)                    NP="$2"; shift 2 ;;
    --results-folder=*)      RESULTS_FOLDER="${1#*=}"; shift ;;
    --results-folder)        RESULTS_FOLDER="$2"; shift 2 ;;
    --log-file=*)            LOG_FILE="${1#*=}"; shift ;;
    --log-file)              LOG_FILE="$2"; shift 2 ;;
    --ckpt-dir=*)            CKPT_DIR="${1#*=}"; shift ;;
    --ckpt-dir)              CKPT_DIR="$2"; shift 2 ;;
    --restart)               MODE="restart"; shift ;;
    *) shift ;;
  esac
done

HOST="$(cat /etc/hostname 2>/dev/null || hostname 2>/dev/null || echo 'unknown')"

mkdir -p "$(dirname "$LOG_FILE")"
: > "$LOG_FILE"
mkdir -p "$RESULTS_FOLDER"
mkdir -p "$CKPT_DIR"

log() {
  local msg="[INFO][$HOST] $*"
  echo "$msg" || true
  echo "$msg" >> "$LOG_FILE" || true
}

now_ms() {
  echo $(( $(date +%s) * 1000 ))
}

log "N-Body MANA Migration Test"
log "Beginning at $(date)"
log "Mode: $MODE"
log "Parameters: BODIES=$BODIES ITERS=$ITERS NP=$NP CHECKPOINT_INTERVAL=$CHECKPOINT_INTERVAL"
log "Checkpoint dir: $CKPT_DIR"

start_ms=$(now_ms)

if [[ "$MODE" == "restart" ]]; then
  # Restart from MANA checkpoint images
  log "[TestLogger] Restarting N-Body simulation from MANA checkpoint at $(date)"

  # mana_restart reads checkpoint images from CKPT_DIR and resumes all ranks
  mana_restart \
    --ckptdir "$CKPT_DIR" \
    --restartdir "$CKPT_DIR" \
    >> "$LOG_FILE" 2>&1
  sim_rc=$?

else
  # Fresh run under MANA coordination
  log "[TestLogger] Starting N-Body simulation under MANA at $(date)"

  # Start sshd for MPI communication (needed for multi-pod runs)
  /usr/sbin/sshd 2>/dev/null || true

  # mana_launch wraps mpirun with DMTCP coordination for transparent
  # checkpointing. The coordinator listens on a port and all ranks
  # register with it.
  mana_launch \
    --ckptdir "$CKPT_DIR" \
    mpirun --allow-run-as-root -np "$NP" \
    /app/nbody/elastic_nbody \
      -b "$BODIES" \
      -i "$ITERS" \
      -c "$CHECKPOINT_INTERVAL" \
      -f "$RESULTS_FOLDER" \
    >> "$LOG_FILE" 2>&1
  sim_rc=$?
fi

end_ms=$(now_ms)
dur_ms=$((end_ms - start_ms))

log "[TestLogger] Simulation exited with rc=$sim_rc duration_ms=$dur_ms"

summary="SUMMARY bodies=$BODIES iters=$ITERS np=$NP checkpoint_interval=$CHECKPOINT_INTERVAL mode=$MODE avg_ms=$dur_ms min_ms=$dur_ms max_ms=$dur_ms"
log "$summary"

echo "[INFO][$HOST] $summary" > /tmp/checkpoints/summary.txt 2>/dev/null || true

log "Finish time: $(date)"
