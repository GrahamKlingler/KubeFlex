#!/bin/bash

# KubeFlex Docker Build and Push Script
# This script builds and pushes all necessary Docker images for the KubeFlex system

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

log_info "=========================================="
log_info "KubeFlex DOCKER BUILD SCRIPT"
log_info "=========================================="

# Configuration
LOAD_KIND=false

# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --load-kind)
            LOAD_KIND=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--load-kind] [--help]"
            echo ""
            echo "Options:"
            echo "  --load-kind  Load images into KIND cluster after building (avoids Docker Hub rate limits)"
            echo "               Recommended for local development. Requires KIND cluster to be running."
            echo "  --help       Show this help message"
            echo ""
            echo "Note: Without --load-kind, you must be logged into Docker Hub (docker login)"
            echo "      to push images. Use --load-kind to avoid Docker Hub authentication."
            exit 0
            ;;
    esac
done

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed or not in PATH"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running or not accessible"
    exit 1
fi

# Check Docker Hub authentication (only if not using --load-kind)
if [ "$LOAD_KIND" = false ]; then
    if ! docker login &> /dev/null; then
        log_warning "Not logged into Docker Hub. Attempting to push will fail."
        log_info "Options:"
        log_info "  1. Login to Docker Hub: docker login"
        log_info "  2. Use --load-kind flag to load images directly into KIND (recommended for local development)"
        read -p "Do you want to login to Docker Hub now? (y/N) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker login
        else
            log_info "Skipping Docker Hub login. Use --load-kind to avoid pushing to Docker Hub."
            log_info "Or run: docker login"
            exit 1
        fi
    else
        log_success "Authenticated with Docker Hub"
    fi
fi

# If loading into KIND, check if kind is available and get cluster name
if [ "$LOAD_KIND" = true ]; then
    if ! command -v kind &> /dev/null; then
        log_error "kind is not installed. Please install kind first or remove --load-kind flag"
        exit 1
    fi
    
    CLUSTER_NAME=$(grep -E "^name:" manifests/cluster.yml 2>/dev/null | awk '{print $2}' | tr -d '"' || echo "kind")
    
    # Check if KIND cluster exists
    if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
        log_warning "KIND cluster '${CLUSTER_NAME}' does not exist"
        log_info "You need to create the cluster first. Options:"
        log_info "  1. Run: ./run.sh --include-cluster (creates cluster and deploys everything)"
        log_info "  2. Or create cluster manually: kind create cluster --config manifests/cluster.yml"
        log_info ""
        read -p "Do you want to create the KIND cluster now? (y/N) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Creating KIND cluster..."
            if kind create cluster --config manifests/cluster.yml; then
                log_success "KIND cluster created successfully"
            else
                log_error "Failed to create KIND cluster"
                exit 1
            fi
        else
            log_warning "Skipping KIND cluster creation. Images will be built but not loaded."
            log_info "You can load them later with: kind load docker-image IMAGE_NAME --name ${CLUSTER_NAME}"
            LOAD_KIND=false  # Disable loading since cluster doesn't exist
        fi
    else
        log_success "Found KIND cluster: ${CLUSTER_NAME}"
        log_info "Will load images into KIND cluster: ${CLUSTER_NAME}"
    fi
fi

# Clean up old images to force fresh builds
log_info "Cleaning up old migration controller images..."
docker rmi python-migrate:latest salamander1223/python-migrate:latest 2>/dev/null || true

# Build and push migration controller
log_info "Building migration controller..."
BUILD_TIMESTAMP=$(date +%s)
if docker build -t python-migrate:latest -f build/Dockerfile.migrate --build-arg BUILD_TIMESTAMP=${BUILD_TIMESTAMP} .; then
    log_success "Migration controller built successfully"
    docker tag python-migrate:latest salamander1223/python-migrate:latest
    
    if [ "$LOAD_KIND" = true ]; then
        log_info "Loading migration controller image into KIND cluster..."
        if kind load docker-image salamander1223/python-migrate:latest --name ${CLUSTER_NAME} 2>/dev/null; then
            log_success "Migration controller image loaded into KIND successfully"
        else
            log_warning "Failed to load migration controller into KIND"
            log_info "Cluster may not exist. Run: kind create cluster --config manifests/cluster.yml"
        fi
    else
    if docker push salamander1223/python-migrate:latest; then
        log_success "Migration controller pushed successfully"
    else
        log_error "Failed to push migration controller"
        exit 1
        fi
    fi
else
    log_error "Failed to build migration controller"
    exit 1
fi

