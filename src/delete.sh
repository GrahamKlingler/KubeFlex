#!/bin/bash
kubectl delete configmap pod-selector-config -n monitor
kubectl delete -k manifests/
kubectl delete -f testpod.yml

kubectl label node desktop-worker2 REGION-
kubectl label node desktop-worker REGION-

kubectl delete namespace monitor
