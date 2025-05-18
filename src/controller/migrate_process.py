#!/usr/bin/env python3
"""
Kubernetes Pod Migration Script with CRIU Checkpoint/Restore

This script migrates pods between nodes using CRIU to freeze and restore
the exact state of containers, preserving all process states, memory, and CPU state.
"""

import argparse
import sys
import time
import json
from typing import Dict, Any, List
import subprocess
import os
import tempfile
import shutil
import tarfile
import base64

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import uvicorn
import logging

from kubernetes import client, config
from kubeapi import *
from datetime import datetime, timedelta
import requests
import json
import psycopg2
import sys
import logging

from kubernetes.client.rest import ApiException
from prettytable import PrettyTable
from kubernetes.watch import Watch

# Set up logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

def load_k8s_config():
    """Load Kubernetes configuration from default location or service account."""
    try:
        # Try loading from default kubeconfig file
        config.load_kube_config()
        logger.info("[CONFIG] Successfully loaded Kubernetes config from kubeconfig file")
    except Exception:
        # Fallback to in-cluster config (when running in a pod)
        config.load_incluster_config()
        logger.info("[CONFIG] Successfully loaded in-cluster Kubernetes config")
    
    return client.CoreV1Api()

def get_node_info(api: client.CoreV1Api, node_name: str) -> Dict[str, Any]:
    """Get information about a node, including taints and labels."""
    try:
        logger.info(f"[NODE] Fetching information for node: {node_name}")
        node = api.read_node(name=node_name)
        
        # Extract taints
        taints = []
        if node.spec.taints:
            taints = [{
                "key": taint.key,
                "value": taint.value,
                "effect": taint.effect
            } for taint in node.spec.taints]
            logger.info(f"[NODE] Found {len(taints)} taints on node {node_name}")
        
        # Check if this is a control plane node
        is_control_plane = False
        if node.metadata.labels:
            for key in node.metadata.labels:
                if "master" in key or "control-plane" in key:
                    is_control_plane = True
                    logger.info(f"[NODE] Node {node_name} is identified as a control plane node")
                    break
        
        return {
            "name": node.metadata.name,
            "taints": taints,
            "labels": node.metadata.labels,
            "is_control_plane": is_control_plane
        }
    except client.rest.ApiException as e:
        logger.error(f"[NODE] Error getting node information: {e}")
        raise

def get_pod_definition(api: client.CoreV1Api, namespace: str, pod_name: str) -> Dict[str, Any]:
    """Get the pod definition as a dictionary that can be modified."""
    try:
        logger.info(f"[POD] Fetching definition for pod: {pod_name} in namespace: {namespace}")
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        # Convert to dict for easier manipulation
        pod_def = client.ApiClient().sanitize_for_serialization(pod)
        logger.info(f"[POD] Successfully retrieved pod definition for {pod_name}")
        return pod_def
    except client.rest.ApiException as e:
        logger.error(f"[POD] Error getting pod definition: {e}")
        raise

def ensure_criu_installed(api: client.CoreV1Api, namespace: str, pod_name: str, container_name: str):
    """Ensure CRIU is installed in the target container."""
    try:
        logger.info(f"[CRIU] Checking CRIU installation in container {container_name}")
        
        # Check if CRIU is installed
        check_cmd = [
            "kubectl", "exec", pod_name,
            "-n", namespace,
            "-c", container_name,
            "--", "which", "criu"
        ]
        
        try:
            subprocess.run(check_cmd, check=True, capture_output=True)
            logger.info(f"[CRIU] CRIU is already installed in container {container_name}")
            return True
        except subprocess.CalledProcessError:
            logger.info(f"[CRIU] CRIU not found in container {container_name}")
            
            # Install CRIU in Debian container
            install_cmd = [
                "kubectl", "exec", pod_name,
                "-n", namespace,
                "-c", container_name,
                "--", "bash", "-c",
                "apt-get update && apt-get install -y criu && rm -rf /var/lib/apt/lists/*"
            ]
            
            try:
                subprocess.run(install_cmd, check=True)
                logger.info(f"[CRIU] Successfully installed CRIU in container {container_name}")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"[CRIU] Failed to install CRIU: {e}")
                return False
                
    except Exception as e:
        logger.error(f"[CRIU] Error ensuring CRIU installation: {e}")
        return False

