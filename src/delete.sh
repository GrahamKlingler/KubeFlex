#!/bin/bash
# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --all)
            APPLY_STORAGE=true
            shift
            ;;
        --cluster)
            APPLY_CLUSTER=true
            shift
            ;;
    esac
done

kubectl delete configmap pod-selector-config -n monitor
kubectl delete -k manifests/
# kubectl delete -f testpod.yml

# Apply storage manifest if --all flag is set
if [ "$APPLY_STORAGE" = true ]; then
    echo "Deleting storage manifest..."
    kubectl delete -f manifests/storage.yml
fi

kubectl label node kind-worker2 REGION-
kubectl label node kind-worker REGION-

# Delete kind cluster if --cluster flag is set
if [ "$APPLY_CLUSTER" = true ]; then
    echo "Deleting kind cluster..."
    kind delete cluster
    rm -f kubeconfig
fi

# kubectl delete namespace monitor
