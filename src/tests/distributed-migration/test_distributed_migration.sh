#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Modular test script for the distributed migrator
#
# Test modules (run individually or combined):
#   deploy    - Deploy MPIJob and wait for workers
#   service   - Start the distributed migration service (port-forward)
#   migrate   - Trigger distributed migration (via HTTP or direct Python)
#   verify    - Verify migration results (pods, processes, logs)
#   cleanup   - Delete MPIJob, migrated pods, stop port-forward
#   all       - Run full pipeline: deploy -> service -> migrate -> verify -> cleanup
#
# Examples:
#   ./test_distributed_migration.sh --module all
#   ./test_distributed_migration.sh --module deploy
#   ./test_distributed_migration.sh --module deploy --module migrate --mode direct
#   ./test_distributed_migration.sh --module all --skip-cleanup
#   ./test_distributed_migration.sh --module all --target-nodes kind-worker2,kind-worker3
# =============================================================================

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()    { echo -e "${RED}[FAIL]${NC}  $*"; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

# ─── Defaults ────────────────────────────────────────────────────────────────
NAMESPACE="test-namespace"
MPIJOB_YAML=""   # auto-detected below
JOB_NAME="nbody-sim"
SOURCE_NODES=""  # auto-detected from running workers
TARGET_NODES=""  # must be provided or defaults to swapping worker nodes
SLEEP_BEFORE_MIGRATE=8
MIGRATE_MODE="http"       # "http" (via service API) or "direct" (python call)
SERVICE_PORT=8001         # local port for distributed migration service
SKIP_CLEANUP=false
MODULES=()
MONITOR_DURATION=15       # seconds to watch restored processes

# Output directory
TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)/data/distributed-migration-test/${TS}"

# Track state across modules
PF_PID=""   # port-forward PID

# ─── Parse args ──────────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
Usage: test_distributed_migration.sh [OPTIONS]

Modules (--module can be repeated):
  deploy          Deploy MPIJob and wait for workers to be running
  service         Port-forward the distributed migration service
  migrate         Trigger distributed migration
  verify          Verify migrated pods and processes
  cleanup         Delete test resources
  all             Run full pipeline (deploy -> service -> migrate -> verify -> cleanup)