def get_main_process_id(api: client.CoreV1Api, namespace: str, pod_name: str, container_name: str) -> str:
    """Get the main process ID of the container."""
    try:
        # First try to get the main process directly using pgrep
        pgrep_cmd = [
            "kubectl", "exec", pod_name,
            "-n", namespace,
            "-c", container_name,
            "--", "pgrep", "-f", "counter="
        ]
        
        try:
            pgrep_output = subprocess.run(pgrep_cmd, check=True, capture_output=True, text=True)
            if pgrep_output.stdout.strip():
                pid = pgrep_output.stdout.strip()
                logger.info(f"[PROCESS] Found main process with PID: {pid} using pgrep")
                return pid
        except subprocess.CalledProcessError:
            logger.info("[PROCESS] pgrep failed, falling back to /proc method")
        
        # Fallback to /proc method with memory-efficient approach
        ls_cmd = [
            "kubectl", "exec", pod_name,
            "-n", namespace,
            "-c", container_name,
            "--", "ls", "-1", "/proc"
        ]
        
        ls_output = subprocess.run(ls_cmd, check=True, capture_output=True, text=True)
        logger.info("[PROCESS] Successfully listed /proc directory")
        
        # Process PIDs in smaller batches to avoid memory issues
        batch_size = 10
        pids = []
        for line in ls_output.stdout.splitlines():
            if line.isdigit():
                pids.append(line)
                if len(pids) >= batch_size:
                    # Process this batch
                    for pid in pids:
                        try:
                            # Check if process is still running
                            stat_cmd = [
                                "kubectl", "exec", pod_name,
                                "-n", namespace,
                                "-c", container_name,
                                "--", "test", "-e", f"/proc/{pid}/stat"
                            ]
                            subprocess.run(stat_cmd, check=True, capture_output=True)
                            
                            # Read cmdline
                            cmdline_cmd = [
                                "kubectl", "exec", pod_name,
                                "-n", namespace,
                                "-c", container_name,
                                "--", "cat", f"/proc/{pid}/cmdline"
                            ]
                            cmdline_output = subprocess.run(cmdline_cmd, check=True, capture_output=True, text=True)
                            cmdline = cmdline_output.stdout
                            
                            if "counter=" in cmdline or "bash" in cmdline:
                                logger.info(f"[PROCESS] Found main process with PID: {pid}")
                                return pid
                        except subprocess.CalledProcessError:
                            continue
                    # Clear the batch
                    pids = []
        
        # Process any remaining PIDs
        for pid in pids:
            try:
                stat_cmd = [
                    "kubectl", "exec", pod_name,
                    "-n", namespace,
                    "-c", container_name,
                    "--", "test", "-e", f"/proc/{pid}/stat"
                ]
                subprocess.run(stat_cmd, check=True, capture_output=True)
                
                cmdline_cmd = [
                    "kubectl", "exec", pod_name,
                    "-n", namespace,
                    "-c", container_name,
                    "--", "cat", f"/proc/{pid}/cmdline"
                ]
                cmdline_output = subprocess.run(cmdline_cmd, check=True, capture_output=True, text=True)
                cmdline = cmdline_output.stdout
                
                if "counter=" in cmdline or "bash" in cmdline:
                    logger.info(f"[PROCESS] Found main process with PID: {pid}")
                    return pid
            except subprocess.CalledProcessError:
                continue
        
        # If we still haven't found the process, try PID 1
        logger.info("[PROCESS] No specific process found, using PID 1")
        return "1"
        
    except subprocess.CalledProcessError as e:
        logger.error(f"[PROCESS] Failed to get process list: {e}")
        # Fallback to PID 1
        logger.info("[PROCESS] Falling back to PID 1")
        return "1"
    except Exception as e:
        logger.error(f"[PROCESS] Unexpected error: {e}")
        return "1"

