#!/usr/bin/env bash
set -euo pipefail

IMAGE=cpp-test:local
NAMESPACE=test-namespace
MANIFEST="../../manifests/testpod.yml"
SERVICE_NS=monitor
MIGRATE_SVC=python-migrate-service
SRC_NODE=kind-worker
TGT_NODE=kind-worker2
POD_NAME=test-pod

here=$(cd "$(dirname "$0")" && pwd)
cd "$here"

echo "Building Docker image $IMAGE..."
docker build -t $IMAGE .

echo "Loading image into kind cluster..."
kind load docker-image $IMAGE

echo "Creating namespace $NAMESPACE if needed..."
kubectl get ns $NAMESPACE >/dev/null 2>&1 || kubectl create ns $NAMESPACE

echo "Applying pod manifest..."
kubectl apply -f $MANIFEST -n $NAMESPACE

echo "Waiting for pod to be running (120s timeout)..."
kubectl wait --for=condition=Ready pod/$POD_NAME -n $NAMESPACE --timeout=120s || true

echo "Tailing logs to /tmp/${POD_NAME}.log"
kubectl logs -n $NAMESPACE -f pod/$POD_NAME > /tmp/${POD_NAME}.log 2>&1 &
TAIL_PID=$!

echo "Port-forwarding migration service ($MIGRATE_SVC) to localhost:8000"
kubectl port-forward -n $SERVICE_NS svc/$MIGRATE_SVC 8000:8000 >/dev/null 2>&1 &
PF_PID=$!
sleep 1

echo "Requesting migration from $SRC_NODE to $TGT_NODE..."
payload=$(cat <<JSON
{
	"namespace": "$NAMESPACE",
	"pod": "$POD_NAME",
	"source_node": "$SRC_NODE",
	"target_node": "$TGT_NODE",
	"delete_original": true,
	"debug": true
}
JSON
)

echo "Migration request payload: $payload"
resp=$(curl -s -X POST -H "Content-Type: application/json" -d "$payload" http://127.0.0.1:8000/live-migrate || true)
echo "Migration service response: $resp"

echo "Cleaning up port-forward and log tail..."
kill $PF_PID >/dev/null 2>&1 || true
kill $TAIL_PID >/dev/null 2>&1 || true

echo "Listing pods in $NAMESPACE to find target pod(s):"
kubectl get pods -n $NAMESPACE
echo "You can view logs of the (new) pod with:"
echo "  kubectl logs -n $NAMESPACE -f <target-pod-name>"

echo "Run finished."