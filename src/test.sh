#!/bin/bash

# KubeFlex Migration Service - Test Script
# Supports migration testing and carbon forecast generation

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default values
NAMESPACE="test-namespace"
POD="test-pod"
SOURCE_NODE="kind-worker"
TARGET_NODE="kind-worker2"
MIGRATION_URL="http://localhost:8000"  # Migration service
METADATA_URL="http://localhost:8008"   # Metadata service
OUTPUT_DIR="./output"
FORECAST_DURATION=""
RUN_MIGRATION_TEST=false
RUN_FORECAST=false
KEEP_POD=true  # If true, don't delete original pod after migration (default: true - keep pod)

# Port forwarding variables
MIGRATION_PORT_FORWARD_PID=""
METADATA_PORT_FORWARD_PID=""

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

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_forecast() {
    echo -e "${CYAN}[FORECAST]${NC} $1"
}

# Function to print usage
print_usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
    --migration             Run migration test (default if no forecast options)
    --forecast DURATION     Generate combined carbon forecast (min forecast + all region forecasts)
                            DURATION: Duration in hours (e.g., 24, 72)
    --output DIR            Output directory for plots and data (default: ./output)
    --pod POD               Pod name for migration test (default: test-pod)
    --namespace NAMESPACE   Kubernetes namespace (default: test-namespace)
    --source-node NODE      Source node for migration (default: kind-worker)
    --target-node NODE      Target node for migration (default: kind-worker2)
    --migration-url URL      Migration service URL (default: http://localhost:8000)
    --metadata-url URL      Metadata service URL (default: http://localhost:8008)
    --keep-pod              Keep the original pod after migration (default: true - pod is kept)
    --delete-pod            Delete the original pod after migration (overrides default keep behavior)
    --help                  Show this help message

Examples:
    # Run migration test
    $0 --migration

    # Generate combined forecast for 24 hours
    $0 --forecast 24 --output ./forecasts

    # Run migration and generate forecast
    $0 --migration --forecast 24 --output ./results
EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --migration)
                RUN_MIGRATION_TEST=true
                shift
                ;;
            --forecast)
                if [ -z "$2" ]; then
                    log_error "--forecast requires DURATION argument"
                    exit 1
                fi
                FORECAST_DURATION="$2"
                RUN_FORECAST=true
                shift 2
                ;;
            --output)
                if [ -z "$2" ]; then
                    log_error "--output requires DIR argument"
                    exit 1
                fi
                OUTPUT_DIR="$2"
                shift 2
                ;;
            --pod)
                POD="$2"
                shift 2
                ;;
            --namespace)
                NAMESPACE="$2"
                shift 2
                ;;
            --source-node)
                SOURCE_NODE="$2"
                shift 2
                ;;
            --target-node)
                TARGET_NODE="$2"
                shift 2
                ;;
            --migration-url)
                MIGRATION_URL="$2"
                shift 2
                ;;
            --metadata-url)
                METADATA_URL="$2"
                shift 2
                ;;
            --keep-pod)
                KEEP_POD=true
                shift
                ;;
            --delete-pod)
                KEEP_POD=false
                shift
                ;;
            --help)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                print_usage
                exit 1
                ;;
        esac
    done

    # If no specific action is requested, default to migration test
    if [ "$RUN_MIGRATION_TEST" = false ] && [ "$RUN_FORECAST" = false ]; then
        RUN_MIGRATION_TEST=true
        log_info "No action specified, defaulting to migration test"
    fi
}

# Function to set up port forwarding for migration service
setup_migration_port_forward() {
    log_info "Setting up port forwarding to python-migrate-service..."
    
    # Check if port forwarding is already running
    if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "Port 8000 is already in use, killing existing process..."
        lsof -ti:8000 | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
    
    # Start port forwarding in background
    kubectl port-forward -n monitor service/python-migrate-service 8000:8000 > /dev/null 2>&1 &
    MIGRATION_PORT_FORWARD_PID=$!
    
    # Wait a moment for port forwarding to establish
    sleep 3
    
    # Test if port forwarding is working
    if curl -s "$MIGRATION_URL/health" > /dev/null 2>&1; then
        log_success "Migration service port forwarding established successfully"
        return 0
    else
        log_error "Migration service port forwarding failed to establish"
        return 1
    fi
}

# Function to set up port forwarding for metadata service
setup_metadata_port_forward() {
    log_info "Setting up port forwarding to metadata-service..."
    
    # Check if port forwarding is already running
    if lsof -Pi :8008 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "Port 8008 is already in use, killing existing process..."
        lsof -ti:8008 | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
    
    # Start port forwarding in background
    kubectl port-forward -n monitor service/metadata-service 8008:8008 > /dev/null 2>&1 &
    METADATA_PORT_FORWARD_PID=$!
    
    # Wait a moment for port forwarding to establish
    sleep 3
    
    # Test if port forwarding is working (metadata service doesn't have /health, so we'll test with a GET request)
    if curl -s "$METADATA_URL" > /dev/null 2>&1; then
        log_success "Metadata service port forwarding established successfully"
        return 0
    else
        log_warning "Metadata service port forwarding may not be ready yet"
        return 0  # Don't fail, service might be starting
    fi
}

