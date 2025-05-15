#!/bin/bash
kubectl delete configmap pod-selector-config -n monitor --force
kubectl delete -k manifests/ --force
kubectl delete -f testpod.yml --force

kubectl label node desktop-worker2 REGION-
kubectl label node desktop-worker REGION-