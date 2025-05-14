#!/bin/bash

kubectl apply -f testpod.yml
sleep 5

# Directory to store the plots
PLOT_DIR="plots"
mkdir -p "$PLOT_DIR"

# Start port forwarding in the background
echo "Starting port forwarding..."
kubectl port-forward svc/metadata-service 8008:8008 &
PORT_FORWARD_PID=$!

# Wait for port forwarding to be ready
sleep 5

# Array of pod configurations
declare -a pods=(
    "test-pod:TEN:foo"
    "test-pod2:NE:foo"
    "test-pod3:NE:foo"
)

# Function to make POST request and download plot
process_pod() {
    local pod_name=$1
    local pod_region=$2
    local pod_namespace=$3
    
    echo "Processing pod: $pod_name in region $pod_region (namespace: $pod_namespace)"
    
    # Make POST request
    curl -X POST http://localhost:8008 \
        -H "Content-Type: application/json" \
        -d "{\"pod_name\": \"$pod_name\", \"pod_region\": \"$pod_region\", \"pod_namespace\": \"$pod_namespace\"}"
    
    # Download the plot
    curl "http://localhost:8008/plot_${pod_name}.html" -o "${PLOT_DIR}/plot_${pod_name}.html"
}

# Process each pod configuration
for pod_config in "${pods[@]}"; do
    IFS=':' read -r pod_name pod_region pod_namespace <<< "$pod_config"
    process_pod "$pod_name" "$pod_region" "$pod_namespace"
done

# Clean up port forwarding
echo "Cleaning up..."
kill $PORT_FORWARD_PID

echo "All plots have been downloaded to the $PLOT_DIR directory" 