# Function to clean up port forwarding
cleanup_port_forward() {
    if [ ! -z "$MIGRATION_PORT_FORWARD_PID" ]; then
        log_info "Cleaning up migration service port forwarding (PID: $MIGRATION_PORT_FORWARD_PID)..."
        kill $MIGRATION_PORT_FORWARD_PID 2>/dev/null || true
        MIGRATION_PORT_FORWARD_PID=""
    fi
    
    if [ ! -z "$METADATA_PORT_FORWARD_PID" ]; then
        log_info "Cleaning up metadata service port forwarding (PID: $METADATA_PORT_FORWARD_PID)..."
        kill $METADATA_PORT_FORWARD_PID 2>/dev/null || true
        METADATA_PORT_FORWARD_PID=""
    fi
    
    # Also kill any remaining processes on ports
    if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "Killing remaining processes on port 8000..."
        lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    fi
    
    if lsof -Pi :8008 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "Killing remaining processes on port 8008..."
        lsof -ti:8008 | xargs kill -9 2>/dev/null || true
    fi
}

# Test migration function
test_migration() {
    log_info "Testing live migration: $POD -> $TARGET_NODE"
    
    # Get source node from pod if not specified
    if [ -z "$SOURCE_NODE" ] || [ "$SOURCE_NODE" = "kind-worker" ]; then
        SOURCE_NODE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}' 2>/dev/null || echo "kind-worker")
    fi
    
    # Get target region from target node
    local target_region=$(kubectl get node "$TARGET_NODE" -o jsonpath='{.metadata.labels.REGION}' 2>/dev/null || echo "")
    if [ -z "$target_region" ]; then
        log_warning "Could not determine target region from node $TARGET_NODE"
    else
        log_info "Target region: $target_region"
    fi
    
    # Create migration request
    local migration_request=$(cat <<EOF
{
    "namespace": "$NAMESPACE",
    "pod": "$POD",
    "source_node": "$SOURCE_NODE",
    "target_node": "$TARGET_NODE",
    "target_region": "$target_region",
    "delete_original": $([ "$KEEP_POD" = true ] && echo "false" || echo "true")
}
EOF
)
    
    log_info "Sending migration request:"
    echo "$migration_request" | jq .
    
    # Send request
    log_info "Sending request to: $MIGRATION_URL/live-migrate"
    local response
    if ! response=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "$migration_request" \
        "$MIGRATION_URL/live-migrate" 2>/dev/null); then
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
    
    # Pod deletion is now handled by the migration service
    if [ "$KEEP_POD" = true ]; then
        log_info "Original pod $POD will be kept (default behavior - migration service will not delete it)"
    else
        log_info "Original pod $POD will be deleted by the migration service after successful migration (--delete-pod flag set)"
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
    
    # Test migration service health endpoint
    if [ "$RUN_MIGRATION_TEST" = true ]; then
        log_info "Testing migration service health endpoint: $MIGRATION_URL/health"
    local health_response
        if health_response=$(curl -s "$MIGRATION_URL/health" 2>/dev/null); then
            log_success "Migration service health check successful"
        echo "$health_response" | jq . 2>/dev/null || echo "$health_response"
    else
            log_error "Migration service health check failed"
        return 1
        fi
    fi
    
    return 0
}


# Generate combined forecast using metadata service
generate_forecast() {
    local duration="$1"
    
    log_forecast "Generating combined carbon forecast for duration: $duration hours"
    
    # Create output directory
    mkdir -p "$OUTPUT_DIR"
    
    # Set up port forwarding for metadata service if not already done
    if [ -z "$METADATA_PORT_FORWARD_PID" ]; then
        if ! setup_metadata_port_forward; then
            log_error "Failed to set up metadata service port forwarding"
            return 1
        fi
    fi
    
    # Use the combined endpoint (duration only) to get min forecast + all region forecasts
    local forecast_request=$(cat <<EOF
{
    "duration": $duration
}
EOF
)
    
    log_forecast "Requesting combined forecast data from metadata service..."
    local response
    if ! response=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "$forecast_request" \
        "$METADATA_URL" 2>/dev/null); then
        log_error "Failed to connect to metadata service"
        return 1
    fi
    
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" != "200" ]; then
        log_error "Metadata service returned HTTP $http_code"
        echo "$body" | jq . 2>/dev/null || echo "$body"
        return 1
    fi
    
    # The response body IS the forecast data (not metadata about it)
    # Save it directly to the output file
    local output_file="$OUTPUT_DIR/forecast_${duration}h.json"
    echo "$body" | jq . > "$output_file"
    
    # Extract summary information for logging
    local min_data_points=$(echo "$body" | jq -r '.min_forecast.forecast_data | length')
    local regions=$(echo "$body" | jq -r '.region_forecasts | keys[]' | tr '\n' ',' | sed 's/,$//')
    local region_count=$(echo "$body" | jq -r '.region_forecasts | keys | length')
    
    log_success "Combined forecast saved to: $output_file"
    log_forecast "Min forecast data points: $min_data_points"
    log_forecast "Regions included: $regions ($region_count regions)"
    
    # Print summary for each region
    for region in $(echo "$body" | jq -r '.region_forecasts | keys[]'); do
        local region_points=$(echo "$body" | jq -r ".region_forecasts[\"$region\"].forecast_data | length")
        log_forecast "  $region: $region_points data points"
    done
    
    return 0
}