def create_checkpoint(api: client.CoreV1Api, namespace: str, pod_name: str) -> str:
    """Create a CRIU checkpoint of the pod and return the checkpoint path."""
    checkpoint_dir = "/tmp/checkpoint"
    checkpoint_archive = f"{checkpoint_dir}.tar.gz"
    
    try:
        logger.info(f"[CHECKPOINT] Creating checkpoint for pod {pod_name}")
        
        # Clean up any existing checkpoint files
        try:
            if os.path.exists(checkpoint_archive):
                os.remove(checkpoint_archive)
                logger.info(f"[CHECKPOINT] Removed existing checkpoint archive: {checkpoint_archive}")
        except Exception as e:
            logger.warning(f"[CHECKPOINT] Could not remove existing checkpoint archive: {e}")
        
        # Create fresh checkpoint directory
        try:
            if os.path.exists(checkpoint_dir):
                # Try to unmount if it's a mount point
                try:
                    subprocess.run(["umount", checkpoint_dir], check=False)
                except Exception:
                    pass
                # Remove directory contents but not the directory itself
                for item in os.listdir(checkpoint_dir):
                    item_path = os.path.join(checkpoint_dir, item)
                    try:
                        if os.path.isfile(item_path):
                            os.unlink(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    except Exception as e:
                        logger.warning(f"[CHECKPOINT] Could not remove {item_path}: {e}")
            else:
                os.makedirs(checkpoint_dir)
            logger.info(f"[CHECKPOINT] Prepared checkpoint directory: {checkpoint_dir}")
        except Exception as e:
            logger.error(f"[CHECKPOINT] Failed to prepare checkpoint directory: {e}")
            raise
        
        # Get pod information
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # Create checkpoint for each container
        for container in pod.spec.containers:
            container_name = container.name
            logger.info(f"[CHECKPOINT] Creating checkpoint for container {container_name}")
            
            # Ensure CRIU is installed
            if not ensure_criu_installed(api, namespace, pod_name, container_name):
                raise Exception(f"Failed to ensure CRIU installation in container {container_name}")
            
            logger.info(f"[CHECKPOINT] Using checkpoint directory: {checkpoint_dir}")
            
            # Get the main process ID
            main_pid = get_main_process_id(api, namespace, pod_name, container_name)
            logger.info(f"[CHECKPOINT] Using process ID: {main_pid}")
            
            # Execute CRIU dump command with additional options
            criu_cmd = [
                "kubectl", "exec", pod_name,
                "-n", namespace,
                "-c", container_name,
                "--", "criu", "dump",
                "-D", checkpoint_dir,
                "-t", main_pid,
                "--leave-running",  # Keep the process running after checkpoint
                "--shell-job",  # Required for shell-based processes
                "--tcp-established",  # Handle established TCP connections
                "--ext-mount-map", "/proc",  # Map /proc
                "--ext-mount-map", "/sys",  # Map /sys
                "--ext-mount-map", "/dev",  # Map /dev
                "--ext-mount-map", "/var/run",  # Map /var/run
                "--ext-mount-map", "/sys/fs/cgroup",  # Map cgroup
                "--log-file", "/tmp/criu.log",  # Log file for debugging
                "--log-level", "4"  # Verbose logging
            ]
            
            try:
                subprocess.run(criu_cmd, check=True)
                logger.info(f"[CHECKPOINT] Successfully created checkpoint for container {container_name}")
                
                # Create a tar archive of the checkpoint
                with tarfile.open(checkpoint_archive, "w:gz") as tar:
                    tar.add(checkpoint_dir, arcname=os.path.basename(checkpoint_dir))
                
                logger.info(f"[CHECKPOINT] Created checkpoint archive: {checkpoint_archive}")
                return checkpoint_archive
                
            except subprocess.CalledProcessError as e:
                logger.error(f"[CHECKPOINT] Failed to create checkpoint for container {container_name}: {e}")
                # Try to get CRIU log for debugging
                try:
                    log_cmd = [
                        "kubectl", "exec", pod_name,
                        "-n", namespace,
                        "-c", container_name,
                        "--", "cat", "/tmp/criu.log"
                    ]
                    log_output = subprocess.run(log_cmd, check=True, capture_output=True, text=True)
                    logger.error(f"[CHECKPOINT] CRIU log:\n{log_output.stdout}")
                except Exception as log_error:
                    logger.error(f"[CHECKPOINT] Could not get CRIU log: {log_error}")
                raise
        
    except Exception as e:
        logger.error(f"[CHECKPOINT] Error creating checkpoint: {e}")
        # Cleanup on failure
        try:
            if os.path.exists(checkpoint_archive):
                os.remove(checkpoint_archive)
        except Exception as cleanup_error:
            logger.warning(f"[CHECKPOINT] Could not remove checkpoint archive during cleanup: {cleanup_error}")
        raise
    finally:
        # Always try to clean up the checkpoint directory
        try:
            if os.path.exists(checkpoint_dir):
                # Try to unmount if it's a mount point
                try:
                    subprocess.run(["umount", checkpoint_dir], check=False)
                except Exception:
                    pass
                # Remove directory contents but not the directory itself
                for item in os.listdir(checkpoint_dir):
                    item_path = os.path.join(checkpoint_dir, item)
                    try:
                        if os.path.isfile(item_path):
                            os.unlink(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    except Exception as e:
                        logger.warning(f"[CHECKPOINT] Could not remove {item_path} during cleanup: {e}")
        except Exception as e:
            logger.warning(f"[CHECKPOINT] Error during final cleanup: {e}")

def restore_checkpoint(api: client.CoreV1Api, namespace: str, pod_name: str, checkpoint_path: str):
    """Restore a pod from a CRIU checkpoint."""
    try:
        logger.info(f"[RESTORE] Restoring pod {pod_name} from checkpoint")
        
        # Extract checkpoint archive
        checkpoint_dir = tempfile.mkdtemp(prefix=f"restore-{pod_name}-")
        with tarfile.open(checkpoint_path, "r:gz") as tar:
            tar.extractall(path=checkpoint_dir)
        
        # Get pod information
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # Restore each container
        for container in pod.spec.containers:
            container_name = container.name
            logger.info(f"[RESTORE] Restoring container {container_name}")
            
            container_checkpoint_dir = os.path.join(checkpoint_dir, container_name)
            
            # Copy checkpoint files to container
            copy_cmd = [
                "kubectl", "cp",
                container_checkpoint_dir,
                f"{namespace}/{pod_name}:/tmp/checkpoint"
            ]
            subprocess.run(copy_cmd, check=True)
            
            # Execute CRIU restore command
            criu_cmd = [
                "kubectl", "exec", pod_name,
                "-n", namespace,
                "-c", container_name,
                "--", "criu", "restore",
                "-D", "/tmp/checkpoint",
                "--restore-detached"  # Restore in detached mode
            ]
            
            try:
                subprocess.run(criu_cmd, check=True)
                logger.info(f"[RESTORE] Successfully restored container {container_name}")
            except subprocess.CalledProcessError as e:
                logger.error(f"[RESTORE] Failed to restore container {container_name}: {e}")
                raise
        
        # Cleanup
        shutil.rmtree(checkpoint_dir)
        logger.info(f"[RESTORE] Successfully restored pod {pod_name}")
        
    except Exception as e:
        logger.error(f"[RESTORE] Error restoring checkpoint: {e}")
        raise

def create_pod_clone_for_node(
    api: client.CoreV1Api,
    namespace: str, 
    original_pod_name: str,
    target_node: str,
    new_pod_name: str = None
) -> str:
    """Create a new pod on the target node based on an existing pod's configuration."""
    logger.info(f"[MIGRATION] Starting pod clone creation process")
    logger.info(f"[MIGRATION] Original pod: {original_pod_name}, Target node: {target_node}")
    
    # Create checkpoint of original pod
    checkpoint_path = create_checkpoint(api, namespace, original_pod_name)
    logger.info(f"[MIGRATION] Created checkpoint at {checkpoint_path}")
    
    # Get the original pod definition
    pod_def = get_pod_definition(api, namespace, original_pod_name)
    
    # Get target node information (for taints)
    node_info = get_node_info(api, target_node)
    logger.info(f"[MIGRATION] Target node info - Name: {node_info['name']}, Control plane: {node_info['is_control_plane']}")
    
    # Generate a new pod name if not provided
    if new_pod_name is None:
        new_pod_name = f"{original_pod_name}-migrated-{int(time.time())}"
        logger.info(f"[MIGRATION] Generated new pod name: {new_pod_name}")

    # Modify the pod definition for the new node
    pod_def["metadata"]["name"] = new_pod_name
    
    # Remove fields that should not be included in a new pod creation
    if "status" in pod_def:
        del pod_def["status"]
        logger.info("[MIGRATION] Removed status field from pod definition")
    
    if "metadata" in pod_def:
        for field in ["creationTimestamp", "resourceVersion", "uid", "selfLink", "managedFields"]:
            if field in pod_def["metadata"]:
                del pod_def["metadata"][field]
        logger.info("[MIGRATION] Cleaned up metadata fields")

    # Add annotation to track migration
    if "annotations" not in pod_def["metadata"]:
        pod_def["metadata"]["annotations"] = {}
    
    pod_def["metadata"]["annotations"]["migrated-from-pod"] = original_pod_name
    pod_def["metadata"]["annotations"]["migration-timestamp"] = str(int(time.time()))
    logger.info("[MIGRATION] Added migration tracking annotations")
    
    # Set the node selector to target the specific node
    if "spec" in pod_def:
        pod_def["spec"]["nodeName"] = target_node
        logger.info(f"[MIGRATION] Set target node to: {target_node}")
        
        # Remove fields that could interfere with scheduling
        for field in ["nodeSelector", "schedulerName", "priority", "priorityClassName"]:
            if field in pod_def["spec"]:
                del pod_def["spec"][field]
        logger.info("[MIGRATION] Removed scheduling interference fields")
    
    # Add tolerations for control plane if needed
    if node_info["is_control_plane"]:
        logger.info("[MIGRATION] Adding control plane tolerations")
        
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
        logger.info("[MIGRATION] Added control plane tolerations")
    
    # Create the new pod
    try:
        logger.info(f"[MIGRATION] Creating new pod {new_pod_name} on node {target_node}")
        api.create_namespaced_pod(namespace=namespace, body=pod_def)
        logger.info(f"[MIGRATION] Successfully created pod {new_pod_name}")
        
        # Wait for pod to be ready
        while True:
            pod = api.read_namespaced_pod(name=new_pod_name, namespace=namespace)
            if pod.status.phase == "Running":
                break
            logger.info(f"[MIGRATION] Waiting for pod {new_pod_name} to be ready...")
            time.sleep(5)
        
        # Restore checkpoint to new pod
        restore_checkpoint(api, namespace, new_pod_name, checkpoint_path)
        logger.info(f"[MIGRATION] Successfully restored checkpoint to new pod")
        
        # Cleanup checkpoint file
        os.remove(checkpoint_path)
        logger.info(f"[MIGRATION] Cleaned up checkpoint file")
        
        return new_pod_name
        
    except client.rest.ApiException as e:
        logger.error(f"[MIGRATION] Error creating pod: {e}")
        # Print more details if available
        if hasattr(e, 'body') and e.body:
            try:
                body = json.loads(e.body)
                if 'message' in body:
                    logger.error(f"[MIGRATION] API error message: {body['message']}")
            except:
                logger.error(f"[MIGRATION] API error body: {e.body}")
        raise

def wait_for_pod_running(api: client.CoreV1Api, namespace: str, pod_name: str, timeout_seconds=300):
    """Wait for a pod to reach Running state."""
    logger.info(f"[WAIT] Starting to wait for pod {pod_name} to reach Running state")
    
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
            logger.info(f"[WAIT] Current pod status: {pod.status.phase}")
            
            if pod.status.phase == "Running":
                logger.info(f"[WAIT] Pod {pod_name} is now running")
                return True
            
            if pod.status.phase == "Failed" or pod.status.phase == "Unknown":
                logger.error(f"[WAIT] Pod entered {pod.status.phase} state")
                
                # Get pod events for troubleshooting
                try:
                    events = api.list_namespaced_event(
                        namespace=namespace,
                        field_selector=f"involvedObject.name={pod_name}"
                    )
                    for event in events.items:
                        logger.error(f"[WAIT] Pod event: {event.reason} - {event.message}")
                except Exception as e:
                    logger.error(f"[WAIT] Could not get pod events: {e}")
                
                return False
            
            # Check if there are scheduling issues
            if pod.status.conditions:
                for condition in pod.status.conditions:
                    if condition.type == "PodScheduled" and condition.status == "False":
                        logger.warning(f"[WAIT] Scheduling issue: {condition.message}")
            
            time.sleep(5)
            
        except client.rest.ApiException as e:
            logger.error(f"[WAIT] Error checking pod status: {e}")
            time.sleep(5)
    
    logger.error(f"[WAIT] Timeout waiting for pod {pod_name} to start")
    return False

def migrate_pod(
    namespace: str,
    pod_name: str, 
    target_pod: str,
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
        logger.info("[MIGRATION] Debug logging enabled")
    
    # Load Kubernetes configuration
    logger.info("[MIGRATION] Starting pod migration process")
    api = load_k8s_config()
    
    # Verify pod exists
    try:
        logger.info(f"[MIGRATION] Verifying original pod {pod_name} exists")
        original_pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        original_node = original_pod.spec.node_name
        logger.info(f"[MIGRATION] Pod {pod_name} is currently on node {original_node}")
        
        # Check if already on target node
        if original_node == target_node:
            logger.info(f"[MIGRATION] Pod is already on target node {target_node}. No migration needed.")
            return pod_name
            
    except client.rest.ApiException as e:
        logger.error(f"[MIGRATION] Pod {pod_name} not found: {e}")
        return None
    
    # Create clone on target node
    logger.info("[MIGRATION] Creating pod clone on target node")
    new_pod_name = create_pod_clone_for_node(api, namespace, pod_name, target_node, target_pod)
    
    # Wait for the new pod to be running
    logger.info("[MIGRATION] Waiting for new pod to reach Running state")
    migration_success = wait_for_pod_running(api, namespace, new_pod_name)
    
    if migration_success:
        logger.info(f"[MIGRATION] Successfully migrated pod to {new_pod_name} on node {target_node}")
        
        # Delete original pod if requested
        if delete_original:
            try:
                logger.info(f"[MIGRATION] Deleting original pod {pod_name}")
                api.delete_namespaced_pod(
                    name=pod_name,
                    namespace=namespace
                )
                logger.info(f"[MIGRATION] Original pod {pod_name} deleted")
            except client.rest.ApiException as e:
                logger.error(f"[MIGRATION] Error deleting original pod: {e}")
        
        return new_pod_name
    else:
        logger.error("[MIGRATION] Migration failed - new pod did not reach Running state")
        return None
    
# Define input model
class MigrateRequest(BaseModel):
    namespace: str
    pod: str
    target_node: str
    target_pod: str = None
    delete_original: bool = True
    debug: bool = False

# FastAPI app
app = FastAPI()

@app.post("/migrate")
async def migrate(req: MigrateRequest):
    try:
        logger.info(f"[API] Received migration request for pod {req.pod} to node {req.target_node}")
        result = migrate_pod(
            namespace=req.namespace,
            pod_name=req.pod,
            target_pod=req.target_pod,
            target_node=req.target_node,
            delete_original=req.delete_original,
            debug=req.debug
        )
        if result:
            logger.info(f"[API] Migration successful. New pod name: {result}")
            return {"status": "success", "new_pod_name": result}
        else:
            logger.error("[API] Migration failed")
            raise HTTPException(status_code=500, detail="Migration failed")
    except Exception as e:
        logger.exception("[API] Exception during migration")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logger.info("[SERVER] Starting migration service")
    uvicorn.run(app, host="0.0.0.0", port=8000)