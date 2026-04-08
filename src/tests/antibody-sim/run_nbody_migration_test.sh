#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# N-Body CRIU migration benchmark harness
#
# Two modes:
#   --mode same-node   : checkpoint + restore on the SAME worker node (CRIU sanity check)
#   --mode cross-node  : checkpoint on one node, restore on a DIFFERENT node (real migration)
#
# Phases per run:
#   1) Optional baseline: run nbody without migration, collect timing
#   2) Migration: run nbody, trigger migration mid-run, collect timing from restored pod
#   3) Compare: record delta vs baseline
#
# Requirements:
#   - nbody-mpi:local image loaded into Kind (with run_nbody.sh baked in)
#   - test.sh migration trigger script
#   - Migration service deployed and reachable via port-forward
#   - YAML template with placeholders: __BODIES__, __ITERS__, __CHECKPOINT__
# ---------------------------------------------

NAMESPACE="test-namespace"
YAML_TEMPLATE="${YAML_TEMPLATE:-./tests/antibody-sim/nbody-testpod.yml}"
MIGRATOR_CMD="${MIGRATOR_CMD:-./test.sh}"
OUT_DIR="${OUT_DIR:-../data/nbody-artifacts}"
POD_BASENAME="${POD_BASENAME:-nbody}"

# Simulation defaults — must be large enough that the pod stays Running
# long enough for migration to trigger. 5000 bodies / 500 iters should
# run for ~20-60s depending on CPU.
BODIES="${BODIES:-5000}"
ITERS="${ITERS:-500}"
CHECKPOINT="${CHECKPOINT:-50}"

# Baseline
SKIP_BASELINE="${SKIP_BASELINE:-false}"

# Migration timing
SLEEP_BEFORE_MIGRATE="${SLEEP_BEFORE_MIGRATE:-5}"

# Mode: same-node or cross-node
MODE="same-node"

# Node names (Kind defaults)
SOURCE_NODE="${SOURCE_NODE:-kind-worker}"
CROSS_NODE_TARGET="${CROSS_NODE_TARGET:-kind-worker2}"

# Parse CLI arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --mode=*)               MODE="${1#*=}"; shift ;;
    --mode)                 MODE="$2"; shift 2 ;;
    --bodies=*)             BODIES="${1#*=}"; shift ;;
    --bodies)               BODIES="$2"; shift 2 ;;
    --iters=*)              ITERS="${1#*=}"; shift ;;
    --iters)                ITERS="$2"; shift 2 ;;
    --checkpoint=*)         CHECKPOINT="${1#*=}"; shift ;;
    --checkpoint)           CHECKPOINT="$2"; shift 2 ;;
    --sleep=*)              SLEEP_BEFORE_MIGRATE="${1#*=}"; shift ;;
    --sleep)                SLEEP_BEFORE_MIGRATE="$2"; shift 2 ;;
    --source-node=*)        SOURCE_NODE="${1#*=}"; shift ;;
    --source-node)          SOURCE_NODE="$2"; shift 2 ;;
    --target-node=*)        CROSS_NODE_TARGET="${1#*=}"; shift ;;
    --target-node)          CROSS_NODE_TARGET="$2"; shift 2 ;;
    --skip-baseline)        SKIP_BASELINE=true; shift ;;
    --out-dir=*)            OUT_DIR="${1#*=}"; shift ;;
    --out-dir)              OUT_DIR="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 [--mode same-node|cross-node] [--bodies N] [--iters N] [--checkpoint N]"
      echo "       [--sleep SECS] [--source-node NODE] [--target-node NODE] [--skip-baseline]"
      echo "       [--out-dir DIR]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Determine target node based on mode
case "$MODE" in
  same-node)   TARGET_NODE="$SOURCE_NODE" ;;
  cross-node)  TARGET_NODE="$CROSS_NODE_TARGET" ;;
  *)           echo "Unknown mode: $MODE (use same-node or cross-node)" >&2; exit 1 ;;
esac

echo "=== N-Body CRIU Migration Test ==="
echo "Mode:        $MODE"
echo "Bodies:      $BODIES"
echo "Iterations:  $ITERS"
echo "Checkpoint:  $CHECKPOINT"
echo "Source node: $SOURCE_NODE"
echo "Target node: $TARGET_NODE"
echo "Sleep before migrate: ${SLEEP_BEFORE_MIGRATE}s"
echo ""

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
  local bodies="$1" iters="$2" checkpoint="$3" pod="$4" node="$5" out="$6"

  sed \
    -e "s/__BODIES__/${bodies}/g" \
    -e "s/__ITERS__/${iters}/g" \
    -e "s/__CHECKPOINT__/${checkpoint}/g" \
    -e "s/^  name: .*/  name: ${pod}/" \
    "$YAML_TEMPLATE" > "$out"

  # Pin pod to the specified node via nodeSelector.
  # Use awk instead of sed -i for portable multi-line insertion (macOS + Linux).
  awk -v node="$node" '
    { print }
    /restartPolicy: Never/ {
      print "  nodeSelector:"
      print "    kubernetes.io/hostname: " node
    }
  ' "$out" > "${out}.tmp" && mv "${out}.tmp" "$out"
}