# Build and push migrator
log_info "Building migrator..."
if docker build -t migrator:latest -f build/Dockerfile.migrator .; then
    log_success "Migrator built successfully"
    docker tag migrator:latest salamander1223/migrator:latest
    
    if [ "$LOAD_KIND" = true ]; then
        log_info "Loading migrator image into KIND cluster..."
        if kind load docker-image salamander1223/migrator:latest --name ${CLUSTER_NAME} 2>/dev/null; then
            log_success "Migrator image loaded into KIND successfully"
        else
            log_warning "Failed to load migrator into KIND"
        fi
    else
    if docker push salamander1223/migrator:latest; then
        log_success "Migrator pushed successfully"
    else
        log_error "Failed to push migrator"
        exit 1
        fi
    fi
else
    log_error "Failed to build migrator"
    exit 1
fi

# Build and push main controller
log_info "Building main controller..."
if docker build -t python-controller:latest -f build/Dockerfile.main .; then
    log_success "Main controller built successfully"
    docker tag python-controller:latest salamander1223/python-controller:latest
    
    if [ "$LOAD_KIND" = true ]; then
        log_info "Loading main controller image into KIND cluster..."
        if kind load docker-image salamander1223/python-controller:latest --name ${CLUSTER_NAME} 2>/dev/null; then
            log_success "Main controller image loaded into KIND successfully"
        else
            log_warning "Failed to load main controller into KIND"
        fi
    else
    if docker push salamander1223/python-controller:latest; then
        log_success "Main controller pushed successfully"
    else
        log_error "Failed to push main controller"
        exit 1
        fi
    fi
else
    log_error "Failed to build main controller"
    exit 1
fi

log_info "Building test pod..."
if docker build -t testpod:latest -f build/Dockerfile.testpod .; then
    log_success "Test pod built successfully"
    docker tag testpod:latest salamander1223/testpod:latest
    
    if [ "$LOAD_KIND" = true ]; then
        log_info "Loading test pod image into KIND cluster..."
        if kind load docker-image salamander1223/testpod:latest --name ${CLUSTER_NAME} 2>/dev/null; then
            log_success "Test pod image loaded into KIND successfully"
        else
            log_warning "Failed to load test pod into KIND"
        fi
    else
    if docker push salamander1223/testpod:latest; then
        log_success "Test pod pushed successfully"
    else
        log_error "Failed to push test pod"
        exit 1
        fi
    fi
else
    log_error "Failed to build test pod"
    exit 1
fi

# Build and push DB upload service
log_info "Building database upload service..."
if docker build -t python-db-upload:latest -f build/Dockerfile.db .; then
    log_success "Database upload service built successfully"
    docker tag python-db-upload:latest salamander1223/python-db-upload:latest
    
    if [ "$LOAD_KIND" = true ]; then
        log_info "Loading database upload service image into KIND cluster..."
        if kind load docker-image salamander1223/python-db-upload:latest --name ${CLUSTER_NAME} 2>/dev/null; then
            log_success "Database upload service image loaded into KIND successfully"
        else
            log_warning "Failed to load database upload service into KIND"
        fi
    else
        if docker push salamander1223/python-db-upload:latest; then
            log_success "Database upload service pushed successfully"
        else
            log_error "Failed to push database upload service"
            exit 1
        fi
    fi
else
    log_error "Failed to build database upload service"
    exit 1
fi

# Build and push metadata service (sidecar for database)
log_info "Building metadata service..."
if docker build -t python-metadata:latest -f build/Dockerfile.metadata .; then
    log_success "Metadata service built successfully"
    docker tag python-metadata:latest salamander1223/python-metadata:latest
    
    if [ "$LOAD_KIND" = true ]; then
        log_info "Loading metadata service image into KIND cluster..."
        if kind load docker-image salamander1223/python-metadata:latest --name ${CLUSTER_NAME} 2>/dev/null; then
            log_success "Metadata service image loaded into KIND successfully"
        else
            log_warning "Failed to load metadata service into KIND"
        fi
    else
        if docker push salamander1223/python-metadata:latest; then
            log_success "Metadata service pushed successfully"
        else
            log_error "Failed to push metadata service"
            exit 1
        fi
    fi
else
    log_error "Failed to build metadata service"
    exit 1
fi

log_info "=========================================="
log_success "ALL DOCKER IMAGES BUILT AND PUSHED SUCCESSFULLY"
log_info "=========================================="

log_info "Built and pushed images:"
log_info "  - salamander1223/python-migrate:latest"
log_info "  - salamander1223/migrator:latest"
log_info "  - salamander1223/python-controller:latest"
log_info "  - salamander1223/testpod:latest"
log_info "  - salamander1223/python-db-upload:latest"
log_info "  - salamander1223/python-metadata:latest"

log_info ""
log_info "Next steps:"
log_info "1. Deploy the system: ./deploy.sh"
log_info "2. Run tests: python3 controller/test_migration.py --test all"
log_info "3. Clean up: ./delete.sh --all"