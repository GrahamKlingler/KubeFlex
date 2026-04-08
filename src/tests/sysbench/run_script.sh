#!/bin/bash
# NOTE: Do NOT use "set -e" here. After CRIU restore, the script's stdout/stderr
# FDs become broken pipes (they were connected to the source container's log
# pipeline via --shell-job, and that PTY is torn down when kubectl exec exits).
# With set -e, the very first echo/log call after restore hits a broken pipe
# and silently kills the script. The pod stays up (sleep infinity is PID 1)
# but the benchmark never produces results.
#
# SIGPIPE must also be ignored. Writing to the broken stdout pipe delivers
# SIGPIPE which kills the process *before* bash can evaluate "|| true".
# With the signal ignored, the write returns EPIPE and || true handles it.
trap '' SIGPIPE

# Default values
NUM_THREADS=1
VERBOSITY=1
DEBUG=""
TEST_TYPE="all"
SLEEP_TIME=1
TIMEOUT=10
ITERS=1
LOG_FILE="/script-data/container.log"
EVENTS=200000

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --threads=*)    NUM_THREADS="${1#*=}"; shift ;;
    --threads)      NUM_THREADS="$2"; shift 2 ;;
    --verbosity=*)  VERBOSITY="${1#*=}"; shift ;;
    --verbosity)    VERBOSITY="$2"; shift 2 ;;
    --debug)        DEBUG="--debug"; shift ;;
    --test-type=*)  TEST_TYPE="${1#*=}"; shift ;;
    --test-type)    TEST_TYPE="$2"; shift 2 ;;
    --sleep-time=*) SLEEP_TIME="${1#*=}"; shift ;;
    --sleep-time)   SLEEP_TIME="$2"; shift 2 ;;
    --timeout=*)    TIMEOUT="${1#*=}"; shift ;;
    --timeout)      TIMEOUT="$2"; shift 2 ;;
    --iters=*)      ITERS="${1#*=}"; shift ;;
    --iters)        ITERS="$2"; shift 2 ;;
    --log-file=*)   LOG_FILE="${1#*=}"; shift ;;
    --log-file)     LOG_FILE="$2"; shift 2 ;;
    --events=*)     EVENTS="${1#*=}"; shift ;;
    --events)       EVENTS="$2"; shift 2 ;;
    *) shift ;;
  esac
done

SYSBENCH_ARGS="--time=$TIMEOUT --events=$EVENTS --threads=$NUM_THREADS $DEBUG --verbosity=$VERBOSITY"
# Cache hostname once at startup — avoids spawning cat/subshell on every log
# call (fewer child processes = cleaner CRIU process tree, and /etc/hostname
# might not be accessible after restore on a different node).
HOST="$(cat /etc/hostname 2>/dev/null || hostname 2>/dev/null || echo 'unknown')"

mkdir -p "$(dirname "$LOG_FILE")"
: > "$LOG_FILE"

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

run_and_time_cmd() {
  local label="$1"
  shift
  local start end dur

  start=$(now_ms)
  "$@" >> "$LOG_FILE"
  end=$(now_ms)

  dur=$((end - start))
  echo "$dur"
}

print_header() {
  log "Sysbench Testing!"
  log "Beginning at $(date)"
  log "Running with parameters: NUM_THREADS=$NUM_THREADS VERBOSITY=$VERBOSITY DEBUG='$DEBUG' SLEEP_TIME=$SLEEP_TIME TIMEOUT=$TIMEOUT ITERS=$ITERS"
}

summary_init() {
  SUM_MS=0
  MIN_MS=2147483647
  MAX_MS=0
  COUNT=0
}

summary_add() {
  local dur="$1"
  SUM_MS=$((SUM_MS + dur))
  (( dur < MIN_MS )) && MIN_MS=$dur
  (( dur > MAX_MS )) && MAX_MS=$dur
  COUNT=$((COUNT + 1))
}