# Extract SUMMARY from pod logs / checkpoint volume.
# Returns avg_ms value on stdout; writes full summary line to out_file.
extract_summary() {
  local pod="$1" out_file="$2"
  local summary

  # Try kubectl logs first (captures stdout)
  summary="$(k logs -n "$NAMESPACE" "$pod" 2>/dev/null | grep -E 'SUMMARY ' | tail -n 1 || true)"

  # Fallbacks: try reading from log files inside the container
  for logpath in /tmp/checkpoints/summary.txt /script-data/container.log; do
    if [[ -z "$summary" ]]; then
      summary="$(k exec -n "$NAMESPACE" "$pod" -- cat "$logpath" 2>/dev/null | grep -E 'SUMMARY ' | tail -n 1 || true)"
    fi
  done

  echo "$summary" > "$out_file"

  local avg
  avg="$(echo "$summary" | sed -nE 's/.*avg_ms=([0-9]+).*/\1/p')"

  if [[ -z "$avg" ]]; then
    return 1
  fi

  echo "$avg"
}

now_ms() { echo $(( $(date +%s) * 1000 )); }

# ---------------------------------------------
# Preconditions
# ---------------------------------------------
need_cmd kubectl
need_cmd sed

[[ -f "$YAML_TEMPLATE" ]] || { echo "YAML template not found: $YAML_TEMPLATE" >&2; exit 1; }
if [[ "$MIGRATOR_CMD" == ./* ]] || [[ "$MIGRATOR_CMD" == /* ]]; then
  [[ -x "$MIGRATOR_CMD" ]] || { echo "Migrator not executable: $MIGRATOR_CMD" >&2; exit 1; }
fi

OUT_DIR="${OUT_DIR}/$(ts)_${MODE}"
mkdir -p "$OUT_DIR"

results_csv="${OUT_DIR}/results.csv"
echo "timestamp,mode,bodies,iters,checkpoint,baseline_ms,migration_time_ms,restored_runtime_ms,delta_vs_baseline_ms,source_node,target_node,migration_rc" \
  > "$results_csv"

k delete pods --all -n "$NAMESPACE"

# ---------------------------------------------
# Phase 1: Baseline (optional)
# ---------------------------------------------
baseline_ms=""
if [[ "$SKIP_BASELINE" != "true" ]]; then
  echo "--- Phase 1: Baseline run (no migration) ---"

  baseline_pod="${POD_BASENAME}-baseline"
  baseline_yaml="${OUT_DIR}/${baseline_pod}.yaml"

  pod_exists "$baseline_pod" && k delete pod "$baseline_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true

  render_yaml "$BODIES" "$ITERS" "$CHECKPOINT" "$baseline_pod" "$SOURCE_NODE" "$baseline_yaml"
  k apply -f "$baseline_yaml" -n "$NAMESPACE" >/dev/null

  echo "Waiting for baseline pod to start..."
  wait_for_phase "$baseline_pod" "Running" "Succeeded" 120 || true

  echo "Waiting for baseline pod to complete..."
  wait_for_phase "$baseline_pod" "Succeeded" "Failed" 1200 || true

  k logs -n "$NAMESPACE" "$baseline_pod" > "${OUT_DIR}/baseline_kubectl_logs.log" 2>&1 || true

  baseline_ms="$(extract_summary "$baseline_pod" "${OUT_DIR}/baseline_summary.txt" || true)"
  if [[ -n "$baseline_ms" ]]; then
    echo "Baseline completed: ${baseline_ms} ms"
  else
    echo "WARNING: Baseline SUMMARY not found/parsable; see ${OUT_DIR}/baseline_kubectl_logs.log" >&2
  fi

  k delete pod "$baseline_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true
else
  echo "--- Phase 1: Skipped (--skip-baseline) ---"
fi

# ---------------------------------------------
# Phase 2: Migration run
# ---------------------------------------------
echo ""
echo "--- Phase 2: Migration run (mode=$MODE) ---"

mig_pod="${POD_BASENAME}-mig"
restored_pod="${mig_pod}-1"
mig_yaml="${OUT_DIR}/${mig_pod}.yaml"

pod_exists "$mig_pod" && k delete pod "$mig_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true
pod_exists "$restored_pod" && k delete pod "$restored_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true

render_yaml "$BODIES" "$ITERS" "$CHECKPOINT" "$mig_pod" "$SOURCE_NODE" "$mig_yaml"
k apply -f "$mig_yaml" -n "$NAMESPACE" >/dev/null

echo "Waiting for migration pod to start running..."
# Use phase-based wait instead of condition=Ready — if the pod finishes
# very fast, it goes straight to Succeeded and condition=Ready never fires.
wait_for_phase "$mig_pod" "Running" "Succeeded" 120 || true

mig_phase="$(pod_phase "$mig_pod")"
mig_src_node="$(pod_node "$mig_pod")"
echo "Pod $mig_pod phase=$mig_phase on node: $mig_src_node"

if [[ "$mig_phase" == "Succeeded" || "$mig_phase" == "Failed" ]]; then
  echo "ERROR: Pod already finished (phase=$mig_phase) before migration could trigger." >&2
  echo "Increase --bodies or --iters so the simulation runs longer." >&2
  k logs -n "$NAMESPACE" "$mig_pod" > "${OUT_DIR}/original_kubectl_logs.log" 2>&1 || true
  k delete pod "$mig_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true
  exit 1
fi

echo "Sleeping ${SLEEP_BEFORE_MIGRATE}s before triggering migration..."
sleep "$SLEEP_BEFORE_MIGRATE"

# Trigger migration
echo "Triggering migration: $mig_pod -> $TARGET_NODE"
mig_start_ms="$(now_ms)"
set +e
"$MIGRATOR_CMD" --migration --pod "$mig_pod" --target-node "$TARGET_NODE" \
  >"${OUT_DIR}/migrator_stdout.log" 2>"${OUT_DIR}/migrator_stderr.log"
mig_rc=$?
set -e
mig_end_ms="$(now_ms)"
migration_time_ms=$((mig_end_ms - mig_start_ms))

echo "Migration command completed: rc=$mig_rc time=${migration_time_ms}ms"

# Wait for original pod to finish
wait_for_phase "$mig_pod" "Succeeded" "Failed" 1200 || true
k logs -n "$NAMESPACE" "$mig_pod" > "${OUT_DIR}/original_kubectl_logs.log" 2>&1 || true

# Wait for restored pod to appear
echo "Waiting for restored pod ${restored_pod}..."
created=0
for _ in $(seq 1 120); do
  if pod_exists "$restored_pod"; then
    created=1
    break
  fi
  sleep 1
done

if [[ $created -ne 1 ]]; then
  echo "WARNING: Restored pod ${restored_pod} never appeared. See migrator logs." >&2
fi

restored_runtime_ms=""
mig_dst_node=""

if pod_exists "$restored_pod"; then
  wait_for_phase "$restored_pod" "Succeeded" "Failed" 1200 || true
  mig_dst_node="$(pod_node "$restored_pod")"
  k logs -n "$NAMESPACE" "$restored_pod" > "${OUT_DIR}/restored_kubectl_logs.log" 2>&1 || true

  restored_runtime_ms="$(extract_summary "$restored_pod" "${OUT_DIR}/restored_summary.txt" || true)"
  if [[ -n "$restored_runtime_ms" ]]; then
    echo "Restored pod completed: ${restored_runtime_ms} ms (on node: $mig_dst_node)"
  else
    echo "WARNING: Restored pod SUMMARY not found; see ${OUT_DIR}/restored_kubectl_logs.log" >&2
  fi
else
  : > "${OUT_DIR}/restored_kubectl_logs.log"
fi

# Cleanup pods
pod_exists "$mig_pod" && k delete pod "$mig_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true
pod_exists "$restored_pod" && k delete pod "$restored_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true

# ---------------------------------------------
# Phase 3: Compare + record
# ---------------------------------------------
echo ""
echo "--- Phase 3: Results ---"

delta_ms=""
if [[ -n "${baseline_ms:-}" && -n "${restored_runtime_ms:-}" ]]; then
  delta_ms=$((restored_runtime_ms - baseline_ms))
fi

echo "$(ts),$MODE,$BODIES,$ITERS,$CHECKPOINT,${baseline_ms:-},${migration_time_ms},${restored_runtime_ms:-},${delta_ms:-},$mig_src_node,$mig_dst_node,$mig_rc" \
  >> "$results_csv"

echo ""
echo "=== Results Summary ==="
echo "Mode:                $MODE"
echo "Baseline:            ${baseline_ms:-N/A} ms"
echo "Migration time:      ${migration_time_ms} ms"
echo "Restored runtime:    ${restored_runtime_ms:-N/A} ms"
echo "Delta vs baseline:   ${delta_ms:-N/A} ms"
echo "Source node:         $mig_src_node"
echo "Target node:         ${mig_dst_node:-N/A}"
echo "Migration rc:        $mig_rc"
echo ""
echo "Results CSV:         $results_csv"
echo "Artifacts:           $OUT_DIR"
echo "DONE."
