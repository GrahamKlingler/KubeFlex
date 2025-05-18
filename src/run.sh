#!/bin/bash

IFS=',' read -ra PAIRS <<< "$1"
SELECTOR=""
APPLY_STORAGE=false

# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --all)
            APPLY_STORAGE=true
            shift
            ;;
    esac
done

# If $SELECTOR is not set (empty or null), assign a default value
if [ $# -eq 0 ]; then
  SELECTOR="io.kubernetes.pod.namespace=foo"
  echo "SELECTOR not set. Assigning default value: namespace=foo"
else
  for PAIR in "${PAIRS[@]}"; do
        if [ -n "$SELECTOR" ]; then
            SELECTOR="$SELECTOR,"
        fi
        KEY=${PAIR%%=*}
        VALUE=${PAIR#*=}
        
        case $KEY in
            namespace) SELECTOR="${SELECTOR}io.kubernetes.pod.namespace=$VALUE" ;;
            name) SELECTOR="${SELECTOR}io.kubernetes.pod.name=$VALUE" ;;
            container) SELECTOR="${SELECTOR}io.kubernetes.container.name=$VALUE" ;;
            *) echo "Invalid key: $KEY. Must be namespace, name, or container"; exit 1 ;;
        esac
    done
fi

# Create the namespace
# kubectl create namespace monitor

kubectl label node desktop-worker REGION=TEN
kubectl label node desktop-worker2 REGION=NE

# Generate the ConfigMap based on the selector
kubectl create configmap pod-selector-config -n monitor --from-literal=POD_SELECTOR="$SELECTOR" --dry-run=client -o yaml | kubectl apply -f -

# Apply manifests
kubectl apply -k manifests/ --validate=false

# Apply storage manifest if --all flag is set
if [ "$APPLY_STORAGE" = true ]; then
    echo "Applying storage manifest..."
    kubectl apply -f manifests/storage.yml --validate=false
fi

