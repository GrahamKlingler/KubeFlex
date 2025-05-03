#!/usr/bin/env python3
"""
Simple Kubernetes Pod Migration Script

This script creates a new pod on a target node with the same configuration
as an existing pod, with special handling for control plane nodes.
It doesn't use checkpointing, making it much simpler and more reliable.
"""

import argparse
import sys
import time
import json
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import uvicorn
import logging

from kubernetes import client, config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_k8s_config():
    """Load Kubernetes configuration from default location or service account."""
    try:
        # Try loading from default kubeconfig file
        config.load_kube_config()
        logger.info("Loaded Kubernetes config from kubeconfig file")
    except Exception:
        # Fallback to in-cluster config (when running in a pod)
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    
    return client.CoreV1Api()

def get_node_info(api: client.CoreV1Api, node_name: str) -> Dict[str, Any]:
    """Get information about a node, including taints and labels."""
    try:
        node = api.read_node(name=node_name)
        
        # Extract taints
        taints = []
        if node.spec.taints:
            taints = [{
                "key": taint.key,
                "value": taint.value,
                "effect": taint.effect
            } for taint in node.spec.taints]
        
        # Check if this is a control plane node
        is_control_plane = False
        if node.metadata.labels:
            for key in node.metadata.labels:
                if "master" in key or "control-plane" in key:
                    is_control_plane = True
                    break
        
        return {
            "name": node.metadata.name,
            "taints": taints,
            "labels": node.metadata.labels,
            "is_control_plane": is_control_plane
        }
    except client.rest.ApiException as e:
        logger.error(f"Error getting node information: {e}")
        raise

def get_pod_definition(api: client.CoreV1Api, namespace: str, pod_name: str) -> Dict[str, Any]:
    """Get the pod definition as a dictionary that can be modified."""
    try:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        # Convert to dict for easier manipulation
        return client.ApiClient().sanitize_for_serialization(pod)
    except client.rest.ApiException as e:
        logger.error(f"Error getting pod definition: {e}")
        raise

def create_pod_clone_for_node(
    api: client.CoreV1Api,
    namespace: str, 
    original_pod_name: str,
    target_node: str
) -> str:
    """Create a new pod on the target node based on an existing pod's configuration."""
    # Get the original pod definition
    pod_def = get_pod_definition(api, namespace, original_pod_name)
    
    # Get target node information (for taints)
    node_info = get_node_info(api, target_node)
    logger.info(f"Target node: {node_info['name']}, is control plane: {node_info['is_control_plane']}")
    
    # Create a new name for the pod
    new_pod_name = f"{original_pod_name}-migrated-{int(time.time())}"
    
    # Modify the pod definition for the new node
    pod_def["metadata"]["name"] = new_pod_name
    
    # Remove fields that should not be included in a new pod creation
    if "status" in pod_def:
        del pod_def["status"]
    
    if "metadata" in pod_def:
        for field in ["creationTimestamp", "resourceVersion", "uid", "selfLink", "managedFields"]:
            if field in pod_def["metadata"]:
                del pod_def["metadata"][field]

    # Add annotation to track migration
    if "annotations" not in pod_def["metadata"]:
        pod_def["metadata"]["annotations"] = {}
    
    pod_def["metadata"]["annotations"]["migrated-from-pod"] = original_pod_name
    pod_def["metadata"]["annotations"]["migration-timestamp"] = str(int(time.time()))
    
    # Set the node selector to target the specific node
    if "spec" in pod_def:
        pod_def["spec"]["nodeName"] = target_node
        
        # Remove fields that could interfere with scheduling
        for field in ["nodeSelector", "schedulerName", "priority", "priorityClassName"]:
            if field in pod_def["spec"]:
                del pod_def["spec"][field]
    
    # Add tolerations for control plane if needed
    if node_info["is_control_plane"]:
        logger.info("Adding control plane tolerations")
        
        # Create tolerations for control plane taints
        control_plane_tolerations = []
        
        # Add specific tolerations for any taints found on the node
        for taint in node_info["taints"]:
            control_plane_tolerations.append({
                "key": taint["key"],
                "operator": "Exists",
                "effect": taint["effect"]
            })
        
        # If no taints found, add common control plane taints
        if not control_plane_tolerations:
            control_plane_tolerations = [
                {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists",
                    "effect": "NoSchedule"
                },
                {
                    "key": "node-role.kubernetes.io/master",
                    "operator": "Exists",
                    "effect": "NoSchedule"
                }
            ]
        
        # Add tolerations to pod spec
        if "tolerations" not in pod_def["spec"]:
            pod_def["spec"]["tolerations"] = []
        
        # Add our control plane tolerations
        for toleration in control_plane_tolerations:
            if toleration not in pod_def["spec"]["tolerations"]:
                pod_def["spec"]["tolerations"].append(toleration)
    
    # Create the new pod
    try:
        logger.info(f"Creating new pod {new_pod_name} on node {target_node}")
        api.create_namespaced_pod(namespace=namespace, body=pod_def)
        logger.info(f"Pod {new_pod_name} created")
        return new_pod_name
    except client.rest.ApiException as e:
        logger.error(f"Error creating pod: {e}")
        # Print more details if available
        if hasattr(e, 'body') and e.body:
            try:
                body = json.loads(e.body)
                if 'message' in body:
                    logger.error(f"API error message: {body['message']}")
            except:
                logger.error(f"API error body: {e.body}")
        raise

