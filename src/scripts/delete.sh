#!/bin/bash
kubectl delete configmap pod-selector-config -n monitor
kubectl delete -k manifests/
kubectl delete namespace monitor

kubectl label node desktop-worker2 REGION-
kubectl label node desktop-worker REGION-