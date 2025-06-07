#!/bin/bash

# Get the pod name from the monitor namespace
POD_NAME=$(kubectl get pod -n monitor -l name=controller -o jsonpath="{.items[0].metadata.name}")

if [ -z "$POD_NAME" ]; then
    echo "Error: Could not find controller pod in monitor namespace"
    exit 1
fi

echo "Found pod: $POD_NAME"

# Execute the migration script in the pod for each thread count
for thread_count in {1..32}; do
    echo "Running benchmark with $thread_count threads"
    
    # Create a temporary manifest with the current thread count
    export STRESS_THREAD_COUNT=$thread_count
    envsubst < ../src/manifests/benchmark-pod.yml > benchmark-pod-temp.yml
    
    # Alter the name on the manifest to include the thread count
    sed -i "s/benchmark-pod/benchmark-pod-${thread_count}/g" benchmark-pod-temp.yml

    # Delete any existing pods
    kubectl delete -f benchmark-pod-temp.yml
    kubectl delete pod benchmark-pod-${thread_count}-migrated -n foo

    sleep 10
    
    # Apply the new configuration
    kubectl apply -f benchmark-pod-temp.yml

    # Wait for the pod to be ready
    echo "Waiting for benchmark pod to be ready..."
    kubectl wait --for=condition=Ready pod/benchmark-pod-${thread_count} -n foo --timeout=60s
    
    # Execute the migration with thread count argument
    kubectl exec -n monitor $POD_NAME -c python-migrate -it -- /bin/sh -c "./migrate_pod.sh ${thread_count}"
    
    echo "Benchmark with $thread_count threads completed"
    
    # Clean up temporary file
    rm benchmark-pod-temp.yml
done