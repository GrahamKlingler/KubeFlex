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
DELETE_STORAGE=false
DELETE_CLUSTER=false
DELETE_DB=false
DELETE_MIGRATE=false
DELETE_CONTROLLER=false
DELETE_ALL=false

for arg in "$@"; do
    case $arg in
        --all)
            DELETE_ALL=true
            DELETE_STORAGE=true
            DELETE_DB=true
            DELETE_MIGRATE=true
            DELETE_CONTROLLER=true
            shift
            ;;
        --cluster)
            DELETE_CLUSTER=true
            shift
            ;;
        --db)
            DELETE_DB=true
            shift
            ;;
        --migrate)
            DELETE_MIGRATE=true
            shift
            ;;
        --controller)
            DELETE_CONTROLLER=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--all] [--cluster] [--db] [--migrate] [--controller] [--help]"
            echo "  --all        Delete all resources including storage and database"
            echo "  --cluster    Delete the entire kind cluster"
            echo "  --db         Delete database resources"
            echo "  --migrate    Delete migration service resources"
            echo "  --controller Delete controller resources"
            echo "  --help       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --all                    # Delete everything"
            echo "  $0 --cluster --db           # Delete cluster and database only"
            echo "  $0 --migrate --controller   # Delete migration and controller only"
            exit 0
            ;;
    esac
done

# If no flags specified, default to all
if [ "$DELETE_STORAGE" = false ] && [ "$DELETE_DB" = false ] && [ "$DELETE_MIGRATE" = false ] && [ "$DELETE_CONTROLLER" = false ] && [ "$DELETE_CLUSTER" = false ] && [ "$DELETE_ALL" = false ]; then
    DELETE_ALL=true
    DELETE_STORAGE=true
    DELETE_DB=true
    DELETE_MIGRATE=true
    DELETE_CONTROLLER=true
    log_info "No specific components specified, deleting all components"
fi

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

# Delete specific components based on flags
if [ "$DELETE_ALL" = true ]; then
    log_info "Deleting all Flex-Nautilus resources..."
    kubectl delete -k manifests/ 2>/dev/null || log_warning "Some resources may not exist"
else
    # Delete specific components
    if [ "$DELETE_MIGRATE" = true ]; then
        log_info "Deleting migration service..."
        kubectl delete pod -n monitor -l name=python-migrate-service 2>/dev/null || log_warning "Migration service may not exist"
        kubectl delete pod -n monitor -l name=migrator-kind-worker2 2>/dev/null || log_warning "Extractor pods may not exist"
        kubectl delete pod -n monitor -l name=migrator-kind-worker 2>/dev/null || log_warning "Extractor pods may not exist"
    fi
    
    if [ "$DELETE_CONTROLLER" = true ]; then
        log_info "Deleting controller..."
        kubectl delete -f manifests/controller.yml 2>/dev/null || log_warning "Controller may not exist"
    fi
    
    if [ "$DELETE_DB" = true ]; then
        log_info "Deleting database resources..."
        kubectl delete -f manifests/storage.yml 2>/dev/null || log_warning "Storage resources may not exist"
        
        # Additional database-specific cleanup
        log_info "Performing additional database cleanup..."
        kubectl delete job db-upload -n monitor 2>/dev/null || log_warning "DB upload job may not exist"
        kubectl delete pvc -l app=postgres -n monitor 2>/dev/null || log_warning "PostgreSQL PVCs may not exist"
    fi
fi

# Delete all pods in all namespaces that begin with "test"
log_info "Deleting all pods in all namespaces that begin with 'test'..."

# Get all pods in foo namespace and delete those starting with "test"
kubectl get pods -n foo --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^test" | while read pod_name; do
    if [ -n "$pod_name" ]; then
        log_info "Deleting pod: $pod_name in namespace foo"
        kubectl delete pod "$pod_name" -n foo 2>/dev/null || log_warning "Failed to delete pod $pod_name in foo namespace"
    fi
done

# Get all pods in monitor namespace and delete those starting with "test"
kubectl get pods -n monitor --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^test" | while read pod_name; do
    if [ -n "$pod_name" ]; then
        log_info "Deleting pod: $pod_name in namespace monitor"
        kubectl delete pod "$pod_name" -n monitor 2>/dev/null || log_warning "Failed to delete pod $pod_name in monitor namespace"
    fi
done

# Remove node labels (only if cluster is being deleted)
if [ "$DELETE_CLUSTER" = true ]; then
    log_info "Removing node labels..."
    kubectl label node kind-worker2 REGION- 2>/dev/null || log_warning "Node kind-worker2 not labeled"
    kubectl label node kind-worker REGION- 2>/dev/null || log_warning "Node kind-worker not labeled"
fi

# Delete namespaces (only if all components are being deleted)
if [ "$DELETE_ALL" = true ]; then
    log_info "Cleaning up namespaces..."
    kubectl delete namespace monitor 2>/dev/null || log_warning "Namespace monitor not found"
    kubectl delete namespace foo 2>/dev/null || log_warning "Namespace foo not found"
fi

# Delete kind cluster if --cluster flag is set
if [ "$DELETE_CLUSTER" = true ]; then
    log_info "Deleting kind cluster..."
    kind delete cluster
    log_success "Kind cluster deleted"
fi

log_info "=========================================="
log_success "CLEANUP COMPLETED"
log_info "=========================================="
