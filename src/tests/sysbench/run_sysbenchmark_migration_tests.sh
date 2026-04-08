#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# Sysbench CRIU migration benchmark harness
#
# Phases per (test_type, threads):
#   1) Baseline: run tests.sh with --iters=N (default 10), collect avg/min/max
#   2) Migration: run tests.sh with --iters=1, trigger migration at +13s, collect duration
#   3) Compare: record migration duration, delta vs baseline avg, and total time
#
# Requirements:
#  - tests.sh prints a line containing: "SUMMARY ... avg_ms=... min_ms=... max_ms=..."
#  - tests.sh supports: --test-type, --threads, --timeout, --verbosity, --debug, --iters, --events
#  - Your migrator: ./test.sh --migration --pod <pod-name> (assumes test-namespace, kind-worker -> kind-worker2)
#  - YAML template contains placeholders: __TEST_TYPE__ __THREADS__ __ITERS__ __EVENTS__
#  - YAML template has spec.restartPolicy: Never
# ---------------------------------------------

NAMESPACE="test-namespace"
YAML_TEMPLATE="${YAML_TEMPLATE:-./tests/sysbench/sysbench.yml}"   # template with placeholders
MIGRATOR_CMD="${MIGRATOR_CMD:-./test.sh}"              # migration script
OUT_DIR="${OUT_DIR:-../data/artifacts}"
POD_BASENAME="${POD_BASENAME:-sysbench}"

# Baseline iterations
BASELINE_ITERS="${BASELINE_ITERS:-10}"

# Sysbench/test args
TIMEOUT="${TIMEOUT:-30}"
VERBOSITY="${VERBOSITY:-5}"
DEBUG_FLAG="${DEBUG_FLAG:---debug}"      # set to "" to disable
SLEEP_BEFORE_MIGRATE="${SLEEP_BEFORE_MIGRATE:-2}"

# Test matrix
TEST_TYPES=(cpu memory threads mutex fileio)
THREADS_LIST=(1 2 4 8)

# If your tests.sh uses --events, set this (or pass via env). Example: EVENTS=10000
EVENTS="${EVENTS:-200000}"

# ---------------------------------------------
# Helpers
# ---------------------------------------------
k() {
  kubectl "$@" 2> >(grep -v "memcache.go" | grep -v "metrics.k8s.io/v1beta1" >&2)
}

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing command: $1" >&2; exit 1; }; }
ts() { date +"%Y%m%d_%H%M%S"; }

pod_exists() { k get pod "$1" -n "$NAMESPACE" >/dev/null 2>&1; }
pod_phase() { k get pod "$1" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || true; }
pod_node() { k get pod "$1" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}' 2>/dev/null || true; }

wait_for_pod_ready() {
  k wait --for=condition=Ready "pod/$1" -n "$NAMESPACE" --timeout=90s >/dev/null
}

wait_for_phase() {
  local pod="$1" want1="$2" want2="${3:-}" timeout="${4:-600}"
  local start now
  start="$(date +%s)"
  while true; do
    local ph
    ph="$(pod_phase "$pod")"
    if [[ "$ph" == "$want1" ]] || ([[ -n "$want2" ]] && [[ "$ph" == "$want2" ]]); then
      return 0
    fi
    now="$(date +%s)"
    if (( now - start > timeout )); then
      echo "Timed out waiting for $pod to reach $want1${want2:+ or $want2}. Current=$ph" >&2
      return 1
    fi
    sleep 1
  done
}

render_yaml() {
  local test_type="$1" threads="$2" iters="$3" events="$4" pod="$5" out="$6"

  # Replace placeholders; also overwrite metadata.name if present.
  # If your template doesn't have __ITERS__/__EVENTS__ placeholders, add them.
  local events_val="$events"
  [[ -z "$events_val" ]] && events_val="__NO_EVENTS__"

  sed \
    -e "s/__TEST_TYPE__/${test_type}/g" \
    -e "s/__THREADS__/${threads}/g" \
    -e "s/__ITERS__/${iters}/g" \
    -e "s/__EVENTS__/${events_val}/g" \
    -e "s/^  name: .*/  name: ${pod}/" \
    "$YAML_TEMPLATE" > "$out"
}