Options:
  --module MOD         Module to run (repeatable, or "all")
  --mode MODE          Migration mode: "http" (default) or "direct" (python call)
  --job-name NAME      MPIJob name (default: nbody-sim)
  --mpijob-yaml PATH   Path to MPIJob manifest (auto-detected if omitted)
  --target-nodes N1,N2 Comma-separated target nodes (default: auto-swap)
  --sleep SECS         Seconds to wait before migrating (default: 8)
  --monitor SECS       Seconds to watch restored processes (default: 15)
  --service-port PORT  Local port for migration service (default: 8001)
  --skip-cleanup       Don't clean up after "all"
  --out-dir DIR        Output directory (default: data/distributed-migration-test/<ts>)
  --help               Show this help
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --module)          MODULES+=("$2"); shift 2 ;;
    --module=*)        MODULES+=("${1#*=}"); shift ;;
    --mode)            MIGRATE_MODE="$2"; shift 2 ;;
    --mode=*)          MIGRATE_MODE="${1#*=}"; shift ;;
    --job-name)        JOB_NAME="$2"; shift 2 ;;
    --job-name=*)      JOB_NAME="${1#*=}"; shift ;;
    --mpijob-yaml)     MPIJOB_YAML="$2"; shift 2 ;;
    --mpijob-yaml=*)   MPIJOB_YAML="${1#*=}"; shift ;;
    --target-nodes)    TARGET_NODES="$2"; shift 2 ;;
    --target-nodes=*)  TARGET_NODES="${1#*=}"; shift ;;
    --sleep)           SLEEP_BEFORE_MIGRATE="$2"; shift 2 ;;
    --sleep=*)         SLEEP_BEFORE_MIGRATE="${1#*=}"; shift ;;
    --monitor)         MONITOR_DURATION="$2"; shift 2 ;;
    --monitor=*)       MONITOR_DURATION="${1#*=}"; shift ;;
    --service-port)    SERVICE_PORT="$2"; shift 2 ;;
    --service-port=*)  SERVICE_PORT="${1#*=}"; shift ;;
    --skip-cleanup)    SKIP_CLEANUP=true; shift ;;
    --out-dir)         OUT_DIR="$2"; shift 2 ;;
    --out-dir=*)       OUT_DIR="${1#*=}"; shift ;;
    --help)            usage ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ ${#MODULES[@]} -eq 0 ]]; then
  echo "No modules specified. Use --module <name> or --module all" >&2
  echo "Run with --help for usage." >&2
  exit 1
fi

# Expand "all"
if [[ " ${MODULES[*]} " == *" all "* ]]; then
  MODULES=(deploy service migrate verify)
  if [[ "$SKIP_CLEANUP" == "false" ]]; then
    MODULES+=(cleanup)
  fi
fi

# Auto-detect MPIJob YAML
if [[ -z "$MPIJOB_YAML" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  for candidate in \
    "${SCRIPT_DIR}/../antibody-sim/nbody-mpijob-long.yml" \
    "${SCRIPT_DIR}/../antibody-sim/nbody-mpijob.yml" \
    "${SCRIPT_DIR}/../../tests/antibody-sim/nbody-mpijob.yml" \
    "./tests/antibody-sim/nbody-mpijob.yml"; do
    if [[ -f "$candidate" ]]; then
      MPIJOB_YAML="$candidate"
      break
    fi
  done
  if [[ -z "$MPIJOB_YAML" ]]; then
    warn "Could not auto-detect MPIJob YAML. Provide --mpijob-yaml if deploy module is used."
  fi
fi

mkdir -p "$OUT_DIR"

# ─── Helpers ─────────────────────────────────────────────────────────────────
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
      fail "Pod $pod already finished (phase=$ph)"; return 1
    fi
    now="$(date +%s)"
    if (( now - start > timeout )); then
      fail "Timed out waiting for $pod (current=$ph)"; return 1
    fi
    sleep 1
  done
}

get_worker_pods() {
  # Returns worker pod names sorted by name (rank order)
  k get pods -n "$NAMESPACE" \
    -l "training.kubeflow.org/job-role=worker" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort
}

get_pod_node() {
  local pod="$1"
  k get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}'
}

record() {
  # Append a key=value line to the run metadata file
  echo "$1" >> "${OUT_DIR}/metadata.txt"
}

# Cleanup port-forward on exit
cleanup_pf() {
  if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" 2>/dev/null; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup_pf EXIT

# ─── Module: deploy ──────────────────────────────────────────────────────────
module_deploy() {
  section "Module: deploy"

  if [[ -z "$MPIJOB_YAML" || ! -f "$MPIJOB_YAML" ]]; then
    fail "MPIJob YAML not found: ${MPIJOB_YAML:-<not set>}"
    fail "Provide --mpijob-yaml or ensure tests/antibody-sim/nbody-mpijob.yml exists"
    return 1
  fi

  info "Using MPIJob manifest: $MPIJOB_YAML"

  # Clean up any existing job
  info "Cleaning up existing MPIJob..."
  k delete mpijob "$JOB_NAME" -n "$NAMESPACE" 2>/dev/null || true
  k delete pods -l "training.kubeflow.org/job-name=$JOB_NAME" -n "$NAMESPACE" 2>/dev/null || true
  sleep 3

  # Deploy
  info "Applying MPIJob..."
  kubectl apply -f "$MPIJOB_YAML" -n "$NAMESPACE" >/dev/null
  record "mpijob_yaml=$MPIJOB_YAML"
  record "job_name=$JOB_NAME"

  # Wait for worker pods
  info "Waiting for worker pods to appear..."
  local workers=""
  for attempt in $(seq 1 60); do
    workers="$(get_worker_pods)"
    local count
    count="$(echo "$workers" | grep -c . || true)"
    if [[ "$count" -ge 2 ]]; then
      break
    fi
    sleep 2
  done

  if [[ -z "$workers" ]]; then
    fail "Worker pods did not appear"
    k get pods -n "$NAMESPACE" || true
    return 1
  fi

  # Wait for each worker to be Running
  local i=0
  while IFS= read -r pod; do
    local node
    info "Waiting for $pod..."
    wait_for_running "$pod" 120
    node="$(get_pod_node "$pod")"
    ok "$pod is Running on $node"
    record "worker_${i}_pod=$pod"
    record "worker_${i}_node=$node"
    i=$((i + 1))
  done <<< "$workers"

  # Find launcher
  local launcher
  launcher="$(k get pods -n "$NAMESPACE" -l training.kubeflow.org/job-role=launcher \
    -o jsonpath='{.items[0].metadata.name}' || true)"
  info "Launcher: ${launcher:-not found}"
  record "launcher=$launcher"

  # Wait for application processes to start
  info "Waiting for application processes to start on workers..."
  sleep "$SLEEP_BEFORE_MIGRATE"

  # Show process trees
  while IFS= read -r pod; do
    info "Process tree on $pod:"
    kexec_worker "$pod" ps auxf 2>/dev/null || kexec_worker "$pod" ps aux 2>/dev/null || true
    echo ""
  done <<< "$workers"

  ok "Deploy complete: $(echo "$workers" | wc -l | tr -d ' ') workers running"
}

# ─── Module: service ─────────────────────────────────────────────────────────
module_service() {
  section "Module: service"

  if [[ "$MIGRATE_MODE" == "direct" ]]; then
    info "Mode is 'direct' -- skipping service port-forward"
    return 0
  fi

  # Check if the distributed migration service pod exists
  local svc_pod
  svc_pod="$(k get pods -n monitor -l name=distributed-migrate-service \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"

  if [[ -z "$svc_pod" ]]; then
    # Fall back to the regular migration service
    svc_pod="$(k get pods -n monitor -l name=python-migrate-service \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  fi

  if [[ -z "$svc_pod" ]]; then
    warn "No migration service pod found in monitor namespace."
    warn "You can still use --mode direct to call the Python module directly."
    warn "Continuing anyway in case you want to bring the service up manually."
    return 0
  fi

  # Kill any existing port-forward on this port
  lsof -ti ":${SERVICE_PORT}" 2>/dev/null | xargs kill -9 2>/dev/null || true
  sleep 1

  info "Port-forwarding $svc_pod -> localhost:${SERVICE_PORT}"
  kubectl port-forward -n monitor "$svc_pod" "${SERVICE_PORT}:8000" \
    >"${OUT_DIR}/port_forward.log" 2>&1 &
  PF_PID=$!
  sleep 2

  # Health check
  if curl -sf "http://localhost:${SERVICE_PORT}/health" >/dev/null 2>&1; then
    ok "Migration service is reachable at localhost:${SERVICE_PORT}"
  else
    warn "Health check failed (service may not have /health endpoint yet)"
  fi
}

# ─── Module: migrate ─────────────────────────────────────────────────────────
module_migrate() {
  section "Module: migrate (mode=$MIGRATE_MODE)"

  # Discover current workers and their nodes
  local workers
  workers="$(get_worker_pods)"
  if [[ -z "$workers" ]]; then
    fail "No worker pods found. Run the deploy module first."
    return 1
  fi

  local -a worker_arr=()
  local -a source_nodes=()
  while IFS= read -r pod; do
    worker_arr+=("$pod")
    source_nodes+=("$(get_pod_node "$pod")")
  done <<< "$workers"

  info "Workers to migrate:"
  for i in "${!worker_arr[@]}"; do
    info "  rank $i: ${worker_arr[$i]} on ${source_nodes[$i]}"
  done

  # Determine target nodes
  local -a target_arr=()
  if [[ -n "$TARGET_NODES" ]]; then
    IFS=',' read -ra target_arr <<< "$TARGET_NODES"
  else
    # Auto-swap: get all worker nodes and assign each worker to a different node
    info "Auto-detecting target nodes (swapping workers to different nodes)..."
    local all_nodes
    all_nodes="$(kubectl get nodes --no-headers | grep -v control-plane | awk '{print $1}' | sort)"

    for i in "${!worker_arr[@]}"; do
      local src="${source_nodes[$i]}"
      local picked=""
      while IFS= read -r node; do
        if [[ "$node" != "$src" ]]; then
          picked="$node"
          break
        fi
      done <<< "$all_nodes"
      # If we couldn't find a different node, use same node (same-node migration)
      target_arr+=("${picked:-$src}")
    done
  fi

  if [[ ${#target_arr[@]} -lt ${#worker_arr[@]} ]]; then
    fail "Need ${#worker_arr[@]} target nodes but only got ${#target_arr[@]}"
    return 1
  fi

  info "Migration plan:"
  for i in "${!worker_arr[@]}"; do
    info "  rank $i: ${source_nodes[$i]} -> ${target_arr[$i]}"
  done
  record "migrate_mode=$MIGRATE_MODE"

  local targets_csv
  targets_csv="$(IFS=,; echo "${target_arr[*]}")"
  record "target_nodes=$targets_csv"

  local migrate_start
  migrate_start="$(date +%s)"

  if [[ "$MIGRATE_MODE" == "http" ]]; then
    _migrate_via_http "$targets_csv"
  else
    _migrate_via_direct "$targets_csv"
  fi

  local migrate_end
  migrate_end="$(date +%s)"
  local elapsed=$(( migrate_end - migrate_start ))
  record "migration_time_s=$elapsed"
  ok "Migration completed in ${elapsed}s"
}

_migrate_via_http() {
  local targets_csv="$1"

  # Build JSON target_nodes array
  local json_targets="["
  local first=true
  IFS=',' read -ra t_arr <<< "$targets_csv"
  for t in "${t_arr[@]}"; do
    if [[ "$first" == "true" ]]; then
      first=false
    else
      json_targets+=","
    fi
    json_targets+="\"$t\""
  done
  json_targets+="]"

  local payload
  payload=$(cat <<EOF
{
  "job_name": "$JOB_NAME",
  "namespace": "$NAMESPACE",
  "target_nodes": $json_targets,
  "delete_originals": true
}
EOF
  )

  info "Sending POST /distributed-migrate"
  info "Payload: $payload"

  local http_code body
  body="$(curl -sf -w '\n%{http_code}' \
    -X POST "http://localhost:${SERVICE_PORT}/distributed-migrate" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    --max-time 300 2>"${OUT_DIR}/curl_stderr.log" || true)"

  http_code="$(echo "$body" | tail -1)"
  body="$(echo "$body" | sed '$d')"

  echo "$body" | python3 -m json.tool > "${OUT_DIR}/migrate_response.json" 2>/dev/null || echo "$body" > "${OUT_DIR}/migrate_response.json"
  record "http_code=$http_code"

  if [[ "$http_code" == "200" ]]; then
    ok "HTTP 200 - migration request succeeded"
    info "Response saved to ${OUT_DIR}/migrate_response.json"
  else
    fail "HTTP $http_code - migration request failed"
    cat "${OUT_DIR}/migrate_response.json"
    return 1
  fi
}

_migrate_via_direct() {
  local targets_csv="$1"

  # Build a small Python script that calls distributed_migrate() directly
  local py_targets="["
  local first=true
  IFS=',' read -ra t_arr <<< "$targets_csv"
  for t in "${t_arr[@]}"; do
    if [[ "$first" == "true" ]]; then first=false; else py_targets+=", "; fi
    py_targets+="'$t'"
  done
  py_targets+="]"

  local pyscript
  pyscript=$(cat <<PYEOF
import sys, json, logging
logging.basicConfig(level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s')
sys.path.insert(0, '$(cd "$(dirname "$0")/../../distributed-migrator" && pwd)')
from distributed_migration import distributed_migrate

result = distributed_migrate(
    job_name='$JOB_NAME',
    namespace='$NAMESPACE',
    target_nodes=$py_targets,
    delete_originals=True,
)

out = {
    'success': result.success,
    'elapsed_s': result.elapsed_s,
    'workers': [
        {'source_pod': w.pod_name, 'source_node': w.node_name,
         'target_pod': w.target_pod_name, 'target_node': w.target_node}
        for w in result.workers
    ],
    'errors': result.errors,
    'steps': result.steps_completed,
}
print(json.dumps(out, indent=2))
sys.exit(0 if result.success else 1)
PYEOF
  )

  info "Running distributed_migrate() directly via Python..."
  set +e
  python3 -c "$pyscript" \
    >"${OUT_DIR}/direct_stdout.log" \
    2>"${OUT_DIR}/direct_stderr.log"
  local rc=$?
  set -e

  cp "${OUT_DIR}/direct_stdout.log" "${OUT_DIR}/migrate_response.json" 2>/dev/null || true
  record "direct_rc=$rc"

  if [[ $rc -eq 0 ]]; then
    ok "Direct Python call succeeded"
    cat "${OUT_DIR}/migrate_response.json"
  else
    fail "Direct Python call failed (rc=$rc)"
    echo "--- stdout ---"
    cat "${OUT_DIR}/direct_stdout.log" 2>/dev/null || true
    echo "--- stderr (last 40 lines) ---"
    tail -40 "${OUT_DIR}/direct_stderr.log" 2>/dev/null || true
    return 1
  fi
}

# ─── Module: verify ──────────────────────────────────────────────────────────
module_verify() {
  section "Module: verify"

  local pass_count=0
  local fail_count=0
  local total=0

  check() {
    total=$((total + 1))
    local desc="$1" result="$2"
    if [[ "$result" == "pass" ]]; then
      ok "  [PASS] $desc"
      pass_count=$((pass_count + 1))
    else
      fail " [FAIL] $desc"
      fail_count=$((fail_count + 1))
    fi
  }

  # 1. Check that migration response file exists and has success
  if [[ -f "${OUT_DIR}/migrate_response.json" ]]; then
    local status
    status="$(python3 -c "
import json, sys
try:
    d = json.load(open('${OUT_DIR}/migrate_response.json'))
    s = d.get('status', d.get('success', False))
    print('pass' if s in (True, 'success') else 'fail')
except: print('fail')
" 2>/dev/null || echo "fail")"
    check "Migration response indicates success" "$status"
  else
    check "Migration response file exists" "fail"
  fi

  # 2. Check for migrated pods (labelled migrated=true)
  info "Looking for migrated pods..."
  local migrated_pods
  migrated_pods="$(k get pods -n "$NAMESPACE" -l migrated=true \
    -o jsonpath='{range .items[*]}{.metadata.name} {.spec.nodeName} {.status.phase}{"\n"}{end}' || true)"

  if [[ -n "$migrated_pods" ]]; then
    check "Migrated pods exist" "pass"
    echo "$migrated_pods" | while IFS= read -r line; do
      info "  $line"
    done
  else
    check "Migrated pods exist" "fail"
    info "All pods in namespace:"
    k get pods -n "$NAMESPACE" -o wide || true
  fi

  # 3. Check each migrated pod is Running
  if [[ -n "$migrated_pods" ]]; then
    echo "$migrated_pods" | while IFS=' ' read -r pname pnode pphase; do
      if [[ "$pphase" == "Running" ]]; then
        check "Pod $pname is Running on $pnode" "pass"
      else
        check "Pod $pname is Running (got: $pphase)" "fail"
      fi
    done
  fi

  # 4. Check that original worker pods are gone (if delete_originals was true)
  local original_workers
  original_workers="$(k get pods -n "$NAMESPACE" \
    -l "training.kubeflow.org/job-role=worker" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' || true)"

  if [[ -z "$original_workers" ]]; then
    check "Original worker pods deleted" "pass"
  else
    warn "Original worker pods still present (may be expected if delete_originals=false):"
    echo "$original_workers" | while IFS= read -r p; do info "  $p"; done
    check "Original worker pods deleted" "fail"
  fi

  # 5. Monitor restored processes for liveness
  if [[ -n "$migrated_pods" ]]; then
    info "Monitoring restored processes for ${MONITOR_DURATION}s..."
    sleep "$MONITOR_DURATION"

    echo "$migrated_pods" | while IFS=' ' read -r pname pnode pphase; do
      local current_phase
      current_phase="$(k get pod "$pname" -n "$NAMESPACE" -o jsonpath='{.status.phase}' || echo "Unknown")"
      if [[ "$current_phase" == "Running" ]]; then
        check "Pod $pname still Running after ${MONITOR_DURATION}s" "pass"
      else
        check "Pod $pname still Running after ${MONITOR_DURATION}s (got: $current_phase)" "fail"
      fi
    done

    # Collect logs from migrated pods
    echo "$migrated_pods" | while IFS=' ' read -r pname pnode pphase; do
      info "Collecting logs from $pname..."
      k logs "$pname" -n "$NAMESPACE" > "${OUT_DIR}/logs_${pname}.log" 2>/dev/null || true
    done
  fi

  # Summary
  section "Verify Summary"
  info "Total checks: $total"
  ok   "Passed: $pass_count"
  if [[ $fail_count -gt 0 ]]; then
    fail "Failed: $fail_count"
  else
    info "Failed: 0"
  fi
  record "verify_pass=$pass_count"
  record "verify_fail=$fail_count"

  if [[ $fail_count -gt 0 ]]; then
    return 1
  fi
}

# ─── Module: cleanup ─────────────────────────────────────────────────────────
module_cleanup() {
  section "Module: cleanup"

  # Stop port-forward
  if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" 2>/dev/null; then
    info "Stopping port-forward (PID $PF_PID)..."
    kill "$PF_PID" 2>/dev/null || true
    PF_PID=""
  fi

  # Delete migrated pods
  info "Deleting migrated pods..."
  k delete pods -n "$NAMESPACE" -l migrated=true --grace-period=0 --force 2>/dev/null || true

  # Delete MPIJob
  info "Deleting MPIJob $JOB_NAME..."
  k delete mpijob "$JOB_NAME" -n "$NAMESPACE" 2>/dev/null || true

  # Delete remaining pods from the job
  info "Deleting remaining job pods..."
  k delete pods -n "$NAMESPACE" -l "training.kubeflow.org/job-name=$JOB_NAME" \
    --grace-period=0 --force 2>/dev/null || true

  # Wait for pods to be gone
  info "Waiting for pods to terminate..."
  local timeout=30
  local start
  start="$(date +%s)"
  while true; do
    local remaining
    remaining="$(k get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "$remaining" -eq 0 ]]; then break; fi
    if (( $(date +%s) - start > timeout )); then
      warn "Some pods still present after ${timeout}s"
      k get pods -n "$NAMESPACE" 2>/dev/null || true
      break
    fi
    sleep 2
  done

  ok "Cleanup complete"
}

# ─── Main ────────────────────────────────────────────────────────────────────
section "Distributed Migration Test"
info "Timestamp:  $TS"
info "Output dir: $OUT_DIR"
info "Modules:    ${MODULES[*]}"
info "Mode:       $MIGRATE_MODE"
info "Job:        $JOB_NAME"
info "Namespace:  $NAMESPACE"
if [[ -n "$TARGET_NODES" ]]; then
  info "Targets:    $TARGET_NODES"
else
  info "Targets:    auto-swap"
fi
echo ""

record "timestamp=$TS"
record "modules=${MODULES[*]}"
record "namespace=$NAMESPACE"

TEST_START="$(date +%s)"
EXIT_CODE=0

for mod in "${MODULES[@]}"; do
  case "$mod" in
    deploy)   module_deploy  || EXIT_CODE=1 ;;
    service)  module_service || EXIT_CODE=1 ;;
    migrate)  module_migrate || EXIT_CODE=1 ;;
    verify)   module_verify  || EXIT_CODE=1 ;;
    cleanup)  module_cleanup || true ;;
    *)
      fail "Unknown module: $mod"
      EXIT_CODE=1
      ;;
  esac

  # Stop early on failure (except cleanup which always runs)
  if [[ $EXIT_CODE -ne 0 && "$mod" != "cleanup" ]]; then
    fail "Module '$mod' failed. Stopping."
    # Still run cleanup if it was requested
    if [[ " ${MODULES[*]} " == *" cleanup "* ]]; then
      module_cleanup || true
    fi
    break
  fi
done

TEST_END="$(date +%s)"
TOTAL_TIME=$(( TEST_END - TEST_START ))
record "total_time_s=$TOTAL_TIME"

section "Done"
info "Total time: ${TOTAL_TIME}s"
info "Logs:       $OUT_DIR"

if [[ $EXIT_CODE -eq 0 ]]; then
  ok "ALL MODULES PASSED"
else
  fail "SOME MODULES FAILED (see above)"
fi

exit $EXIT_CODE
