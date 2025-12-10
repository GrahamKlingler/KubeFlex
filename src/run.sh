#!/bin/bash

# KubeFlex Deployment Script
# This script deploys the updated KubeFlex system with Docker checkpoint functionality

set -e

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

# Configuration
NAMESPACE="monitor"
MANIFESTS_DIR="manifests"
# Everything is always deployed except DB and cluster (which require flags)
CREATE_CLUSTER=false
CREATE_DB=false
CREATE_MIGRATE=true
CREATE_CONTROLLER=true
CREATE_METRICS=true
CREATE_ALL=true
SCHEDULER_TIME=""  # Unix timestamp, will be set from --time flag or default to current time
SCHEDULING_POLICY="3"  # Scheduling policy: 1, 2, or 3 (default: 3)

# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --include-db)
            CREATE_DB=true
            shift
            ;;
        --include-cluster)
            CREATE_CLUSTER=true
            shift
            ;;
        --time)
            SCHEDULER_TIME="$2"
            shift
            shift
            ;;
        --policy)
            SCHEDULING_POLICY="$2"
            shift
            shift
            ;;
        --help)
            echo "Usage: $0 [--include-db] [--include-cluster] [--time TIMESTAMP] [--policy POLICY] [--help]"
            echo "  --include-db       Deploy the database and storage components (includes metadata service as sidecar)"
            echo "                     Without this flag, everything else is deployed but database is skipped"
            echo "  --include-cluster  Create the KIND cluster (if it doesn't exist)"
            echo "                     Without this flag, the script assumes a cluster already exists"
            echo "  --time             Set scheduler time (Unix timestamp, default: beginning of interval)"
            echo "                     Valid range: 1577836800 (2020-01-01) to 1672527600 (2022-12-31)"
            echo "  --policy           Set scheduling policy (1, 2, or 3, default: 3)"
            echo "                     1 = Initial placement only (assign to lowest region at runtime)"
            echo "                     2 = Hourly migration (migrate all pods to minimum region every hour)"
            echo "                     3 = Forecast-based (compare forecasts for all regions over EXPECTED_DURATION)"
            echo "  --help             Show this help message"
            echo ""
            echo "By default, the script deploys:"
            echo "  - Metrics-server"
            echo "  - Migration service and migrators"
            echo "  - Controller (scheduler)"
            echo "  - Test pod"
            echo ""
            echo "Examples:"
            echo "  $0                           # Deploy everything except database and cluster"
            echo "  $0 --include-db              # Deploy everything including database"
            echo "  $0 --include-cluster         # Deploy everything including cluster creation"
            echo "  $0 --include-db --include-cluster  # Deploy everything including database and cluster"
            echo "  $0 --include-db --time 1609459200  # Deploy with specific scheduler time"
            echo "  $0 --include-db --policy 2  # Deploy with hourly migration policy"
            echo "  $0 --include-db --time 1609459200 --policy 3  # Deploy with scheduler time and forecast-based policy"
            exit 0
            ;;
    esac
done

log_info "=========================================="
log_info "KubeFlex DEPLOYMENT SCRIPT"
log_info "=========================================="

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    log_error "kubectl is not installed or not in PATH"
    log_info "Please install kubectl first:"
    log_info "  - macOS: brew install kubectl"
    log_info "  - Linux: curl -LO https://dl.k8s.io/release/\$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    log_info "  - Windows: choco install kubernetes-cli"
    exit 1
fi

# Check if we're connected to a cluster or if we should create one
if [ "$CREATE_CLUSTER" = true ]; then
    log_info "Creating/configuring kind cluster..."
    
    # Check if kind is available
    if ! command -v kind &> /dev/null; then
        log_error "kind is not installed. Please install kind first:"
        log_info "  - macOS: brew install kind"
        log_info "  - Linux: curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64"
        log_info "  - Windows: choco install kind"
        exit 1
    fi
    
    # Extract cluster name from cluster.yml
    CLUSTER_NAME=$(grep -E "^name:" manifests/cluster.yml | awk '{print $2}' | tr -d '"' || echo "kind")
    log_info "Detected cluster name: ${CLUSTER_NAME}"
    
    # Check if the kind cluster exists
    if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
        log_warning "Kind cluster '${CLUSTER_NAME}' already exists"
        log_info "Deleting existing cluster to create a fresh one..."
        if kind delete cluster --name ${CLUSTER_NAME}; then
            log_success "Successfully deleted existing cluster"
        else
            log_error "Failed to delete existing cluster"
            exit 1
        fi
    fi
    
    # Create new kind cluster
    log_info "Creating kind cluster with configuration..."
    if kind create cluster --config manifests/cluster.yml; then
        log_success "Kind cluster created successfully"
    else
        log_error "Failed to create kind cluster"
        exit 1
    fi
    
    # Set up kubeconfig (use the cluster name from config)
    log_info "Setting up kubeconfig..."
    kind get kubeconfig --name ${CLUSTER_NAME} > kubeconfig
    chmod 600 kubeconfig
    export KUBECONFIG=./kubeconfig
    
    if kubectl cluster-info &> /dev/null; then
        log_success "Successfully connected to new cluster"
    else
        log_error "Failed to connect to new cluster"
        exit 1
    fi