def wait_for_pod_running(api: client.CoreV1Api, namespace: str, pod_name: str, timeout_seconds=300):
    """Wait for a pod to reach Running state."""
    logger.info(f"Waiting for pod {pod_name} to start running")
    
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
            logger.info(f"Pod status: {pod.status.phase}")
            
            if pod.status.phase == "Running":
                logger.info(f"Pod {pod_name} is now running")

                return True
            
            if pod.status.phase == "Failed" or pod.status.phase == "Unknown":
                logger.error(f"Pod entered {pod.status.phase} state")
                
                # Get pod events for troubleshooting
                try:
                    events = api.list_namespaced_event(
                        namespace=namespace,
                        field_selector=f"involvedObject.name={pod_name}"
                    )
                    for event in events.items:
                        logger.error(f"Pod event: {event.reason} - {event.message}")
                except Exception as e:
                    logger.error(f"Could not get pod events: {e}")
                
                return False
            
            # Check if there are scheduling issues
            if pod.status.conditions:
                for condition in pod.status.conditions:
                    if condition.type == "PodScheduled" and condition.status == "False":
                        logger.warning(f"Scheduling issue: {condition.message}")
            
            time.sleep(5)
            
        except client.rest.ApiException as e:
            logger.error(f"Error checking pod status: {e}")
            time.sleep(5)
    
    logger.error(f"Timeout waiting for pod {pod_name} to start")
    return False

def migrate_pod(
    namespace: str,
    pod_name: str, 
    target_node: str,
    delete_original: bool = True,
    debug: bool = False
):
    """
    Migrate a pod to another node by creating a clone with the same configuration.
    
    Args:
        namespace: Kubernetes namespace
        pod_name: Name of the pod to migrate
        target_node: Target node for the new pod
        delete_original: Whether to delete the original pod if migration succeeds
        debug: Enable debug logging
    """
    if debug:
        logger.setLevel(logging.DEBUG)
    
    # Load Kubernetes configuration
    api = load_k8s_config()
    
    # Verify pod exists
    try:
        original_pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        original_node = original_pod.spec.node_name
        logger.info(f"Pod {pod_name} is currently on node {original_node}")
        
        # Check if already on target node
        if original_node == target_node:
            logger.info(f"Pod is already on target node {target_node}. No migration needed.")
            return pod_name
            
    except client.rest.ApiException as e:
        logger.error(f"Pod {pod_name} not found: {e}")
        return None
    
    # Create clone on target node
    new_pod_name = create_pod_clone_for_node(api, namespace, pod_name, target_node)
    
    # Wait for the new pod to be running
    if wait_for_pod_running(api, namespace, new_pod_name):
        logger.info(f"Successfully migrated pod to {new_pod_name} on node {target_node}")
        
        # Delete original pod if requested
        if delete_original:
            try:
                logger.info(f"Deleting original pod {pod_name}")
                api.delete_namespaced_pod(
                    name=pod_name,
                    namespace=namespace
                )
                logger.info(f"Original pod {pod_name} deleted")
            except client.rest.ApiException as e:
                logger.error(f"Error deleting original pod: {e}")
        
        return new_pod_name
    else:
        logger.error("Migration failed - new pod did not reach Running state")
        return None
    
# Define input model
class MigrateRequest(BaseModel):
    namespace: str
    pod: str
    target_node: str
    delete_original: bool = True
    debug: bool = False

# FastAPI app
app = FastAPI()

@app.post("/migrate")
async def migrate(req: MigrateRequest):
    try:
        result = migrate_pod(
            namespace=req.namespace,
            pod_name=req.pod,
            target_node=req.target_node,
            delete_original=req.delete_original,
            debug=req.debug
        )
        if result:
            logger.info(f"Migration successful. New pod name: {result}")
            return {"status": "success", "new_pod_name": result}
        else:
            logger.error("Migration failed")
            raise HTTPException(status_code=500, detail="Migration failed")
    except Exception as e:
        logger.exception("Exception during migration")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

# def main():
#     """Main entry point for the script."""
#     parser = argparse.ArgumentParser(description="Migrate a Kubernetes pod to another node")
#     parser.add_argument("-n", "--namespace", required=True, help="Namespace of the pod")
#     parser.add_argument("-p", "--pod", required=True, help="Name of the pod to migrate")
#     parser.add_argument("-t", "--target-node", required=True, help="Target node to migrate to")
#     parser.add_argument("-d", "--delete-original", default=True, action="store_true", help="Delete the original pod if migration succeeds")
#     parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
#     args = parser.parse_args()
    
#     try:
#         result = migrate_pod(
#             namespace=args.namespace,
#             pod_name=args.pod,
#             target_node=args.target_node,
#             delete_original=args.delete_original,
#             debug=args.debug
#         )
        
#         if result:
#             logger.info(f"Migration successful. New pod name: {result}")
#             return 0
#         else:
#             logger.error("Migration failed")
#             return 1
#     except Exception as e:
#         logger.error(f"Error during migration: {e}")
#         return 1

# if __name__ == "__main__":
#     sys.exit(main())