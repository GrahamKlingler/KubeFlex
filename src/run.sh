#!/bin/bash

IFS=',' read -ra PAIRS <<< "$1"
SELECTOR=""

# If $SELECTOR is not set (empty or null), assign a default value
if [ $# -eq 0 ]; then
  SELECTOR="io.kubernetes.pod.namespace=default"
  echo "SELECTOR not set. Assigning default value: namespace=default"
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
kubectl create namespace monitor

# Generate the ConfigMap based on the selector
kubectl create configmap pod-selector-config -n monitor --from-literal=POD_SELECTOR="$SELECTOR" --dry-run=client -o yaml | kubectl apply -f -

# Apply manifests
kubectl apply -k manifests/ --validate=false

