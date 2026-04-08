#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------
# Carbon-Aware Single-Pod Migration Test Harness
#
# Controller-driven mode: deploys a long-running pod, lets the controller
# drive migrations based on carbon-aware scheduling policies, and records
# carbon usage across the run.
#
# Phases:
#   1) Optional baseline: run pod to completion without controller
#   2) Controller-driven: deploy pod, update scheduler-config ConfigMap,
#      poll for migration events by watching pod names
#   3) Carbon accounting: for each hour, query metadata service for carbon
#      intensity of the region the pod was in, sum total carbon
#
# Requirements:
#   - nbody-mpi:local image loaded into Kind
#   - Controller deployed and configured
#   - Metadata service running (for carbon queries)
#   - YAML template with placeholders
# ---------------------------------------------

NAMESPACE="test-namespace"
CONTROLLER_NAMESPACE="monitor"
YAML_TEMPLATE="${YAML_TEMPLATE:-./tests/carbon-single-pod/carbon-testpod.yml}"
OUT_DIR="${OUT_DIR:-../data/carbon-single-pod}"
POD_BASENAME="${POD_BASENAME:-carbon-pod}"
METADATA_URL="${METADATA_URL:-http://localhost:8008}"

# Simulation defaults — long-running for carbon testing
BODIES="${BODIES:-10000}"
ITERS="${ITERS:-5000}"
CHECKPOINT="${CHECKPOINT:-$ITERS}"
EXPECTED_DURATION="${EXPECTED_DURATION:-360}"  # 6 hours in minutes

# Scheduling policy (1-5)
POLICY="${POLICY:-4}"

# Scheduler time (Unix timestamp)
SCHEDULER_TIME="${SCHEDULER_TIME:-1609459200}"  # 2021-01-01 00:00:00 UTC

# Controller timing — must match controller.yml env vars
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-30}"
SIM_HOURS_PER_CHECK="${SIM_HOURS_PER_CHECK:-1}"

# Mode: same-node or cross-node
MODE="cross-node"

# Baseline
SKIP_BASELINE="${SKIP_BASELINE:-false}"

# Node names (Kind defaults)
SOURCE_NODE="${SOURCE_NODE:-kind-worker}"

# Parse CLI arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --bodies=*)             BODIES="${1#*=}"; shift ;;
    --bodies)               BODIES="$2"; shift 2 ;;
    --iters=*)              ITERS="${1#*=}"; shift ;;
    --iters)                ITERS="$2"; shift 2 ;;
    --checkpoint=*)         CHECKPOINT="${1#*=}"; shift ;;
    --checkpoint)           CHECKPOINT="$2"; shift 2 ;;
    --policy=*)             POLICY="${1#*=}"; shift ;;
    --policy)               POLICY="$2"; shift 2 ;;
    --scheduler-time=*)     SCHEDULER_TIME="${1#*=}"; shift ;;
    --scheduler-time)       SCHEDULER_TIME="$2"; shift 2 ;;
    --mode=*)               MODE="${1#*=}"; shift ;;
    --mode)                 MODE="$2"; shift 2 ;;
    --skip-baseline)        SKIP_BASELINE=true; shift ;;
    --expected-duration=*)  EXPECTED_DURATION="${1#*=}"; shift ;;
    --expected-duration)    EXPECTED_DURATION="$2"; shift 2 ;;
    --source-node=*)        SOURCE_NODE="${1#*=}"; shift ;;
    --source-node)          SOURCE_NODE="$2"; shift 2 ;;
    --out-dir=*)            OUT_DIR="${1#*=}"; shift ;;
    --out-dir)              OUT_DIR="$2"; shift 2 ;;
    --metadata-url=*)       METADATA_URL="${1#*=}"; shift ;;
    --metadata-url)         METADATA_URL="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --bodies N              Number of bodies for simulation (default: 10000)"
      echo "  --iters N               Number of iterations (default: 5000)"
      echo "  --checkpoint N          Checkpoint interval (default: 100)"
      echo "  --policy P              Scheduling policy 1-4 (default: 4)"
      echo "  --scheduler-time T      Unix timestamp for scheduler (default: 1609459200)"
      echo "  --mode MODE             same-node or cross-node (default: cross-node)"
      echo "  --expected-duration M   Expected duration in minutes (default: 360)"
      echo "  --source-node NODE      Source node name (default: kind-worker)"
      echo "  --skip-baseline         Skip baseline run"
      echo "  --out-dir DIR           Output directory (default: ../data/carbon-single-pod)"
      echo "  --metadata-url URL      Metadata service URL (default: http://localhost:8008)"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Validate policy
