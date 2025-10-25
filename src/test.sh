#!/bin/bash

# Flex-Nautilus Migration Service - Test Script
# Hardcoded values for easy testing

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Hardcoded values
NAMESPACE="foo"
POD="test-pod"
SOURCE_NODE="kind-worker"
TARGET_NODE="kind-worker2"
URL="http://localhost:8000"  # Use localhost with port forwarding

# Port forwarding variables
PORT_FORWARD_PID=""

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to set up port forwarding
setup_port_forward() {
    log_info "Setting up port forwarding to python-migrate-service..."
    
    # Check if port forwarding is already running
    if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "Port 8000 is already in use, killing existing process..."
        lsof -ti:8000 | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
    
    # Start port forwarding in background
    kubectl port-forward -n monitor service/python-migrate-service 8000:8000 > /dev/null 2>&1 &
    PORT_FORWARD_PID=$!
    
    # Wait a moment for port forwarding to establish
    sleep 3
    
    # Test if port forwarding is working
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        log_success "Port forwarding established successfully"
        return 0
    else
        log_error "Port forwarding failed to establish"
        return 1
    fi
}

# Function to clean up port forwarding
cleanup_port_forward() {
    if [ ! -z "$PORT_FORWARD_PID" ]; then
        log_info "Cleaning up port forwarding (PID: $PORT_FORWARD_PID)..."
        kill $PORT_FORWARD_PID 2>/dev/null || true
        PORT_FORWARD_PID=""
    fi
    
    # Also kill any remaining processes on port 8000
    if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "Killing remaining processes on port 8000..."
        lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    fi
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Test migration function
test_migration() {
    log_info "Testing live migration: $POD -> $TARGET_NODE"
    
    # Create migration request
    local migration_request=$(cat <<EOF
{
    "namespace": "$NAMESPACE",
    "pod": "$POD",
    "source_node": "$SOURCE_NODE",
    "target_node": "$TARGET_NODE"
}
EOF
)
    
    log_info "Sending migration request:"
    echo "$migration_request" | jq .
    
    # Send request
    log_info "Sending request to: $URL/live-migrate"
    local response
    if ! response=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "$migration_request" \
        "$URL/live-migrate" 2>/dev/null); then
        log_error "Migration failed: Connection error"
        return 1
    fi
    
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')
    
    log_info "HTTP Response Code: $http_code"
    log_info "Response Body:"
    echo "$body" | jq . 2>/dev/null || echo "$body"
    
    if [ "$http_code" != "200" ]; then
        log_error "Migration failed: HTTP $http_code"
        return 1
    fi
    
    # Check if response is valid JSON
    if ! echo "$body" | jq . >/dev/null 2>&1; then
        log_error "Migration failed: Invalid JSON response"
        return 1
    fi
    
    # Check for success status
    local status=$(echo "$body" | jq -r '.status // "unknown"')
    if [ "$status" != "success" ]; then
        log_error "Migration failed: Status is '$status'"
        return 1
    fi
    
    return 0
}

# Check if test pod exists
check_test_pod() {
    log_info "Checking if test pod exists..."
    
    if ! kubectl get pod "$POD" -n "$NAMESPACE" >/dev/null 2>&1; then
        log_error "Test pod '$POD' not found in namespace '$NAMESPACE'"
        log_info "Please create the test pod first"
        return 1
    fi
    
    log_success "Test pod '$POD' found in namespace '$NAMESPACE'"
    return 0
}

# Test service connectivity
test_service_connectivity() {
    log_info "Testing service connectivity..."
    
    # Test health endpoint
    log_info "Testing health endpoint: $URL/health"
    local health_response
    if health_response=$(curl -s "$URL/health" 2>/dev/null); then
        log_success "Health check successful"
        echo "$health_response" | jq . 2>/dev/null || echo "$health_response"
    else
        log_error "Health check failed"
        return 1
    fi
    
    return 0
}

# Main function
main() {
    log_info "============================================================"
    log_info "Flex-Nautilus Migration Service"
    log_info "============================================================"
    log_info "Service URL: $URL (via port forwarding)"
    log_info "Namespace: $NAMESPACE"
    log_info "Pod: $POD"
    log_info "Target Node: $TARGET_NODE"
    log_info ""
    
    # Check if kubectl is available
    if ! command -v kubectl >/dev/null 2>&1; then
        log_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check if jq is available
    if ! command -v jq >/dev/null 2>&1; then
        log_error "jq is not installed or not in PATH"
        exit 1
    fi
    
    # Check if curl is available
    if ! command -v curl >/dev/null 2>&1; then
        log_error "curl is not installed or not in PATH"
        exit 1
    fi
    
    # Set up port forwarding
    if ! setup_port_forward; then
        log_error "Failed to set up port forwarding. Exiting."
        exit 1
    fi
    
    # Set up cleanup trap
    trap cleanup_port_forward EXIT
    
    # Test service connectivity
    if ! test_service_connectivity; then
        log_error "Service connectivity test failed"
        exit 1
    fi
    
    # Check if test pod exists
    if ! check_test_pod; then
        exit 1
    fi
    
    # Run migration test
    log_info "Running migration test..."
    log_info "----------------------------------------"
    if test_migration; then
        log_success "🎉 Migration test completed successfully!"
        exit 0
    else
        log_error "❌ Migration test failed"
        exit 1
    fi
}

# Run main function
main "$@"
