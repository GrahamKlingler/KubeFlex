#!/bin/bash

# Check if thread count argument is provided
if [ -z "$1" ]; then
    echo "Error: Thread count argument is required"
    echo "Usage: $0 <thread_count>"
    exit 1
fi

THREAD_COUNT=$1

# Base URL for the migration service
MIGRATION_URL="http://python-migrate-service.monitor.svc.cluster.local:8000/migrate"

# Namespace to use
NAMESPACE="foo"

# Source and target nodes
SOURCE_NODE="kind-worker"
TARGET_NODE="kind-worker2"

# Pod names with thread count
SOURCE_POD="benchmark-pod-${THREAD_COUNT}"
TARGET_POD="${SOURCE_POD}-migrated"

echo "Running migration for ${SOURCE_POD}..."

# Verify source pod exists
if ! kubectl get pod ${SOURCE_POD} -n ${NAMESPACE} &>/dev/null; then
    echo "Error: Source pod ${SOURCE_POD} not found in namespace ${NAMESPACE}"
    exit 1
fi

# Make the POST request
curl -X POST "${MIGRATION_URL}" \
    -H "Content-Type: application/json" \
    -d "{
        \"namespace\": \"${NAMESPACE}\",
        \"pod\": \"${SOURCE_POD}\",
        \"target_node\": \"${TARGET_NODE}\",
        \"target_pod\": \"${TARGET_POD}\",
        \"delete_original\": true,
        \"debug\": false
    }"

# Check if the request was successful
if [ $? -eq 0 ]; then
    echo -e "\nMigration request sent successfully!"
    
    # Wait for migration to complete (you might want to adjust this timeout)
    echo "Waiting for migration to complete..."
    sleep 10
    
    # Clean up the migrated pod if it exists
    if kubectl get pod ${TARGET_POD} -n ${NAMESPACE} &>/dev/null; then
        echo "Cleaning up migrated pod..."
        kubectl delete pod ${TARGET_POD} -n ${NAMESPACE} --force --grace-period=0
        echo "Migrated pod ${TARGET_POD} deleted"
        sleep 10
    fi
else
    echo -e "\nError: Failed to send migration request"
    exit 1
fi 