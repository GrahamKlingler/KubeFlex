#!/bin/bash

# Flex-Nautilus Deployment Script
# This script deploys the updated Flex-Nautilus system with Docker checkpoint functionality

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
CREATE_CLUSTER=false
CREATE_DB=false
CREATE_MIGRATE=true
CREATE_CONTROLLER=false
CREATE_ALL=false

# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --cluster)
            CREATE_CLUSTER=true
            shift
            ;;
        --db)
            CREATE_DB=true
            shift
            ;;
        --migrate)
            CREATE_MIGRATE=true
            shift
            ;;
        --controller)
            CREATE_CONTROLLER=true
            shift
            ;;
        --all)
            CREATE_ALL=true
            CREATE_CLUSTER=true
            CREATE_DB=true
            CREATE_MIGRATE=true
            CREATE_CONTROLLER=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--cluster] [--db] [--migrate] [--controller] [--all] [--help]"
            echo "  --cluster     Deploy/configure the kind cluster"
            echo "  --db          Deploy the database and storage components"
            echo "  --migrate     Deploy the migration service"
            echo "  --controller  Deploy the controller"
            echo "  --all         Deploy all components (equivalent to all flags)"
            echo "  --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --all                    # Deploy everything"
            echo "  $0 --cluster --db           # Deploy cluster and database only"
            echo "  $0 --migrate --controller   # Deploy migration and controller only"
            exit 0
            ;;
    esac
done

# If no flags specified, default to all
if [ "$CREATE_CLUSTER" = false ] && [ "$CREATE_DB" = false ] && [ "$CREATE_MIGRATE" = false ] && [ "$CREATE_CONTROLLER" = false ] && [ "$CREATE_ALL" = false ]; then
    CREATE_ALL=true
    CREATE_CLUSTER=true
    CREATE_DB=true
    CREATE_MIGRATE=true
    CREATE_CONTROLLER=true
    log_info "No specific components specified, deploying all components"
fi

log_info "=========================================="
log_info "FLEX-NAUTILUS DEPLOYMENT SCRIPT"
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
    
    # Check if the default kind cluster exists
    if kind get clusters | grep -q "^kind$"; then
        log_warning "Kind cluster 'kind' already exists"
        log_info "Deleting existing cluster to create a fresh one..."
        if kind delete cluster --name kind; then
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
    
    # Set up kubeconfig
    log_info "Setting up kubeconfig..."
    kind get kubeconfig --name kind > kubeconfig
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

# Label nodes for region-based scheduling (only if cluster is being created)
if [ "$CREATE_CLUSTER" = true ]; then
    log_info "Labeling nodes for region-based scheduling..."
    if kubectl get nodes | grep -q "kind-worker"; then
        kubectl label node kind-worker REGION=TEN --overwrite
        log_success "Labeled kind-worker as REGION=TEN"
    fi

    if kubectl get nodes | grep -q "kind-worker2"; then
        kubectl label node kind-worker2 REGION=NE --overwrite
        log_success "Labeled kind-worker2 as REGION=NE"
    fi
fi

log_info "Ensuring namespace foo exists..."
if ! kubectl get namespace foo &> /dev/null; then
    kubectl create namespace foo
    log_success "Created namespace foo"
else
    log_info "Namespace foo already exists"
fi


log_info "Ensuring namespace $NAMESPACE exists..."
if ! kubectl get namespace $NAMESPACE &> /dev/null; then
    kubectl create namespace $NAMESPACE
    log_success "Created namespace $NAMESPACE"
else
    log_info "Namespace $NAMESPACE already exists"
fi

# Deploy the manifests based on flags
log_info "Deploying Flex-Nautilus manifests..."

# Always deploy roles first (needed for RBAC)
log_info "Applying roles.yml..."
if kubectl apply -f $MANIFESTS_DIR/roles.yml; then
    log_success "Successfully applied roles.yml"
else
    log_error "Failed to apply roles.yml"
    exit 1
fi

# Deploy storage if requested
if [ "$CREATE_DB" = true ]; then
    log_info "Applying storage.yml..."
    if kubectl apply -f $MANIFESTS_DIR/storage.yml; then
        log_success "Successfully applied storage.yml"
    else
        log_error "Failed to apply storage.yml"
        exit 1
    fi
fi

# Deploy migration service if requested
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
    
    # Create migrator pod for kind-worker
    log_info "Creating migrator pod for kind-worker..."
    if sed 's/{NODE_NAME}/kind-worker/g' $MANIFESTS_DIR/migrator.yml | kubectl apply -f -; then
        log_success "Successfully created migrator pod for kind-worker"
    else
        log_error "Failed to create migrator pod for kind-worker"
        exit 1
    fi
    
    # Create migrator pod for kind-worker2
    log_info "Creating migrator pod for kind-worker2..."
    if sed 's/{NODE_NAME}/kind-worker2/g' $MANIFESTS_DIR/migrator.yml | kubectl apply -f -; then
        log_success "Successfully created migrator pod for kind-worker2"
    else
        log_error "Failed to create migrator pod for kind-worker2"
        exit 1
    fi
fi

# Deploy controller if requested
if [ "$CREATE_CONTROLLER" = true ]; then
    log_info "Applying controller.yml..."
    if kubectl apply -f $MANIFESTS_DIR/controller.yml; then
        log_success "Successfully applied controller.yml"
    else
        log_error "Failed to apply controller.yml"
        exit 1
    fi
fi

# Deploy benchmark pod if all components are being deployed
log_info "Applying testpod.yml..."
if kubectl apply -f $MANIFESTS_DIR/testpod.yml; then
    log_success "Successfully applied testpod.yml"
else
    log_error "Failed to apply testpod.yml"
    exit 1
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
    if kubectl wait --for=condition=Ready pod migrator-kind-worker -n $NAMESPACE --timeout=300s; then
        log_success "migrator-kind-worker is ready"
    else
        log_error "migrator-kind-worker failed to become ready"
        exit 1
    fi
    
    if kubectl wait --for=condition=Ready pod migrator-kind-worker2 -n $NAMESPACE --timeout=300s; then
        log_success "migrator-kind-worker2 is ready"
    else
        log_error "migrator-kind-worker2 failed to become ready"
        exit 1
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
    log_info "3. Check database status:"
    log_info "   kubectl get pods -n $NAMESPACE -l app=postgres"
    log_info ""
fi

log_info "4. Monitor all pods:"
log_info "   kubectl get pods -n $NAMESPACE -w"

log_success "Flex-Nautilus deployment completed!"
