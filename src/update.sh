#!/bin/bash

# Flex-Nautilus Docker Build and Push Script
# This script builds and pushes all necessary Docker images for the Flex-Nautilus system

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
log_info "FLEX-NAUTILUS DOCKER BUILD SCRIPT"
log_info "=========================================="

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed or not in PATH"
    exit 1
fi

# Check if we're logged into Docker Hub
if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running or not accessible"
    exit 1
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
    if docker push salamander1223/python-migrate:latest; then
        log_success "Migration controller pushed successfully"
    else
        log_error "Failed to push migration controller"
        exit 1
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
    if docker push salamander1223/migrator:latest; then
        log_success "Migrator pushed successfully"
    else
        log_error "Failed to push migrator"
        exit 1
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
    if docker push salamander1223/python-controller:latest; then
        log_success "Main controller pushed successfully"
    else
        log_error "Failed to push main controller"
        exit 1
    fi
else
    log_error "Failed to build main controller"
    exit 1
fi

log_info "Building test pod..."
if docker build -t testpod:latest -f build/Dockerfile.testpod .; then
    log_success "Test pod built successfully"
    docker tag testpod:latest salamander1223/testpod:latest
    if docker push salamander1223/testpod:latest; then
        log_success "Test pod pushed successfully"
    else
        log_error "Failed to push test pod"
        exit 1
    fi
else
    log_error "Failed to build test pod"
    exit 1
fi

# # Build and push DB upload service
# log_info "Building database upload service..."
# if docker build -t python-db-upload:latest -f build/Dockerfile.db .; then
#     log_success "Database upload service built successfully"
#     docker tag python-db-upload:latest salamander1223/python-db-upload:latest
#     if docker push salamander1223/python-db-upload:latest; then
#         log_success "Database upload service pushed successfully"
#     else
#         log_error "Failed to push database upload service"
#         exit 1
#     fi
# else
#     log_error "Failed to build database upload service"
#     exit 1
# fi

# # Build and push data server
# log_info "Building data server..."
# if docker build -t python-data-server:latest -f build/Dockerfile.data-server .; then
#     log_success "Data server built successfully"
#     docker tag python-data-server:latest salamander1223/python-data-server:latest
#     if docker push salamander1223/python-data-server:latest; then
#         log_success "Data server pushed successfully"
#     else
#         log_error "Failed to push data server"
#         exit 1
#     fi
# else
#     log_error "Failed to build data server"
#     exit 1
# fi

log_info "=========================================="
log_success "ALL DOCKER IMAGES BUILT AND PUSHED SUCCESSFULLY"
log_info "=========================================="

log_info "Built and pushed images:"
log_info "  - salamander1223/python-migrate:latest"
log_info "  - salamander1223/python-controller:latest"
log_info "  - salamander1223/testpod:latest"
log_info "  - salamander1223/python-db-upload:latest"
log_info "  - salamander1223/python-data-server:latest"

log_info ""
log_info "Next steps:"
log_info "1. Deploy the system: ./deploy.sh"
log_info "2. Run tests: python3 controller/test_migration.py --test all"
log_info "3. Clean up: ./delete.sh --all"