fi

log_info "Connected to cluster: $(kubectl config current-context)"

# Deploy metrics-server if requested (should be done early for cluster metrics)
if [ "$CREATE_METRICS" = true ]; then
    log_info "Applying metrics-server.yaml..."
    if kubectl apply -f $MANIFESTS_DIR/metrics-server.yaml; then
        log_success "Successfully applied metrics-server.yaml"
    else
        log_warning "Failed to apply metrics-server.yaml (may already exist or not needed)"
    fi
fi

# Label nodes for region-based scheduling (always done if nodes exist, not just when creating cluster)
log_info "Labeling nodes for region-based scheduling..."
WORKER_NODES=$(kubectl get nodes --no-headers | grep -v control-plane | awk '{print $1}')
if [ -n "$WORKER_NODES" ]; then
    WORKER_COUNT=0
    for NODE_NAME in $WORKER_NODES; do
        WORKER_COUNT=$((WORKER_COUNT + 1))
        if [ $WORKER_COUNT -eq 1 ]; then
            kubectl label node ${NODE_NAME} REGION=NE --overwrite
            log_success "Labeled ${NODE_NAME} as REGION=NE"
        elif [ $WORKER_COUNT -eq 2 ]; then
            kubectl label node ${NODE_NAME} REGION=TEN --overwrite
            log_success "Labeled ${NODE_NAME} as REGION=TEN"
        elif [ $WORKER_COUNT -eq 3 ]; then
            kubectl label node ${NODE_NAME} REGION=CENT --overwrite
            log_success "Labeled ${NODE_NAME} as REGION=CENT"
        else
            log_warning "More than 3 worker nodes found, skipping ${NODE_NAME} (only first 3 are labeled)"
        fi
    done
    
    if [ $WORKER_COUNT -lt 3 ]; then
        log_warning "Only $WORKER_COUNT worker node(s) found, but 3 are expected for full region coverage"
    fi
else
    log_warning "No worker nodes found to label"
fi

log_info "Ensuring namespace test-namespace exists..."
if ! kubectl get namespace test-namespace &> /dev/null; then
    kubectl create namespace test-namespace
    log_success "Created namespace test-namespace"
else
    log_info "Namespace test-namespace already exists"
fi


log_info "Ensuring namespace $NAMESPACE exists..."
if ! kubectl get namespace $NAMESPACE &> /dev/null; then
    kubectl create namespace $NAMESPACE
    log_success "Created namespace $NAMESPACE"
else
    log_info "Namespace $NAMESPACE already exists"
fi

# Set scheduler time if not provided
if [ -z "$SCHEDULER_TIME" ]; then
    # Default to beginning of interval (2020-01-01 00:00:00)
    SCHEDULER_TIME=1577836800
    log_info "No scheduler time provided, using default (beginning of interval): $SCHEDULER_TIME"
else
    # Validate provided timestamp
    if ! [[ "$SCHEDULER_TIME" =~ ^[0-9]+$ ]]; then
        log_error "Invalid scheduler time: $SCHEDULER_TIME (must be a Unix timestamp)"
        exit 1
    fi
    
    if [ "$SCHEDULER_TIME" -lt 1577836800 ] || [ "$SCHEDULER_TIME" -gt 1672527600 ]; then
        log_warning "Scheduler time $SCHEDULER_TIME is outside data range (1577836800-1672527600)"
        log_warning "This may cause issues with carbon data queries"
    fi
    
    log_info "Using provided scheduler time: $SCHEDULER_TIME"