if ! [[ "$POLICY" =~ ^[12345]$ ]]; then
  echo "ERROR: Invalid policy: $POLICY (must be 1, 2, 3, 4, or 5)" >&2
  exit 1
fi

echo "=== Carbon-Aware Single-Pod Migration Test ==="
echo "Policy:            $POLICY"
echo "Bodies:            $BODIES"
echo "Iterations:        $ITERS"
echo "Checkpoint:        $CHECKPOINT"
echo "Expected duration: ${EXPECTED_DURATION} minutes"
echo "Scheduler time:    $SCHEDULER_TIME"
echo "Mode:              $MODE"
echo "Source node:       $SOURCE_NODE"
echo ""

# ---------------------------------------------
# Helpers (modeled on antibody-sim harness)
# ---------------------------------------------
k() {
  kubectl "$@" 2> >(grep -v "memcache.go" | grep -v "metrics.k8s.io/v1beta1" >&2)
}

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing command: $1" >&2; exit 1; }; }
ts() { date +"%Y%m%d_%H%M%S"; }

pod_exists() { k get pod "$1" -n "$NAMESPACE" >/dev/null 2>&1; }
pod_phase() { k get pod "$1" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || true; }
pod_node() { k get pod "$1" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}' 2>/dev/null || true; }
pod_region() {
  local node="$1"
  k get node "$node" -o jsonpath='{.metadata.labels.REGION}' 2>/dev/null || echo "unknown"
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
    sleep 2
  done
}

render_yaml() {
  local bodies="$1" iters="$2" checkpoint="$3" pod="$4" node="$5" expected_dur="$6" out="$7"

  sed \
    -e "s/__BODIES__/${bodies}/g" \
    -e "s/__ITERS__/${iters}/g" \
    -e "s/__CHECKPOINT__/${checkpoint}/g" \
    -e "s/__EXPECTED_DURATION__/${expected_dur}/g" \
    -e "s/^  name: .*/  name: ${pod}/" \
    "$YAML_TEMPLATE" > "$out"

  # Pin pod to the specified node via nodeSelector
  awk -v node="$node" '
    { print }
    /restartPolicy: Never/ {
      print "  nodeSelector:"
      print "    kubernetes.io/hostname: " node
    }
  ' "$out" > "${out}.tmp" && mv "${out}.tmp" "$out"
}

