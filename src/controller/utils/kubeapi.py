from datetime import datetime, timedelta
import requests
import json
import time
import psycopg2
import sys
import logging

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from prettytable import PrettyTable
from kubernetes.watch import Watch

# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load Kubernetes configuration (kubeconfig or in-cluster)
def load_kubernetes_config():
    """
    Load Kubernetes configuration from default location or service account
    """
    try:
        # Try loading from kube config file first
        config.load_kube_config()
        logger.info("Using local Kubernetes configuration")
    except Exception:
        # If that fails, try loading from service account
        try:
            config.load_incluster_config()
            logger.info("Using in-cluster Kubernetes configuration")
        except Exception as e:
            logger.error(f"Error loading Kubernetes configuration: {e}")
            sys.exit(1)

# Get the status of a pod
def get_pod_status(pod):
    """Get the status of a pod"""
    if pod.status.phase:
        if pod.status.reason:
            return f"{pod.status.phase}: {pod.status.reason}"
        return pod.status.phase
    
    return "Unknown"

# List all resources in a namespace with k8s library
def list_resources(namespace, include_system=False) -> list:
    """
    List all resources in the specified namespace
    """
    load_kubernetes_config()
    
    # Create API clients
    core_v1 = client.CoreV1Api()
    batch_v1 = client.BatchV1Api()
    # apps_v1 = client.AppsV1Api()
    # networking_v1 = client.NetworkingV1Api()
    
    all_resources = []
    
    # Get pods
    try:
        pods = core_v1.list_namespaced_pod(namespace=namespace)
        logger.info(f"Found {len(pods.items)} pods in namespace {namespace}")
        for pod in pods.items:
            if not include_system and pod.metadata.name.startswith('system-'):
                continue
                
            resource_data = {
                'kind': 'Pod',
                'name': pod.metadata.name,
                'labels': pod.metadata.labels or {},
                'annotations': pod.metadata.annotations or {},
                'state': get_pod_status(pod),
                'age': pod.metadata.creation_timestamp,
            }
            all_resources.append(resource_data)
    except ApiException as e:
        logger.info(f"Error listing pods: {e}")
    
    # Get jobs
    try:
        jobs = batch_v1.list_namespaced_job(namespace=namespace)
        for job in jobs.items:
            if not include_system and job.metadata.name.startswith('system-'):
                continue
                
            status = "Unknown"
            if job.status.succeeded:
                status = "Succeeded"
            elif job.status.active:
                status = "Active"
            elif job.status.failed:
                status = "Failed"
                
            resource_data = {
                'kind': 'Job',
                'name': job.metadata.name,
                'labels': job.metadata.labels or {},
                'annotations': job.metadata.annotations or {},
                'state': status,
                'age': job.metadata.creation_timestamp,
            }
            all_resources.append(resource_data)
    except ApiException as e:
        logger.info(f"Error listing jobs: {e}")
    
    return all_resources

# List all nodes in the cluster, including their labels and annotations
def list_nodes_with_labels_annotations() -> list:
    """
    List all nodes in the cluster, including their labels and annotations.
    Returns a list of dicts: {'name': ..., 'labels': ..., 'annotations': ...}
    """
    load_kubernetes_config()
    core_v1 = client.CoreV1Api()
    nodes_info = []
    try:
        nodes = core_v1.list_node()
        for node in nodes.items:
            node_info = {
                'name': node.metadata.name,
                'labels': node.metadata.labels or {},
                'annotations': node.metadata.annotations or {}
            }
            nodes_info.append(node_info)
    except ApiException as e:
        logger.error(f"Error listing nodes: {e}")
    return nodes_info

def watch_pod_events(namespace: str, name: str = None, labels: dict = None, annotations: dict = None, timeout_seconds: int = None):
    """
    Watch for pod events in a specific namespace with optional filters for name, labels, and annotations.
    
    Args:
        namespace (str): The namespace to watch
        name (str, optional): Specific pod name to watch for
        labels (dict, optional): Dictionary of labels to match
        annotations (dict, optional): Dictionary of annotations to match
        timeout_seconds (int, optional): How long to watch for events (None for indefinite)
    
    Returns:
        None, but prints events as they occur
    """
    load_kubernetes_config()
    core_v1 = client.CoreV1Api()
    
    # Create a watch object
    w = Watch()
    
    # Start time for timeout calculation
    start_time = datetime.now()
    
    try:
        # Watch for pod events
        for event in w.stream(core_v1.list_namespaced_pod,
                            namespace=namespace,
                            timeout_seconds=timeout_seconds):
            pod = event['object']
            event_type = event['type']
            
            # Skip if name doesn't match (if specified)
            if name and pod.metadata.name != name:
                continue
                
            # Skip if labels don't match (if specified)
            if labels:
                pod_labels = pod.metadata.labels or {}
                if not all(pod_labels.get(k) == v for k, v in labels.items()):
                    continue
                    
            # Skip if annotations don't match (if specified)
            if annotations:
                pod_annotations = pod.metadata.annotations or {}
                if not all(pod_annotations.get(k) == v for k, v in annotations.items()):
                    continue
            
            # Calculate time since start
            elapsed = datetime.now() - start_time
            
            # Print event details
            print(f"[{elapsed}] {event_type} Pod: {pod.metadata.name}")
            print(f"  Status: {get_pod_status(pod)}")
            if pod.metadata.labels:
                print(f"  Labels: {pod.metadata.labels}")
            if pod.metadata.annotations:
                print(f"  Annotations: {pod.metadata.annotations}")
            print("-" * 50)
            
    except Exception as e:
        logger.error(f"Error watching pod events: {e}")
        raise