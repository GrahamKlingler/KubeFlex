#!/bin/bash

# Lists of possible values
POD_NAMES=(test-pod test-pod2 test-pod3 test-pod4 test-pod5)
POD_REGIONS=(TEN NE SW SE CAL CENT)
EXPECTED_DURATIONS=(12 24 36 48 60)
N_PODS=5  # Number of pods to create

# Directory to store the plots
PLOT_DIR="plots"
DATA_DIR="data"
YAML_DIR="generated_pods"
mkdir -p "$PLOT_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$YAML_DIR"

# Function to generate a random pod YAML
create_pod_yaml() {
    local pod_name=$1
    local pod_region=$2
    local expected_duration=$3
    local yaml_file=$4
    cat <<EOF > "$yaml_file"
apiVersion: v1
kind: Pod
metadata:
  name: $pod_name
  namespace: foo
  labels:
    name: $pod_name
  annotations:
    REGION: "$pod_region"
    EXPECTED_DURATION: "$expected_duration"
spec:
  containers:
  - name: test-container
    image: busybox:latest
    command: ["sh", "-c", "echo Hello Kubernetes! && sleep 6000"]
    imagePullPolicy: IfNotPresent
    resources:
      requests:
        memory: "128Mi"
        cpu: "1000m"
      limits:
        memory: "256Mi"
        cpu: "2000m"
    ports:
    - name: http
      containerPort: 8080
      protocol: TCP
EOF
}

# Array to keep track of pod configs
declare -a pods=()

# Generate and apply pods by iterating through POD_NAMES in order
num_pods_to_create=$(( N_PODS < ${#POD_NAMES[@]} ? N_PODS : ${#POD_NAMES[@]} ))
for ((i=0; i<num_pods_to_create; i++)); do
    pod_name=${POD_NAMES[$i]}
    pod_region=${POD_REGIONS[$RANDOM % ${#POD_REGIONS[@]}]}
    expected_duration=${EXPECTED_DURATIONS[$RANDOM % ${#EXPECTED_DURATIONS[@]}]}
    yaml_file="$YAML_DIR/pod_${pod_name}_${pod_region}_${expected_duration}.yml"
    create_pod_yaml "$pod_name" "$pod_region" "$expected_duration" "$yaml_file"
    kubectl apply -f "$yaml_file"
    pods+=("$pod_name:$pod_region:foo")
done

sleep 5

# Start port forwarding in the background
echo "Starting port forwarding..."
kubectl port-forward svc/metadata-service 8008:8008 &
PORT_FORWARD_PID=$!

# Wait for port forwarding to be ready
sleep 5

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
    curl "http://localhost:8008/raw_data_${pod_name}_${pod_region}.json" -o "${DATA_DIR}/${pod_name}.json"
}

# Process each pod configuration
for pod_config in "${pods[@]}"; do
    IFS=':' read -r pod_name pod_region pod_namespace <<< "$pod_config"
    process_pod "$pod_name" "$pod_region" "$pod_namespace"
done

# Clean up port forwarding
echo "Cleaning up..."
kill $PORT_FORWARD_PID

# Optionally clean up generated YAMLs
rm -rf "$YAML_DIR"
