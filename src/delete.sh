#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse command line arguments
# Everything is always deleted except DB and cluster (which require flags)
DELETE_STORAGE=true
DELETE_CLUSTER=false
DELETE_DB=false
DELETE_MIGRATE=true
DELETE_CONTROLLER=true
DELETE_METRICS=true
DELETE_ALL=true

for arg in "$@"; do
    case $arg in
        --include-db)
            DELETE_DB=true
            shift
            ;;
        --include-cluster)
            DELETE_CLUSTER=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--include-db] [--include-cluster] [--help]"
            echo "  --include-db       Delete the database and storage components (includes metadata service sidecar)"
            echo "                    Without this flag, everything else is deleted but database is skipped"
            echo "  --include-cluster  Delete the KIND cluster"
            echo "                    Without this flag, the cluster is left intact"
            echo "  --help            Show this help message"
            echo ""
            echo "By default, the script deletes:"
            echo "  - Metrics-server"
            echo "  - Migration service and migrators"
            echo "  - Controller (scheduler)"
            echo "  - Test pods"
            echo "  - All namespaces and resources"
            echo ""
            echo "Examples:"
            echo "  $0                      # Delete everything except database and cluster"
            echo "  $0 --include-db         # Delete everything including database"
            echo "  $0 --include-cluster    # Delete everything including cluster"
            echo "  $0 --include-db --include-cluster  # Delete everything including database and cluster"
            exit 0
            ;;
    esac
done

log_info "=========================================="
log_info "FLEX-NAUTILUS CLEANUP SCRIPT"
log_info "=========================================="

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    log_error "kubectl is not installed or not in PATH"
    exit 1
fi

# Check if we're connected to a cluster
if ! kubectl cluster-info &> /dev/null; then
    log_error "Not connected to a Kubernetes cluster"
    exit 1
fi

log_info "Connected to cluster: $(kubectl config current-context)"

# Delete configmaps (ignore if not found)
log_info "Cleaning up configmaps..."
kubectl delete configmap pod-selector-config -n monitor 2>/dev/null || log_warning "ConfigMap pod-selector-config not found"
kubectl delete configmap scheduler-config -n monitor 2>/dev/null || log_warning "ConfigMap scheduler-config not found in monitor namespace"
kubectl delete configmap scheduler-config -n test-namespace 2>/dev/null || log_warning "ConfigMap scheduler-config not found in test-namespace namespace"

# Delete specific components based on flags
# Always delete everything except database (which requires --include-db)
log_info "Deleting Flex-Nautilus resources..."

# Delete migration service
log_info "Deleting migration service..."
kubectl delete pod -n monitor -l name=python-migrate-service 2>/dev/null || log_warning "Migration service may not exist"

# Delete all migrator pods across all nodes
log_info "Deleting all migrator pods..."
# Get all migrator pods (they have names like migrator-{node-name})
MIGRATOR_PODS=$(kubectl get pods -n monitor --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^migrator-" || true)
if [ -n "$MIGRATOR_PODS" ]; then
    for MIGRATOR_POD in $MIGRATOR_PODS; do
        log_info "Deleting migrator pod: $MIGRATOR_POD"
        kubectl delete pod "$MIGRATOR_POD" -n monitor 2>/dev/null || log_warning "Failed to delete migrator pod $MIGRATOR_POD"
    done
else
    log_info "No migrator pods found to delete"
fi

# Also try deleting by label selector (if migrator pods have a common label)
kubectl delete pod -n monitor -l purpose=containerd-access 2>/dev/null || log_warning "No migrator pods found with purpose=containerd-access label"

kubectl delete -f manifests/python-migrate.yml 2>/dev/null || log_warning "Migration service manifest may not exist"
kubectl delete -f manifests/migrator.yml 2>/dev/null || log_warning "Migrator manifest may not exist"

# Delete controller
        log_info "Deleting controller..."
        kubectl delete -f manifests/controller.yml 2>/dev/null || log_warning "Controller may not exist"

# Delete testpod
log_info "Deleting test pod..."
kubectl delete -f manifests/testpod.yml 2>/dev/null || log_warning "Test pod may not exist"

# Delete metrics-server
log_info "Deleting metrics-server..."
kubectl delete -f manifests/metrics-server.yaml 2>/dev/null || log_warning "Metrics-server may not exist"

# Delete roles
log_info "Deleting roles..."
kubectl delete -f manifests/roles.yml 2>/dev/null || log_warning "Roles may not exist"

# Delete scheduler-config
log_info "Deleting scheduler-config..."
kubectl delete -f manifests/scheduler-config.yml 2>/dev/null || log_warning "Scheduler-config may not exist"

# Delete database only if --include-db was provided
    if [ "$DELETE_DB" = true ]; then
        log_info "Deleting database resources..."
        kubectl delete -f manifests/storage.yml 2>/dev/null || log_warning "Storage resources may not exist"
        
        # Additional database-specific cleanup
        log_info "Performing additional database cleanup..."
        kubectl delete job db-upload -n monitor 2>/dev/null || log_warning "DB upload job may not exist"
        kubectl delete pvc -l app=postgres -n monitor 2>/dev/null || log_warning "PostgreSQL PVCs may not exist"
else
    log_info "Skipping database deletion (use --include-db to delete database)"
fi

# Delete all pods in all namespaces that begin with "test"
log_info "Deleting all pods in all namespaces that begin with 'test'..."

# Get all pods in test-namespace namespace and delete those starting with "test"
kubectl get pods -n test-namespace --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^test" | while read pod_name; do
    if [ -n "$pod_name" ]; then
        log_info "Deleting pod: $pod_name in namespace test-namespace"
        kubectl delete pod "$pod_name" -n test-namespace 2>/dev/null || log_warning "Failed to delete pod $pod_name in test-namespace namespace"
    fi
done

# Get all pods in monitor namespace and delete those starting with "test"
kubectl get pods -n monitor --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^test" | while read pod_name; do
    if [ -n "$pod_name" ]; then
        log_info "Deleting pod: $pod_name in namespace monitor"
        kubectl delete pod "$pod_name" -n monitor 2>/dev/null || log_warning "Failed to delete pod $pod_name in monitor namespace"
    fi
done

# Remove node labels (always done)
    log_info "Removing node labels..."
WORKER_NODES=$(kubectl get nodes --no-headers | grep -v control-plane | awk '{print $1}' 2>/dev/null)
if [ -n "$WORKER_NODES" ]; then
    for NODE_NAME in $WORKER_NODES; do
        kubectl label node ${NODE_NAME} REGION- 2>/dev/null || log_warning "Node ${NODE_NAME} not labeled"
    done
else
    log_warning "No worker nodes found to unlabel"
fi

# Delete kind cluster only if --include-cluster was provided
if [ "$DELETE_CLUSTER" = true ]; then
    log_info "Deleting kind cluster..."
    if command -v kind &> /dev/null; then
        kind delete cluster 2>/dev/null || log_warning "Kind cluster may not exist or already deleted"
        log_success "Kind cluster deletion attempted"
    else
        log_warning "kind command not found, skipping cluster deletion"
    fi
else
    log_info "Skipping cluster deletion (use --include-cluster to delete cluster)"
fi

log_info "=========================================="
log_success "CLEANUP COMPLETED"
log_info "=========================================="