# Extract avg/min/max from the SUMMARY line.
# Tries kubectl logs first (works pre-migration), then falls back to reading
# the log file inside the container (works post-CRIU-restore where stdout is
# a broken pipe but file writes still succeed).
extract_summary() {
  local pod="$1" out_file="$2"
  local summary

  # Try kubectl logs first (captures stdout)
  summary="$(k logs -n "$NAMESPACE" "$pod" 2>/dev/null | grep -E 'SUMMARY ' | tail -n 1 || true)"

  # Fallbacks: try reading from log files inside the container (only works while pod is Running)
  for logpath in /tmp/container.log /tmp/checkpoints/summary.txt /script-data/container.log; do
    if [[ -z "$summary" ]]; then
      summary="$(k exec -n "$NAMESPACE" "$pod" -- cat "$logpath" 2>/dev/null | grep -E 'SUMMARY ' | tail -n 1 || true)"
    fi
  done

  echo "$summary" > "$out_file"

  local avg min max
  avg="$(echo "$summary" | sed -nE 's/.*avg_ms=([0-9]+).*/\1/p')"
  min="$(echo "$summary" | sed -nE 's/.*min_ms=([0-9]+).*/\1/p')"
  max="$(echo "$summary" | sed -nE 's/.*max_ms=([0-9]+).*/\1/p')"

  if [[ -z "$avg" || -z "$min" || -z "$max" ]]; then
    return 1
  fi

  echo "$avg,$min,$max"
}

# Millisecond wall time for a whole phase from the harness perspective
now_ms() { echo $(( $(date +%s) * 1000 )); }

# ---------------------------------------------
# Preconditions
# ---------------------------------------------
need_cmd kubectl
need_cmd sed
need_cmd awk

[[ -f "$YAML_TEMPLATE" ]] || { echo "YAML template not found: $YAML_TEMPLATE" >&2; exit 1; }
OUT_DIR="${OUT_DIR}/$(ts)"
mkdir -p "$OUT_DIR"