fi

# Validate scheduling policy
if ! [[ "$SCHEDULING_POLICY" =~ ^[123]$ ]]; then
    log_error "Invalid scheduling policy: $SCHEDULING_POLICY (must be 1, 2, or 3)"
    exit 1
fi

log_info "Using scheduling policy: $SCHEDULING_POLICY"
case "$SCHEDULING_POLICY" in
    1)
        log_info "  Policy 1: Initial placement only (assign to lowest region at runtime)"
        ;;
    2)
        log_info "  Policy 2: Hourly migration (migrate all pods to minimum region every hour)"
        ;;
    3)
        log_info "  Policy 3: Forecast-based (compare forecasts for all regions over EXPECTED_DURATION)"
        ;;
esac

# Create or update scheduler-config ConfigMap in both namespaces
log_info "Creating/updating scheduler-config ConfigMap..."
SCHEDULER_DATETIME=$(date -r "$SCHEDULER_TIME" -u +"%Y-%m-%d %H:%M:%S" 2>/dev/null || date -d "@$SCHEDULER_TIME" -u +"%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "unknown")
log_info "Scheduler time: $SCHEDULER_TIME ($SCHEDULER_DATETIME UTC)"

# Create ConfigMap in monitor namespace (for controller)
kubectl create configmap scheduler-config \
    --from-literal=scheduler-time="$SCHEDULER_TIME" \
    --from-literal=scheduling-policy="$SCHEDULING_POLICY" \
    -n $NAMESPACE \
    --dry-run=client -o yaml | kubectl apply -f - > /dev/null

if kubectl get configmap scheduler-config -n $NAMESPACE &> /dev/null; then
    log_success "Scheduler-config ConfigMap created/updated in $NAMESPACE namespace"
else
    log_error "Failed to create scheduler-config ConfigMap in $NAMESPACE namespace"
    exit 1
fi

# Create ConfigMap in test-namespace namespace (for testpod)
kubectl create configmap scheduler-config \
    --from-literal=scheduler-time="$SCHEDULER_TIME" \
    --from-literal=scheduling-policy="$SCHEDULING_POLICY" \
    -n test-namespace \
    --dry-run=client -o yaml | kubectl apply -f - > /dev/null

if kubectl get configmap scheduler-config -n test-namespace &> /dev/null; then
    log_success "Scheduler-config ConfigMap created/updated in test-namespace namespace"
else
    log_error "Failed to create scheduler-config ConfigMap in test-namespace namespace"
    exit 1
fi

# Deploy the manifests based on flags
log_info "Deploying KubeFlex manifests..."

# Always deploy roles first (needed for RBAC)
log_info "Applying roles.yml..."
if kubectl apply -f $MANIFESTS_DIR/roles.yml; then
    log_success "Successfully applied roles.yml"
else
    log_error "Failed to apply roles.yml"
    exit 1
fi

# Apply scheduler-config (needed for controller and testpod, but we'll deploy those last)
log_info "Applying scheduler-config.yml..."
if kubectl apply -f $MANIFESTS_DIR/scheduler-config.yml; then
    # Update the ConfigMap with the actual scheduler time and policy
    kubectl create configmap scheduler-config \
        --from-literal=scheduler-time="$SCHEDULER_TIME" \
        --from-literal=scheduling-policy="$SCHEDULING_POLICY" \
        -n $NAMESPACE \
        --dry-run=client -o yaml | kubectl apply -f - > /dev/null
    kubectl create configmap scheduler-config \
        --from-literal=scheduler-time="$SCHEDULER_TIME" \
        --from-literal=scheduling-policy="$SCHEDULING_POLICY" \
        -n test-namespace \
        --dry-run=client -o yaml | kubectl apply -f - > /dev/null
    log_success "Successfully applied scheduler-config.yml with time: $SCHEDULER_TIME, policy: $SCHEDULING_POLICY"
else
    log_error "Failed to apply scheduler-config.yml"
    exit 1
fi

# STEP 1: Deploy database and upload data FIRST (before migrator)
if [ "$CREATE_DB" = true ]; then
    log_info "Applying storage.yml (database + upload job)..."
    if kubectl apply -f $MANIFESTS_DIR/storage.yml; then
        log_success "Successfully applied storage.yml"
    else
        log_error "Failed to apply storage.yml"
        exit 1
    fi
fi


# STEP 3: Deploy migration service and migrator pods (after db + upload)
if [ "$CREATE_MIGRATE" = true ]; then
    log_info "Applying python-migrate.yml..."
    if kubectl apply -f $MANIFESTS_DIR/python-migrate.yml; then
        log_success "Successfully applied python-migrate.yml"
    else
        log_error "Failed to apply python-migrate.yml"
        exit 1
    fi
    
    # Create migrator pods for KIND worker nodes
    log_info "Creating migrator pods for KIND worker nodes..."
    
    # Get actual worker node names from the cluster
    WORKER_NODES=$(kubectl get nodes -o jsonpath='{.items[?(@.metadata.labels.node-role\.kubernetes\.io/worker!="")].metadata.name}' 2>/dev/null || kubectl get nodes --no-headers | grep -v control-plane | awk '{print $1}')
    
    if [ -z "$WORKER_NODES" ]; then
        # Fallback: try to detect worker nodes by name pattern
        WORKER_NODES=$(kubectl get nodes --no-headers | grep -v control-plane | awk '{print $1}')
    fi
    
    # If still empty, use default names based on cluster name from cluster.yml
    if [ -z "$WORKER_NODES" ]; then
        # Get cluster name from cluster.yml (already set earlier if CREATE_CLUSTER was true)
        if [ -z "$CLUSTER_NAME" ]; then
            CLUSTER_NAME=$(grep -E "^name:" manifests/cluster.yml | awk '{print $2}' | tr -d '"' || echo "kind")
        fi
        WORKER_NODES="${CLUSTER_NAME}-worker ${CLUSTER_NAME}-worker2"
        log_info "Using default worker node names: ${WORKER_NODES}"
    fi
    
    # Create migrator pod for each worker node
    for NODE_NAME in $WORKER_NODES; do
        log_info "Creating migrator pod for ${NODE_NAME}..."
        if sed "s/{NODE_NAME}/${NODE_NAME}/g" $MANIFESTS_DIR/migrator.yml | kubectl apply -f -; then
            log_success "Successfully created migrator pod for ${NODE_NAME}"
    else
            log_error "Failed to create migrator pod for ${NODE_NAME}"
        exit 1
    fi
    done
fi

sleep 3

# STEP 5: Deploy test pod - SECOND TO LAST
if [ "$CREATE_ALL" = true ]; then
log_info "Applying testpod.yml..."
if kubectl apply -f $MANIFESTS_DIR/testpod.yml; then
    log_success "Successfully applied testpod.yml"
else
    log_error "Failed to apply testpod.yml"
    exit 1
    fi
fi

sleep 3

# STEP 4: Deploy controller (scheduler) - LAST
if [ "$CREATE_CONTROLLER" = true ]; then
    log_info "Applying controller.yml..."
    if kubectl apply -f $MANIFESTS_DIR/controller.yml; then
        log_success "Successfully applied controller.yml"
    else
        log_error "Failed to apply controller.yml"
        exit 1
    fi
fi


# Wait for pods to be ready based on what was deployed
log_info "Waiting for deployed components to be ready..."

# Wait for database to be ready
if [ "$CREATE_DB" = true ]; then
    log_info "Waiting for database..."
    if kubectl wait --for=condition=Ready pod -l app=postgres -n $NAMESPACE --timeout=300s; then
        log_success "Database is ready"
    else
        log_error "Database failed to become ready"
        exit 1
    fi
    
    # Wait for db-upload job to complete (data must be uploaded before other services use it)
    log_info "Waiting for database upload job to complete..."
    if kubectl wait --for=condition=complete job/db-upload -n $NAMESPACE --timeout=600s 2>/dev/null; then
        log_success "Database upload job completed successfully"
    elif kubectl wait --for=condition=failed job/db-upload -n $NAMESPACE --timeout=10s 2>/dev/null; then
        log_warning "Database upload job failed, but continuing (data may already be uploaded)"
    else
        log_warning "Database upload job status unknown, continuing (may need to check manually)"
    fi
fi

# Wait for metadata container in database pod to be ready
if [ "$CREATE_DB" = true ]; then
    log_info "Waiting for metadata container in database pod..."
    # Check if metadata container is ready in the postgres pod
    DB_POD=$(kubectl get pods -n $NAMESPACE -l app=postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$DB_POD" ]; then
        if kubectl wait --for=condition=Ready pod $DB_POD -n $NAMESPACE --timeout=300s; then
            # Check if metadata container is running
            if kubectl get pod $DB_POD -n $NAMESPACE -o jsonpath='{.status.containerStatuses[?(@.name=="metadata-container")].ready}' | grep -q "true"; then
                log_success "Metadata container is ready"
            else
                log_warning "Metadata container may not be ready yet (check with: kubectl get pod $DB_POD -n $NAMESPACE)"
            fi
        else
            log_error "Database pod failed to become ready"
            exit 1
        fi
    else
        log_warning "Database pod not found, skipping metadata container check"
    fi
fi

# Wait for python-migrate-service
if [ "$CREATE_MIGRATE" = true ]; then
    log_info "Waiting for python-migrate-service..."
    if kubectl wait --for=condition=Ready pod -l name=python-migrate-service -n $NAMESPACE --timeout=300s; then
        log_success "python-migrate-service is ready"
    else
        log_error "python-migrate-service failed to become ready"
        exit 1
    fi
    
    # Wait for migrator pods to be ready
    log_info "Waiting for migrator pods..."
    # Use purpose label that's common to all migrator pods, or fallback to grep
    MIGRATOR_PODS=$(kubectl get pods -n $NAMESPACE -l purpose=containerd-access --no-headers -o custom-columns=":metadata.name" 2>/dev/null || kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep migrator | awk '{print $1}')
    
    if [ -z "$MIGRATOR_PODS" ]; then
        log_warning "No migrator pods found to wait for"
    else
        for POD_NAME in $MIGRATOR_PODS; do
            log_info "Waiting for ${POD_NAME}..."
            if kubectl wait --for=condition=Ready pod ${POD_NAME} -n $NAMESPACE --timeout=300s; then
                log_success "${POD_NAME} is ready"
    else
                log_warning "${POD_NAME} failed to become ready (may need more time or image pull)"
            fi
        done
    fi
fi

# Wait for controller
if [ "$CREATE_CONTROLLER" = true ]; then
    log_info "Waiting for controller..."
    if kubectl wait --for=condition=Ready pod -l name=controller -n $NAMESPACE --timeout=300s; then
        log_success "Controller is ready"
    else
        log_error "Controller failed to become ready"
        exit 1
    fi
fi

log_info "=========================================="
log_success "DEPLOYMENT COMPLETED SUCCESSFULLY"
log_info "=========================================="

# Show next steps based on what was deployed
log_info "Next steps:"

if [ "$CREATE_MIGRATE" = true ]; then
    log_info "1. Test migration service:"
    log_info "   kubectl port-forward -n $NAMESPACE svc/python-migrate-service 8000:8000"
    log_info "   curl http://localhost:8000/health"
    log_info ""
fi

if [ "$CREATE_CONTROLLER" = true ]; then
    log_info "2. Check controller logs:"
    log_info "   kubectl logs -n $NAMESPACE -l name=controller"
    log_info ""
fi

if [ "$CREATE_DB" = true ]; then
    log_info "3. Test metadata service (runs as sidecar in database pod):"
    log_info "   kubectl port-forward -n $NAMESPACE svc/metadata-service 8008:8008"
    log_info "   curl http://localhost:8008"
    log_info ""
fi

if [ "$CREATE_DB" = true ]; then
    log_info "4. Check database status:"
    log_info "   kubectl get pods -n $NAMESPACE -l app=postgres"
    log_info ""
fi

log_info "5. Monitor all pods:"
log_info "   kubectl get pods -n $NAMESPACE -w"
log_info ""
log_info "6. Scheduler configuration:"
log_info "   Scheduler time: $SCHEDULER_TIME ($SCHEDULER_DATETIME UTC)"
log_info "   Scheduling policy: $SCHEDULING_POLICY"
log_info "   ConfigMap: scheduler-config (in both monitor and test-namespace namespaces)"
log_info "   To update scheduler time and policy:"
log_info "     kubectl create configmap scheduler-config --from-literal=scheduler-time=<timestamp> --from-literal=scheduling-policy=<1|2|3> -n monitor --dry-run=client -o yaml | kubectl apply -f -"
log_info "     kubectl create configmap scheduler-config --from-literal=scheduler-time=<timestamp> --from-literal=scheduling-policy=<1|2|3> -n test-namespace --dry-run=client -o yaml | kubectl apply -f -"

log_success "KubeFlex deployment completed!"
