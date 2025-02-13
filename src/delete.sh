#!/bin/bash
kubectl delete configmap pod-selector-config -n cadvisor
kubectl delete -k manifests/
kubectl delete namespace cadvisor