if [[ "$MIGRATOR_CMD" == ./* ]] || [[ "$MIGRATOR_CMD" == /* ]]; then
  [[ -x "$MIGRATOR_CMD" ]] || { echo "Migrator not executable: $MIGRATOR_CMD" >&2; exit 1; }
fi

results_csv="${OUT_DIR}/results_$(ts).csv"
echo "timestamp,test_type,threads,events,baseline_iters,baseline_avg_ms,baseline_min_ms,baseline_max_ms,migration_runtime_ms,migration_time_ms,total_time_with_migration_ms,delta_vs_baseline_avg_ms,source_node,target_node,migration_rc" \
  > "$results_csv"

# ---------------------------------------------
# Main loop
# ---------------------------------------------
k delete pods --all -n "$NAMESPACE"
for test_type in "${TEST_TYPES[@]}"; do
  for threads in "${THREADS_LIST[@]}"; do
    run_id="$(ts)"
    case_dir="${OUT_DIR}/${POD_BASENAME}_${test_type}_t${threads}"
    mkdir -p "$case_dir"

    echo "=== Case: test_type=$test_type threads=$threads events=${EVENTS:-none} ==="

    # -------------------------
    # Phase 1: Baseline (N iters, no migration)
    # -------------------------
    baseline_pod="${POD_BASENAME}-${test_type}-t${threads}-base"
    baseline_yaml="${case_dir}/${baseline_pod}.yaml"

    # cleanup
    pod_exists "$baseline_pod" && k delete pod "$baseline_pod" -n "$NAMESPACE" --wait=true >/dev/null || true

    render_yaml "$test_type" "$threads" "$BASELINE_ITERS" "${EVENTS:-}" "$baseline_pod" "$baseline_yaml"
    k apply -f "$baseline_yaml" -n "$NAMESPACE" >/dev/null

    wait_for_pod_ready "$baseline_pod" || true
    src_node="$(pod_node "$baseline_pod")"

    wait_for_phase "$baseline_pod" "Succeeded" "Failed" 1200 || true
    k logs -n "$NAMESPACE" "$baseline_pod" > "${case_dir}/baseline_kubectl_logs.log" 2>&1 || true

    baseline_vals="$(extract_summary "$baseline_pod" "${case_dir}/baseline_summary_line.txt" || true)"
    if [[ -z "${baseline_vals:-}" ]]; then
      echo "Baseline SUMMARY not found/parsable; see ${case_dir}/baseline_kubectl_logs.log" >&2
      # Still proceed so you get artifacts
      baseline_avg="" baseline_min="" baseline_max=""
    else
      echo "Baseline SUMMARY found!"
      IFS=',' read -r baseline_avg baseline_min baseline_max <<< "$baseline_vals"
      echo "baseline_avg: $baseline_avg"
      echo "baseline_min: $baseline_min"
      echo "baseline_max: $baseline_max"
    fi

    # cleanup baseline pod to reduce clutter
    k delete pod "$baseline_pod" -n "$NAMESPACE" --wait=true >/dev/null || true

    # -------------------------
    # Phase 2: Migration run (1 iter, migrate at +13s)
    # -------------------------
    mig_pod="${POD_BASENAME}-${test_type}-t${threads}-mig"
    restored_pod="${mig_pod}-1"
    mig_yaml="${case_dir}/${mig_pod}.yaml"

    pod_exists "$mig_pod" && k delete pod "$mig_pod" -n "$NAMESPACE" --wait=true >/dev/null || true
    pod_exists "$restored_pod" && k delete pod "$restored_pod" -n "$NAMESPACE" --wait=true >/dev/null || true

    render_yaml "$test_type" "$threads" "1" "${EVENTS:-}" "$mig_pod" "$mig_yaml"
    k apply -f "$mig_yaml" -n "$NAMESPACE" >/dev/null

    wait_for_pod_ready "$mig_pod" || true
    wait_for_phase "$mig_pod" "Running" "Failed" 600 || true
    mig_src_node="$(pod_node "$mig_pod")"

    total_start_ms="$(now_ms)"

    sleep "$SLEEP_BEFORE_MIGRATE"

    # Measure migration command duration
    mig_start_ms="$(now_ms)"
    set +e
    "$MIGRATOR_CMD" --migration --pod "$mig_pod" >"${case_dir}/migrator_stdout.log" 2>"${case_dir}/migrator_stderr.log"
    mig_rc=$?
    set -e
    mig_end_ms="$(now_ms)"
    migration_time_ms=$((mig_end_ms - mig_start_ms))

    # Wait for ORIGINAL pod to finish (it should complete its run)
    wait_for_phase "$mig_pod" "Succeeded" "Failed" 1200 || true
    k logs -n "$NAMESPACE" "$mig_pod" > "${case_dir}/original_kubectl_logs.log" 2>&1 || true

    # Wait for RESTORED pod to be created, then finish
    # (poll for up to 2 minutes for creation)
    created=0
    for _ in $(seq 1 120); do
    if pod_exists "$restored_pod"; then
        created=1
        break
    fi
    sleep 1
    done
    if [[ $created -ne 1 ]]; then
    echo "Restored pod ${restored_pod} never appeared. See migrator logs." >&2
    fi

    if pod_exists "$restored_pod"; then
    # it may or may not become Ready depending on how restore works, but it should reach a terminal phase
    wait_for_phase "$restored_pod" "Succeeded" "Failed" 1200 || true
    mig_dst_node="$(pod_node "$restored_pod")"
    k logs -n "$NAMESPACE" "$restored_pod" > "${case_dir}/restored_kubectl_logs.log" 2>&1 || true
    else
    mig_dst_node=""
    : > "${case_dir}/restored_kubectl_logs.log"
    fi

    total_end_ms="$(now_ms)"
    total_time_ms=$((total_end_ms - total_start_ms))

    # Parse SUMMARY from restored pod (this is the migrated runtime)
    mig_vals=""
    if pod_exists "$restored_pod"; then
    mig_vals="$(extract_summary "$restored_pod" "${case_dir}/migration_summary_line.txt" || true)"
    fi

    if [[ -z "${mig_vals:-}" ]]; then
    echo "Restored pod SUMMARY not found/parsable; see ${case_dir}/restored_kubectl_logs.log" >&2
    mig_runtime=""
    else
    IFS=',' read -r mig_runtime _ _ <<< "$mig_vals"
    fi

    # Cleanup both pods
    pod_exists "$mig_pod" && k delete pod "$mig_pod" -n "$NAMESPACE" --wait=true >/dev/null || true
    pod_exists "$restored_pod" && k delete pod "$restored_pod" -n "$NAMESPACE" --wait=true >/dev/null || true

    # -------------------------
    # Phase 3: Compare + record
    # -------------------------
    # delta = migration_runtime - baseline_avg (if both exist)
    if [[ -n "${baseline_avg:-}" && -n "${mig_runtime:-}" ]]; then
      delta_vs_avg=$((mig_runtime - baseline_avg))
    else
      delta_vs_avg=""
    fi

    # Write row
    echo "$(ts),$test_type,$threads,${EVENTS:-},$BASELINE_ITERS,${baseline_avg:-},${baseline_min:-},${baseline_max:-},${mig_runtime:-},$migration_time_ms,$total_time_ms,${delta_vs_avg:-},$mig_src_node,$mig_dst_node,$mig_rc" \
      >> "$results_csv"

    echo "Saved case artifacts: $case_dir"
    echo
  done
done

echo "DONE. Results CSV: $results_csv"