# Main function
main() {
    log_info "============================================================"
    log_info "KubeFlex Test Script"
    log_info "============================================================"
    
    # Parse arguments
    parse_arguments "$@"
    
    # Display configuration
    if [ "$RUN_MIGRATION_TEST" = true ]; then
        log_info "Migration Test Configuration:"
        log_info "  Service URL: $MIGRATION_URL (via port forwarding)"
        log_info "  Namespace: $NAMESPACE"
        log_info "  Pod: $POD"
        log_info "  Target Node: $TARGET_NODE"
        if [ "$KEEP_POD" = true ]; then
            log_info "  Keep Original Pod: Yes (default - original pod will be kept after migration)"
        else
            log_info "  Keep Original Pod: No (--delete-pod flag set - original pod will be deleted after migration)"
        fi
    fi
    
    if [ "$RUN_FORECAST" = true ]; then
        log_info "Forecast Configuration:"
        log_info "  Output Directory: $OUTPUT_DIR"
        log_info "  Duration: $FORECAST_DURATION hours"
    fi
    
    log_info ""
    
    # Check if kubectl is available
    if ! command -v kubectl >/dev/null 2>&1; then
        log_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check if jq is available (needed for migration test)
    if [ "$RUN_MIGRATION_TEST" = true ] && ! command -v jq >/dev/null 2>&1; then
        log_error "jq is not installed or not in PATH (required for migration test)"
        exit 1
    fi
    
    # Check if curl is available
    if ! command -v curl >/dev/null 2>&1; then
        log_error "curl is not installed or not in PATH"
        exit 1
    fi
    
    # Check if jq is available (needed for forecasts and parsing JSON responses)
    if [ "$RUN_FORECAST" = true ]; then
        if ! command -v jq >/dev/null 2>&1; then
            log_error "jq is not installed or not in PATH (required for forecast generation)"
            exit 1
        fi
    fi
    
    # Set up port forwarding for migration service if needed
    if [ "$RUN_MIGRATION_TEST" = true ]; then
        if ! setup_migration_port_forward; then
            log_error "Failed to set up migration service port forwarding. Exiting."
            exit 1
        fi
    fi
    
    # Set up port forwarding for metadata service if needed for forecasts
    if [ "$RUN_FORECAST" = true ]; then
        if ! setup_metadata_port_forward; then
            log_error "Failed to set up metadata service port forwarding. Exiting."
        exit 1
        fi
    fi
    
    # Set up cleanup trap
    trap cleanup_port_forward EXIT
    
    # Test service connectivity if running migration test
    if [ "$RUN_MIGRATION_TEST" = true ]; then
    if ! test_service_connectivity; then
        log_error "Service connectivity test failed"
        exit 1
    fi
    
    # Check if test pod exists
    if ! check_test_pod; then
        exit 1
    fi
    fi
    
    local exit_code=0
    
    # Run migration test
    if [ "$RUN_MIGRATION_TEST" = true ]; then
    log_info "Running migration test..."
    log_info "----------------------------------------"
        if ! test_migration; then
            log_error "❌ Migration test failed"
            exit_code=1
        else
        log_success "🎉 Migration test completed successfully!"
        fi
        log_info ""
    fi
    
    # Generate combined forecast
    if [ "$RUN_FORECAST" = true ]; then
        log_info "Generating combined forecast..."
        log_info "----------------------------------------"
        if ! generate_forecast "$FORECAST_DURATION"; then
            log_error "❌ Forecast generation failed"
            exit_code=1
        else
            log_success "🎉 Forecast generated successfully!"
        fi
        log_info ""
    fi
    
    # Summary
    log_info "============================================================"
    if [ $exit_code -eq 0 ]; then
        log_success "All tests completed successfully!"
        if [ -n "$OUTPUT_DIR" ] && [ -d "$OUTPUT_DIR" ]; then
            log_info "Output files saved to: $OUTPUT_DIR"
            ls -lh "$OUTPUT_DIR" 2>/dev/null | tail -n +2 || true
        fi
    else
        log_error "Some tests failed"
    fi
    log_info "============================================================"
    
    exit $exit_code
}

# Run main function
main "$@"