summary_print() {
  local avg_ms=$((SUM_MS / COUNT))
  local summary="SUMMARY test_type=$TEST_TYPE events=$EVENTS threads=$NUM_THREADS timeout=$TIMEOUT iters=$COUNT avg_ms=$avg_ms min_ms=$MIN_MS max_ms=$MAX_MS"
  log "$summary"
  # Also write to the checkpoint volume (hostPath shared between pods).
  # After CRIU restore the script's /script-data mount is in the restored
  # mount namespace and invisible to the container's PID 1 / holder script.
  # /tmp/checkpoints is a hostPath volume that both namespaces can reach.
  echo "[INFO][$HOST] $summary" > /tmp/checkpoints/summary.txt 2>/dev/null || true
}

run_cpu() {
  summary_init
  for i in $(seq 1 "$ITERS"); do
    log "[TestLogger] Starting CPU Test #$i at $(date)"
    dur=$(run_and_time_cmd "cpu" sysbench cpu $SYSBENCH_ARGS run)
    log "[TestLogger] ITER $i duration_ms=$dur"
    summary_add "$dur"
    (( i < ITERS )) && sleep "$SLEEP_TIME"
  done
  summary_print
}

run_memory() {
  summary_init
  for i in $(seq 1 "$ITERS"); do
    log "[TestLogger] Starting Memory Test #$i at $(date)"
    dur=$(run_and_time_cmd "memory" sysbench memory $SYSBENCH_ARGS run)
    log "[TestLogger] ITER $i duration_ms=$dur"
    summary_add "$dur"
    (( i < ITERS )) && sleep "$SLEEP_TIME"
  done
  summary_print
}

run_threads() {
  summary_init
  for i in $(seq 1 "$ITERS"); do
    log "[TestLogger] Starting Threads Test #$i at $(date)"
    dur=$(run_and_time_cmd "threads" sysbench threads $SYSBENCH_ARGS run)
    log "[TestLogger] ITER $i duration_ms=$dur"
    summary_add "$dur"
    (( i < ITERS )) && sleep "$SLEEP_TIME"
  done
  summary_print
}

run_mutex() {
  summary_init
  for i in $(seq 1 "$ITERS"); do
    log "[TestLogger] Starting Mutex Test #$i at $(date)"
    dur=$(run_and_time_cmd "mutex" sysbench mutex $SYSBENCH_ARGS run)
    log "[TestLogger] ITER $i duration_ms=$dur"
    summary_add "$dur"
    (( i < ITERS )) && sleep "$SLEEP_TIME"
  done
  summary_print
}

run_fileio() {
  # FileIO is heavier; you may want ITERS=1 by default for it.
  summary_init

  log "[TestLogger] Preparing fileio test files at $(date)"
  sysbench fileio --file-total-size=1G --verbosity="$VERBOSITY" prepare >> "$LOG_FILE" 2>&1

  for i in $(seq 1 "$ITERS"); do
    for mode in seqrd seqwr seqrewr rndrd rndwr rndrw; do
      log "[TestLogger] Starting FileIO Test #$i mode=$mode at $(date)"
      dur=$(run_and_time_cmd "fileio-$mode" sysbench fileio $SYSBENCH_ARGS --file-total-size=1G --file-test-mode="$mode" run)
      log "[TestLogger] ITER $i mode=$mode duration_ms=$dur"
      summary_add "$dur"
    done
    (( i < ITERS )) && sleep "$SLEEP_TIME"
  done

  log "[TestLogger] Cleaning up fileio test files at $(date)"
  sysbench fileio cleanup >> "$LOG_FILE" 2>&1

  summary_print
}

print_header

case "$TEST_TYPE" in
  cpu)     run_cpu ;;
  memory)  run_memory ;;
  threads) run_threads ;;
  mutex)   run_mutex ;;
  fileio)  run_fileio ;;
  all)
    # pick what you want for "all"
    run_cpu
    ;;
  *)
    log "Unknown test type: $TEST_TYPE"
    exit 1
    ;;
esac

log "Finish time: $(date)"