extract_summary() {
  local pod="$1" out_file="$2"
  local summary

  summary="$(k logs -n "$NAMESPACE" "$pod" 2>/dev/null | grep -E 'SUMMARY ' | tail -n 1 || true)"

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

# Find the current active pod (latest in the migration chain)
find_active_pod() {
  local base="$1"
  local latest=""
  local max_counter=-1

  # Check base pod
  if pod_exists "$base"; then
    local ph
    ph="$(pod_phase "$base")"
    if [[ "$ph" == "Running" ]]; then
      latest="$base"
      max_counter=0
    fi
  fi

  # Check numbered pods — don't break on gaps since old pods get cleaned up
  for i in $(seq 1 50); do
    local candidate="${base}-${i}"
    if pod_exists "$candidate"; then
      local ph
      ph="$(pod_phase "$candidate")"
      if [[ "$ph" == "Running" ]]; then
        latest="$candidate"
        max_counter=$i
      fi
    fi
  done

  echo "$latest"
}

# Fetch the full forecast from the metadata service and cache it.
# Returns a JSON file path that can be queried for per-region/per-hour intensity.
FORECAST_CACHE=""
fetch_full_forecast() {
  local duration="$1"
  local cache_file="${OUT_DIR}/forecast_cache.json"

  if [[ -n "$FORECAST_CACHE" && -f "$FORECAST_CACHE" ]]; then
    echo "$FORECAST_CACHE"
    return
  fi

  local result
  result="$(curl -s --max-time 30 "${METADATA_URL}" \
    -H "Content-Type: application/json" \
    -d "{\"duration\": ${duration}}" 2>/dev/null || echo "")"

  if [[ -n "$result" ]]; then
    echo "$result" > "$cache_file"
    FORECAST_CACHE="$cache_file"
    echo "$cache_file"
  else
    echo ""
  fi
}

# Query carbon intensity for a specific region and simulation timestamp
# from the cached forecast data.
query_carbon_intensity() {
  local region="$1"
  local sim_timestamp="$2"
  local forecast_file="$3"

  if [[ -z "$forecast_file" || ! -f "$forecast_file" ]]; then
    echo "0"
    return
  fi

  local intensity
  intensity="$(python3 -c "
import sys, json
from datetime import datetime, timezone

target_region = '${region}'
target_ts = int(${sim_timestamp})

try:
    with open('${forecast_file}') as f:
        data = json.load(f)

    # Look in region_forecasts for the specific region
    region_data = data.get('region_forecasts', {}).get(target_region, {})
    points = region_data.get('forecast_data', [])

    if points:
        # Find the point closest to our target simulation timestamp
        best_intensity = None
        best_diff = float('inf')
        for point in points:
            if len(point) >= 3:
                ts_str = point[0].split('+')[0].strip()
                try:
                    pt_dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                    pt_ts = int(pt_dt.timestamp())
                    diff = abs(pt_ts - target_ts)
                    if diff < best_diff:
                        best_diff = diff
                        best_intensity = float(point[2])
                except:
                    continue
        if best_intensity is not None and best_diff <= 7200:  # within 2 hours
            print(best_intensity)
            sys.exit(0)

    # Fallback: check min_forecast
    for point in data.get('min_forecast', {}).get('forecast_data', []):
        if len(point) >= 3 and point[1] == target_region:
            ts_str = point[0].split('+')[0].strip()
            try:
                pt_dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                pt_ts = int(pt_dt.timestamp())
                if abs(pt_ts - target_ts) <= 7200:
                    print(float(point[2]))
                    sys.exit(0)
            except:
                continue

    print('0')
except Exception as e:
    print('0')
" 2>/dev/null || echo "0")"
  echo "$intensity"
}

# ---------------------------------------------
# Preconditions
# ---------------------------------------------
need_cmd kubectl
need_cmd sed
need_cmd curl

[[ -f "$YAML_TEMPLATE" ]] || { echo "YAML template not found: $YAML_TEMPLATE" >&2; exit 1; }

OUT_DIR="${OUT_DIR}/$(ts)_policy${POLICY}"
mkdir -p "$OUT_DIR"

results_csv="${OUT_DIR}/results.csv"
echo "timestamp,policy,bodies,iters,expected_duration_min,baseline_ms,total_runtime_ms,num_migrations,total_carbon_gco2,migration_events" \
  > "$results_csv"

migration_log="${OUT_DIR}/migration_events.csv"
echo "event_num,timestamp,sim_time,pod_name,source_node,source_region,target_node,target_region" \
  > "$migration_log"

# ---------------------------------------------
# Update scheduler-config ConfigMap with desired policy
# ---------------------------------------------
echo "--- Updating scheduler-config with policy=$POLICY, time=$SCHEDULER_TIME ---"
kubectl create configmap scheduler-config \
  --from-literal=scheduler-time="$SCHEDULER_TIME" \
  --from-literal=scheduling-policy="$POLICY" \
  -n "$CONTROLLER_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f - > /dev/null

kubectl create configmap scheduler-config \
  --from-literal=scheduler-time="$SCHEDULER_TIME" \
  --from-literal=scheduling-policy="$POLICY" \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f - > /dev/null

echo "ConfigMap updated. Restarting controller to pick up new config..."
kubectl rollout restart deployment controller -n "$CONTROLLER_NAMESPACE" > /dev/null 2>&1
kubectl rollout status deployment controller -n "$CONTROLLER_NAMESPACE" --timeout=120s > /dev/null 2>&1
echo "Controller restarted."

# Clean up any existing test pods
k delete pods -l name="${POD_BASENAME}" -n "$NAMESPACE" --ignore-not-found=true > /dev/null 2>&1 || true
for i in $(seq 0 20); do
  local_pod="${POD_BASENAME}"
  [[ $i -gt 0 ]] && local_pod="${POD_BASENAME}-${i}"
  pod_exists "$local_pod" && k delete pod "$local_pod" -n "$NAMESPACE" --wait=true > /dev/null 2>&1 || true
done

# ---------------------------------------------
# Phase 1: Baseline (optional)
# ---------------------------------------------
baseline_ms=""
if [[ "$SKIP_BASELINE" != "true" ]]; then
  echo ""
  echo "--- Phase 1: Baseline run (no controller migration) ---"

  baseline_pod="${POD_BASENAME}-baseline"
  baseline_yaml="${OUT_DIR}/${baseline_pod}.yaml"

  pod_exists "$baseline_pod" && k delete pod "$baseline_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true

  render_yaml "$BODIES" "$ITERS" "$CHECKPOINT" "$baseline_pod" "$SOURCE_NODE" "$EXPECTED_DURATION" "$baseline_yaml"
  k apply -f "$baseline_yaml" -n "$NAMESPACE" >/dev/null

  echo "Waiting for baseline pod to start..."
  wait_for_phase "$baseline_pod" "Running" "Succeeded" 120 || true

  echo "Waiting for baseline pod to complete..."
  wait_for_phase "$baseline_pod" "Succeeded" "Failed" 86400 || true

  k logs -n "$NAMESPACE" "$baseline_pod" > "${OUT_DIR}/baseline_kubectl_logs.log" 2>&1 || true

  baseline_ms="$(extract_summary "$baseline_pod" "${OUT_DIR}/baseline_summary.txt" || true)"
  if [[ -n "$baseline_ms" ]]; then
    echo "Baseline completed: ${baseline_ms} ms"
  else
    echo "WARNING: Baseline SUMMARY not found/parsable; see ${OUT_DIR}/baseline_kubectl_logs.log" >&2
  fi

  k delete pod "$baseline_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true
else
  echo ""
  echo "--- Phase 1: Skipped (--skip-baseline) ---"
fi

# ---------------------------------------------
# Phase 2: Controller-Driven Migration Run
# ---------------------------------------------
echo ""
echo "--- Phase 2: Controller-driven migration run (policy=$POLICY) ---"

mig_pod="${POD_BASENAME}"
mig_yaml="${OUT_DIR}/${mig_pod}.yaml"

render_yaml "$BODIES" "$ITERS" "$CHECKPOINT" "$mig_pod" "$SOURCE_NODE" "$EXPECTED_DURATION" "$mig_yaml"
k apply -f "$mig_yaml" -n "$NAMESPACE" >/dev/null

echo "Waiting for pod to start running..."
wait_for_phase "$mig_pod" "Running" "Succeeded" 120 || true

mig_start_ms="$(now_ms)"
echo "Pod $mig_pod started at $(date). Monitoring for controller-driven migrations..."

# Track migration events
migration_count=0
last_known_pod="$mig_pod"
last_known_node="$(pod_node "$mig_pod")"
last_known_region="$(pod_region "$last_known_node")"

# Record initial placement
echo "Initial placement: $mig_pod on $last_known_node (region: $last_known_region)"

# Carbon tracking: list of (sim_hour_timestamp, region) tuples
declare -a carbon_regions=()
current_sim_time="$SCHEDULER_TIME"
carbon_regions+=("${current_sim_time}:${last_known_region}")

# Poll for migration events until workload completes.
# The controller checks every CHECK_INTERVAL_SECONDS real seconds and advances
# SIM_HOURS_PER_CHECK simulated hours per check. We mirror this to track carbon
# for every simulated hour, not just migration events.
poll_interval=10  # seconds between polls
max_poll_time=86400  # 24 hours max real time

# Match the controller's check interval to know when sim time advances
controller_check_interval="${CHECK_INTERVAL_SECONDS:-30}"
sim_hours_per_check="${SIM_HOURS_PER_CHECK:-1}"

poll_start="$(date +%s)"
last_sim_advance="$(date +%s)"

while true; do
  # Find the currently active pod
  active_pod="$(find_active_pod "$POD_BASENAME")"

  if [[ -z "$active_pod" ]]; then
    # No running pod found — check if any pod is still running/pending
    all_done=true
    for i in $(seq 0 50); do
      check_pod="${POD_BASENAME}"
      [[ $i -gt 0 ]] && check_pod="${POD_BASENAME}-${i}"
      if pod_exists "$check_pod"; then
        ph="$(pod_phase "$check_pod")"
        if [[ "$ph" == "Running" || "$ph" == "Pending" ]]; then
          all_done=false
          break
        fi
      fi
    done

    if [[ "$all_done" == "true" ]]; then
      echo "All pods completed."
      break
    fi
  fi

  if [[ -n "$active_pod" && "$active_pod" != "$last_known_pod" ]]; then
    # Migration detected!
    migration_count=$((migration_count + 1))
    new_node="$(pod_node "$active_pod")"
    new_region="$(pod_region "$new_node")"

    echo "  Migration #${migration_count}: ${last_known_pod} (${last_known_node}/${last_known_region}) -> ${active_pod} (${new_node}/${new_region})"
    echo "${migration_count},$(date -u +"%Y-%m-%dT%H:%M:%SZ"),${current_sim_time},${active_pod},${last_known_node},${last_known_region},${new_node},${new_region}" \
      >> "$migration_log"

    last_known_pod="$active_pod"
    last_known_node="$new_node"
    last_known_region="$new_region"
  fi

  # Advance simulation time in sync with the controller's check interval.
  # Every controller_check_interval real seconds, the controller advances
  # sim_hours_per_check simulated hours. We record the region for each hour.
  now="$(date +%s)"
  elapsed_since_advance=$((now - last_sim_advance))
  if (( elapsed_since_advance >= controller_check_interval )); then
    for _h in $(seq 1 "$sim_hours_per_check"); do
      current_sim_time=$((current_sim_time + 3600))
      carbon_regions+=("${current_sim_time}:${last_known_region}")
    done
    last_sim_advance="$now"
  fi

  # Timeout check
  if (( now - poll_start > max_poll_time )); then
    echo "WARNING: Poll timeout reached (${max_poll_time}s)" >&2
    break
  fi

  sleep "$poll_interval"
done

mig_end_ms="$(now_ms)"
total_runtime_ms=$((mig_end_ms - mig_start_ms))

# Collect logs from all pods in the chain
for i in $(seq 0 $((migration_count + 5))); do
  log_pod="${POD_BASENAME}"
  [[ $i -gt 0 ]] && log_pod="${POD_BASENAME}-${i}"
  if pod_exists "$log_pod"; then
    k logs -n "$NAMESPACE" "$log_pod" > "${OUT_DIR}/${log_pod}_logs.log" 2>&1 || true
  fi
done

# ---------------------------------------------
# Phase 3: Carbon Accounting
# ---------------------------------------------
echo ""
echo "--- Phase 3: Carbon Accounting ---"

# Start metadata service port-forward for carbon queries
PORTFWD_PID=""
echo "Starting metadata service port-forward..."
kubectl port-forward -n "$CONTROLLER_NAMESPACE" svc/metadata-service 8008:8008 >/dev/null 2>&1 &
PORTFWD_PID=$!
# Give port-forward time to establish
sleep 3

# Verify port-forward is working
if ! kill -0 "$PORTFWD_PID" 2>/dev/null; then
  echo "WARNING: Port-forward failed to start. Carbon data may be unavailable." >&2
  PORTFWD_PID=""
fi

# Cleanup port-forward on exit
cleanup_portfwd() {
  if [[ -n "$PORTFWD_PID" ]]; then
    kill "$PORTFWD_PID" 2>/dev/null || true
    wait "$PORTFWD_PID" 2>/dev/null || true
  fi
}
trap cleanup_portfwd EXIT

# Calculate how many simulated hours the run covered
sim_hours=$(( (current_sim_time - SCHEDULER_TIME) / 3600 ))
if [[ $sim_hours -lt 1 ]]; then
  sim_hours=${#carbon_regions[@]}
fi

# Fetch full forecast covering the entire simulation period
echo "Fetching forecast for ${sim_hours} hours from metadata service..."
forecast_file="$(fetch_full_forecast "$sim_hours")"

if [[ -z "$forecast_file" ]]; then
  echo "WARNING: Could not fetch forecast data. Ensure metadata service is running in the cluster." >&2
fi

total_carbon=0
hours_tracked=0

# Calculate carbon for each hour segment
for entry in "${carbon_regions[@]}"; do
  sim_ts="${entry%%:*}"
  region="${entry##*:}"

  # Query carbon intensity for this region at this simulation time
  intensity="$(query_carbon_intensity "$region" "$sim_ts" "$forecast_file")"

  if [[ -n "$intensity" && "$intensity" != "0" ]]; then
    # Carbon = time (hours) * power (kW) * intensity (gCO2/kWh)
    # Assume power = 1 kW, each segment = 1 hour, so carbon = intensity
    hour_carbon="$intensity"
    total_carbon="$(echo "$total_carbon + $hour_carbon" | bc -l 2>/dev/null || echo "$total_carbon")"
    hours_tracked=$((hours_tracked + 1))
    echo "  Hour ${hours_tracked}: region=$region intensity=${intensity} gCO2/kWh carbon=${hour_carbon} gCO2"
  else
    echo "  Hour $((hours_tracked + 1)): region=$region intensity=unknown (metadata unavailable)"
    hours_tracked=$((hours_tracked + 1))
  fi
done

echo ""
echo "Total carbon: ${total_carbon} gCO2 over ${hours_tracked} hours"

# Stop port-forward now that carbon accounting is done
if [[ -n "$PORTFWD_PID" ]]; then
  kill "$PORTFWD_PID" 2>/dev/null || true
  wait "$PORTFWD_PID" 2>/dev/null || true
  PORTFWD_PID=""
  echo "Port-forward stopped."
fi

# Clean up pods
for i in $(seq 0 $((migration_count + 5))); do
  cleanup_pod="${POD_BASENAME}"
  [[ $i -gt 0 ]] && cleanup_pod="${POD_BASENAME}-${i}"
  pod_exists "$cleanup_pod" && k delete pod "$cleanup_pod" -n "$NAMESPACE" --wait=true >/dev/null 2>&1 || true
done

# ---------------------------------------------
# Results
# ---------------------------------------------
echo ""
echo "--- Results ---"

migration_events_str=""
if [[ -f "$migration_log" ]]; then
  migration_events_str="$(tail -n +2 "$migration_log" | tr '\n' ';' | sed 's/;$//')"
fi

echo "$(ts),$POLICY,$BODIES,$ITERS,$EXPECTED_DURATION,${baseline_ms:-},${total_runtime_ms},${migration_count},${total_carbon},\"${migration_events_str}\"" \
  >> "$results_csv"

echo ""
echo "=== Results Summary ==="
echo "Policy:              $POLICY"
echo "Baseline:            ${baseline_ms:-N/A} ms"
echo "Total runtime:       ${total_runtime_ms} ms"
echo "Migrations:          ${migration_count}"
echo "Total carbon:        ${total_carbon} gCO2"
echo "Hours tracked:       ${hours_tracked}"
echo ""
echo "Results CSV:         $results_csv"
echo "Migration log:       $migration_log"
echo "Artifacts:           $OUT_DIR"
echo "DONE."
