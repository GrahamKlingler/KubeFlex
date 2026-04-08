#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# Compare carbon-aware migration policies (2, 3, 4)
#
# Runs the carbon migration test harness for each policy with the same
# parameters and produces a comparison summary.
# ---------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${SCRIPT_DIR}/run_carbon_migration_test.sh"
OUT_DIR="${OUT_DIR:-../data/carbon-single-pod/comparison_$(date +%Y%m%d_%H%M%S)}"

# Default parameters (can be overridden via environment)
BODIES="${BODIES:-10000}"
ITERS="${ITERS:-5000}"
CHECKPOINT="${CHECKPOINT:-100}"
EXPECTED_DURATION="${EXPECTED_DURATION:-360}"
SCHEDULER_TIME="${SCHEDULER_TIME:-1609459200}"
SKIP_BASELINE="${SKIP_BASELINE:-false}"

# Policies to compare
POLICIES="${POLICIES:-2 3 4}"

# Parse CLI arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --bodies=*)             BODIES="${1#*=}"; shift ;;
    --bodies)               BODIES="$2"; shift 2 ;;
    --iters=*)              ITERS="${1#*=}"; shift ;;
    --iters)                ITERS="$2"; shift 2 ;;
    --checkpoint=*)         CHECKPOINT="${1#*=}"; shift ;;
    --checkpoint)           CHECKPOINT="$2"; shift 2 ;;
    --expected-duration=*)  EXPECTED_DURATION="${1#*=}"; shift ;;
    --expected-duration)    EXPECTED_DURATION="$2"; shift 2 ;;
    --scheduler-time=*)     SCHEDULER_TIME="${1#*=}"; shift ;;
    --scheduler-time)       SCHEDULER_TIME="$2"; shift 2 ;;
    --policies=*)           POLICIES="${1#*=}"; shift ;;
    --policies)             POLICIES="$2"; shift 2 ;;
    --skip-baseline)        SKIP_BASELINE=true; shift ;;
    --out-dir=*)            OUT_DIR="${1#*=}"; shift ;;
    --out-dir)              OUT_DIR="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --bodies N              Number of bodies (default: 10000)"
      echo "  --iters N               Number of iterations (default: 5000)"
      echo "  --checkpoint N          Checkpoint interval (default: 100)"
      echo "  --expected-duration M   Expected duration in minutes (default: 360)"
      echo "  --scheduler-time T      Unix timestamp (default: 1609459200)"
      echo "  --policies 'P1 P2 ...'  Policies to compare (default: '2 3 4')"
      echo "  --skip-baseline         Skip baseline for all runs"
      echo "  --out-dir DIR           Output directory"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$OUT_DIR"
comparison_csv="${OUT_DIR}/comparison.csv"
echo "policy,bodies,iters,expected_duration_min,total_runtime_ms,num_migrations,total_carbon_gco2" \
  > "$comparison_csv"

echo "=========================================="
echo "Carbon Policy Comparison"
echo "=========================================="
echo "Policies:          $POLICIES"
echo "Bodies:            $BODIES"
echo "Iterations:        $ITERS"
echo "Checkpoint:        $CHECKPOINT"
echo "Expected duration: ${EXPECTED_DURATION} min"
echo "Scheduler time:    $SCHEDULER_TIME"
echo "Output:            $OUT_DIR"
echo ""

baseline_done=false

for policy in $POLICIES; do
  echo ""
  echo "=========================================="
  echo "Running Policy $policy"
  echo "=========================================="

  policy_out="${OUT_DIR}/policy_${policy}"
  mkdir -p "$policy_out"

  baseline_flag=""
  if [[ "$SKIP_BASELINE" == "true" ]] || [[ "$baseline_done" == "true" ]]; then
    baseline_flag="--skip-baseline"
  fi

  # Run the harness
  OUT_DIR="$policy_out" "$HARNESS" \
    --bodies="$BODIES" \
    --iters="$ITERS" \
    --checkpoint="$CHECKPOINT" \
    --policy="$policy" \
    --scheduler-time="$SCHEDULER_TIME" \
    --expected-duration="$EXPECTED_DURATION" \
    $baseline_flag \
    2>&1 | tee "${policy_out}/harness_output.log"

  # After first run with baseline, skip for subsequent
  baseline_done=true

  # Extract results from the harness output
  result_file="$(find "$policy_out" -name "results.csv" -type f | head -n 1)"
  if [[ -n "$result_file" ]]; then
    # Get the last data line (skip header)
    last_line="$(tail -n 1 "$result_file")"
    # Extract fields: timestamp,policy,bodies,iters,expected_duration_min,baseline_ms,total_runtime_ms,num_migrations,total_carbon_gco2,migration_events
    runtime="$(echo "$last_line" | cut -d',' -f7)"
    migrations="$(echo "$last_line" | cut -d',' -f8)"
    carbon="$(echo "$last_line" | cut -d',' -f9)"

    echo "${policy},${BODIES},${ITERS},${EXPECTED_DURATION},${runtime},${migrations},${carbon}" \
      >> "$comparison_csv"
  else
    echo "WARNING: No results found for policy $policy" >&2
    echo "${policy},${BODIES},${ITERS},${EXPECTED_DURATION},,," >> "$comparison_csv"
  fi
done

echo ""
echo "=========================================="
echo "Comparison Summary"
echo "=========================================="
echo ""

# Print comparison table
printf "%-8s %-15s %-12s %-15s\n" "Policy" "Runtime (ms)" "Migrations" "Carbon (gCO2)"
printf "%-8s %-15s %-12s %-15s\n" "------" "------------" "----------" "-------------"

while IFS=',' read -r pol bod it dur rt mig carb; do
  [[ "$pol" == "policy" ]] && continue  # skip header
  printf "%-8s %-15s %-12s %-15s\n" "$pol" "${rt:-N/A}" "${mig:-N/A}" "${carb:-N/A}"
done < "$comparison_csv"

echo ""
echo "Full comparison CSV: $comparison_csv"
echo "DONE."
