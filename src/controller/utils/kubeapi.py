from datetime import datetime, timedelta
import requests
import json
import time
import psycopg2
import sys
import logging
import subprocess
import os
import tempfile
import shutil
import tarfile
import base64
import csv
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream
from prettytable import PrettyTable
from kubernetes.watch import Watch

logger = logging.getLogger(__name__)

# CSV logging setup for migration timings
CSV_LOG_FILE = "migration_timings.csv"
CSV_HEADERS = [
    "timestamp",
    "pod_name",
    "total_migration_time",
    "pod_clone_creation_time",
    "pod_ready_time",
    "original_pod_deletion_time",
    "migration_success"
]

def ensure_csv_file_exists():
    """Ensure the CSV log file exists with headers."""
    if not os.path.exists(CSV_LOG_FILE):
        with open(CSV_LOG_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)

def log_migration_timing(timing_data: dict):
    """Log migration timing data to CSV file."""
    ensure_csv_file_exists()
    
    # Prepare row data
    row_data = [
        timing_data.get('timestamp', datetime.now().isoformat()),
        timing_data.get('pod_name', ''),
        timing_data.get('total_migration_time', 0),
        timing_data.get('pod_clone_creation_time', 0),
        timing_data.get('pod_ready_time', 0),
        timing_data.get('original_pod_deletion_time', 0),
        timing_data.get('migration_success', False)
    ]
    
    # Write to CSV
    with open(CSV_LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(row_data)

def load_kubernetes_config():
    """Load Kubernetes configuration."""
    try:
        # Try in-cluster config first
        config.load_incluster_config()
        logger.info("Using in-cluster Kubernetes configuration")
    except:
        try:
            # Fall back to kubeconfig
            config.load_kube_config()
            logger.info("Using kubeconfig Kubernetes configuration")
        except Exception as e:
            logger.error(f"Failed to load Kubernetes configuration: {e}")
            raise

def get_node_info(api: client.CoreV1Api, node_name: str) -> dict:
    """Get detailed information about a specific node."""
    try:
        node = api.read_node(name=node_name)
        
        node_info = {
            "name": node.metadata.name,
            "labels": node.metadata.labels or {},
            "annotations": node.metadata.annotations or {},
            "taints": [],
            "capacity": node.status.capacity or {},
            "allocatable": node.status.allocatable or {},
            "conditions": []
        }
        
        # Extract taints
        if node.spec.taints:
            node_info["taints"] = [{
                "key": taint.key,
                "value": taint.value,
                "effect": taint.effect
            } for taint in node.spec.taints]
        
        # Extract conditions
        if node.status.conditions:
            node_info["conditions"] = [{
                "type": condition.type,
                "status": condition.status,
                "reason": condition.reason,
                "message": condition.message
            } for condition in node.status.conditions]
        
        return node_info
        
    except Exception as e:
        logger.error(f"Error getting node info for {node_name}: {e}")
        return {}

def get_pod_definition(api: client.CoreV1Api, namespace: str, pod_name: str) -> dict:
    """Get the pod definition for cloning."""
    try:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # Create a clean pod definition for cloning
        pod_definition = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": namespace,
                "labels": pod.metadata.labels or {},
                "annotations": pod.metadata.annotations or {}
            },
            "spec": {
                "containers": [],
                "restartPolicy": pod.spec.restart_policy,
                "nodeName": None,  # Will be set to target node
                "affinity": pod.spec.affinity,
                "tolerations": pod.spec.tolerations,
                "volumes": pod.spec.volumes or []
            }
        }
        
        # Copy container specifications
        for container in pod.spec.containers:
            container_spec = {
                "name": container.name,
                "image": container.image,
                "ports": container.ports or [],
                "env": container.env or [],
                "resources": container.resources or {},
                "volumeMounts": container.volume_mounts or [],
                "securityContext": container.security_context or {},
                "command": container.command or [],
                "args": container.args or []
            }
            pod_definition["spec"]["containers"].append(container_spec)
        
        return pod_definition
        
    except Exception as e:
        logger.error(f"Error getting pod definition for {pod_name}: {e}")
        return {}

def create_pod_clone_for_node(api: client.CoreV1Api, namespace: str, pod_name: str, target_node: str, target_pod_name: str = None) -> str:
    """Create a pod clone on the target node."""
    try:
        logger.info(f"[POD_CLONE] Starting pod clone creation process")
        logger.info(f"[POD_CLONE] Original pod: {pod_name}")
        logger.info(f"[POD_CLONE] Target node: {target_node}")
        
        # Get the original pod definition
        logger.info(f"[POD_CLONE] Step 1: Getting pod definition for {pod_name}")
        pod_definition = get_pod_definition(api, namespace, pod_name)
        if not pod_definition:
            raise Exception(f"Failed to get pod definition for {pod_name}")
        
        logger.info(f"[POD_CLONE] Pod definition retrieved:")
        logger.info(f"[POD_CLONE]   Containers: {len(pod_definition['spec']['containers'])}")
        logger.info(f"[POD_CLONE]   Volumes: {len(pod_definition['spec']['volumes'])}")
        logger.info(f"[POD_CLONE]   Restart Policy: {pod_definition['spec']['restartPolicy']}")
        
        # Set target pod name
        if not target_pod_name:
            target_pod_name = f"{pod_name}-migrated-{int(time.time())}"
        
        logger.info(f"[POD_CLONE] Step 2: Preparing pod clone")
        logger.info(f"[POD_CLONE]   Target pod name: {target_pod_name}")
        
        # Update pod definition for target node
        pod_definition["metadata"]["name"] = target_pod_name
        pod_definition["spec"]["nodeName"] = target_node
        
        if "affinity" in pod_definition["spec"] and pod_definition["spec"]["affinity"]:
            # Convert V1Affinity to dict if needed
            affinity = pod_definition["spec"]["affinity"]
            if hasattr(affinity, 'node_affinity') and affinity.node_affinity:
                logger.info(f"[POD_CLONE] Removing conflicting node affinity")
                # Set node_affinity to None to remove it
                affinity.node_affinity = None
        
        # Log container details
        for i, container in enumerate(pod_definition["spec"]["containers"]):
            logger.info(f"[POD_CLONE]   Container {i+1}: {container['name']}")
            logger.info(f"[POD_CLONE]     Image: {container['image']}")
            logger.info(f"[POD_CLONE]     Ports: {len(container.get('ports', []))}")
            logger.info(f"[POD_CLONE]     Environment Variables: {len(container.get('env', []))}")
            logger.info(f"[POD_CLONE]     Volume Mounts: {len(container.get('volumeMounts', []))}")
        
        # Create the pod
        logger.info(f"[POD_CLONE] Step 3: Creating pod {target_pod_name} on node {target_node}")
        created_pod = api.create_namespaced_pod(
            namespace=namespace,
            body=pod_definition
        )
        
        logger.info(f"[POD_CLONE] Successfully created pod:")
        logger.info(f"[POD_CLONE]   Name: {created_pod.metadata.name}")
        logger.info(f"[POD_CLONE]   Namespace: {created_pod.metadata.namespace}")
        logger.info(f"[POD_CLONE]   Node: {created_pod.spec.node_name}")
        logger.info(f"[POD_CLONE]   Phase: {created_pod.status.phase}")
        
        return target_pod_name
        
    except Exception as e:
        logger.error(f"[POD_CLONE] Error creating pod clone: {e}")
        raise

def create_pod_for_checkpoint_restore(api: client.CoreV1Api, namespace: str, target_pod_name: str, 
                                    target_node: str, original_pod: client.V1Pod, 
                                    checkpoint_info: dict) -> str:
    """Create a pod specifically designed for containerd checkpoint restoration."""
    try:
        logger.info(f"[POD_CHECKPOINT] Creating pod {target_pod_name} for containerd checkpoint restoration")
        logger.info(f"[POD_CHECKPOINT] Target node: {target_node}")
        logger.info(f"[POD_CHECKPOINT] Checkpoint: {checkpoint_info}")
        
        # Create pod definition based on original pod
        pod_definition = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": target_pod_name,
                "namespace": namespace,
                "labels": {
                    "app": "migrated-pod",
                    "checkpoint-restore": "true",
                    "original-pod": original_pod.metadata.name,
                    "runtime": "containerd"
                }
            },
            "spec": {
                "nodeName": target_node,
                "restartPolicy": "Never",  # Important for checkpoint restoration
                "containers": []
            }
        }
        
        # Create a special container for containerd checkpoint restoration
        task_id = checkpoint_info.get('task_id', '')
        checkpoint_name = checkpoint_info.get('checkpoint_name', '')
        checkpoint_dir = checkpoint_info.get('checkpoint_dir', f'/tmp/checkpoints/{checkpoint_name}')
        
        # Create a container that will be restored from containerd checkpoint
        checkpoint_container = {
            "name": "checkpoint-container",
            "image": "alpine:latest",  # Minimal image, will be replaced by checkpoint
            "command": ["/bin/sh"],
            "args": ["-c", f"""
                # Wait for containerd to be ready
                while ! ctr version >/dev/null 2>&1; do
                    echo "Waiting for containerd daemon..."
                    sleep 1
                done
                
                echo "Containerd is ready, starting checkpoint restoration..."
                
                # Check if checkpoint directory exists
                if [ ! -d "{checkpoint_dir}" ]; then
                    echo "Checkpoint directory {checkpoint_dir} not found"
                    exit 1
                fi
                
                echo "Found checkpoint directory: {checkpoint_dir}"
                
                # Create a new container for restoration
                NEW_TASK_ID="{task_id}_restored_$(date +%s)"
                echo "Creating new task: $NEW_TASK_ID"
                
                # Try to restore from checkpoint using ctr
                echo "Restoring from checkpoint {checkpoint_name}..."
                ctr -n k8s.io tasks restore $NEW_TASK_ID {checkpoint_dir} || {{
                    echo "Failed to restore with ctr tasks restore, trying alternative method..."
                    
                    # Alternative: create container and restore
                    ctr -n k8s.io containers create $NEW_TASK_ID alpine:latest || echo "Container may already exist"
                    ctr -n k8s.io tasks start --checkpoint {checkpoint_dir} $NEW_TASK_ID || {{
                        echo "Failed to start task with checkpoint"
                        exit 1
                    }}
                }}
                
                echo "Checkpoint restoration completed successfully"
                echo "New task ID: $NEW_TASK_ID"
                
                # Keep the container running to maintain the restored state
                sleep infinity
            """],
            "securityContext": {
                "privileged": True  # Required for containerd operations
            },
            "volumeMounts": [
                {
                    "name": "containerd-sock",
                    "mountPath": "/run/containerd"
                },
                {
                    "name": "checkpoint-data",
                    "mountPath": "/tmp/checkpoints"
                },
                {
                    "name": "proc",
                    "mountPath": "/proc"
                },
                {
                    "name": "sys",
                    "mountPath": "/sys"
                },
                {
                    "name": "dev",
                    "mountPath": "/dev"
                }
            ],
            "env": [
                {
                    "name": "TASK_ID",
                    "value": task_id
                },
                {
                    "name": "CHECKPOINT_NAME", 
                    "value": checkpoint_name
                },
                {
                    "name": "CHECKPOINT_DIR",
                    "value": checkpoint_dir
                },
                {
                    "name": "CONTAINERD_NAMESPACE",
                    "value": "k8s.io"
                }
            ]
        }
        
        pod_definition["spec"]["containers"].append(checkpoint_container)
        
        # Add volumes for containerd access
        pod_definition["spec"]["volumes"] = [
            {
                "name": "containerd-sock",
                "hostPath": {
                    "path": "/run/containerd"
                }
            },
            {
                "name": "checkpoint-data",
                "hostPath": {
                    "path": "/tmp/checkpoints"
                }
            },
            {
                "name": "proc",
                "hostPath": {
                    "path": "/proc"
                }
            },
            {
                "name": "sys",
                "hostPath": {
                    "path": "/sys"
                }
            },
            {
                "name": "dev",
                "hostPath": {
                    "path": "/dev"
                }
            }
        ]
        
        # Create the pod
        logger.info(f"[POD_CHECKPOINT] Creating containerd checkpoint restoration pod...")
        created_pod = api.create_namespaced_pod(
            namespace=namespace,
            body=pod_definition
        )
        
        logger.info(f"[POD_CHECKPOINT] Successfully created containerd checkpoint restoration pod:")
        logger.info(f"[POD_CHECKPOINT]   Name: {created_pod.metadata.name}")
        logger.info(f"[POD_CHECKPOINT]   Namespace: {created_pod.metadata.namespace}")
        logger.info(f"[POD_CHECKPOINT]   Node: {created_pod.spec.node_name}")
        logger.info(f"[POD_CHECKPOINT]   Phase: {created_pod.status.phase}")
        
        return target_pod_name
        
    except Exception as e:
        logger.error(f"[POD_CHECKPOINT] Error creating containerd checkpoint restoration pod: {e}")
        raise

def wait_for_pod_running(api: client.CoreV1Api, namespace: str, pod_name: str, timeout: int = 300) -> bool:
    """Wait for a pod to be in Running state."""
    try:
        logger.info(f"[POD_WAIT] Waiting for pod {pod_name} to be running")
        logger.info(f"[POD_WAIT] Timeout: {timeout}s")
        
        start_time = time.time()
        check_count = 0
        
        while time.time() - start_time < timeout:
            try:
                check_count += 1
                elapsed = time.time() - start_time
                
                pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
                phase = pod.status.phase
                
                logger.info(f"[POD_WAIT] Check #{check_count} (elapsed: {elapsed:.1f}s): Pod {pod_name} phase = {phase}")
                
                # Log container statuses
                if pod.status.container_statuses:
                    for i, container_status in enumerate(pod.status.container_statuses):
                        logger.info(f"[POD_WAIT]   Container {i+1}: {container_status.name}")
                        logger.info(f"[POD_WAIT]     Ready: {container_status.ready}")
                        logger.info(f"[POD_WAIT]     Restart Count: {container_status.restart_count}")
                        if container_status.state:
                            if container_status.state.running:
                                logger.info(f"[POD_WAIT]     State: Running (started: {container_status.state.running.started_at})")
                            elif container_status.state.waiting:
                                logger.info(f"[POD_WAIT]     State: Waiting - {container_status.state.waiting.reason}")
                            elif container_status.state.terminated:
                                logger.info(f"[POD_WAIT]     State: Terminated - {container_status.state.terminated.reason}")
                
                if phase == "Running":
                    logger.info(f"[POD_WAIT] SUCCESS: Pod {pod_name} is now running!")
                    logger.info(f"[POD_WAIT] Total wait time: {elapsed:.2f}s")
                    return True
                elif phase == "Failed":
                    logger.error(f"[POD_WAIT] FAILED: Pod {pod_name} failed to start")
                    return False
                elif phase == "Succeeded":
                    logger.info(f"[POD_WAIT] SUCCESS: Pod {pod_name} completed successfully")
                    return True
                else:
                    logger.info(f"[POD_WAIT] Pod {pod_name} is in phase: {phase}, continuing to wait...")
                
                time.sleep(5)
                
            except ApiException as e:
                if e.status == 404:
                    logger.warning(f"[POD_WAIT] Pod {pod_name} not found yet (check #{check_count})")
                    time.sleep(5)
                else:
                    logger.error(f"[POD_WAIT] Error checking pod status: {e}")
                    return False
        
        logger.error(f"[POD_WAIT] TIMEOUT: Pod {pod_name} did not reach Running state within {timeout}s")
        logger.error(f"[POD_WAIT] Total checks performed: {check_count}")
        return False
        
    except Exception as e:
        logger.error(f"[POD_WAIT] Error waiting for pod to be running: {e}")
        return False

def get_docker_and_k8s_info(api: client.CoreV1Api, namespace: str, pod_name: str) -> dict:
    """Get comprehensive Docker and Kubernetes information about a pod."""
    try:
        logger.info(f"[INFO_COLLECTION] Collecting Docker and K8s info for pod {pod_name}")
        
        # Get pod information
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        pod_info = {
            'pod_name': pod_name,
            'namespace': namespace,
            'node_name': pod.spec.node_name,
            'pod_ip': pod.status.pod_ip,
            'phase': pod.status.phase,
            'creation_timestamp': pod.metadata.creation_timestamp,
            'labels': pod.metadata.labels or {},
            'annotations': pod.metadata.annotations or {},
            'containers': [],
            'volumes': [],
            'restart_policy': pod.spec.restart_policy,
            'service_account': pod.spec.service_account_name,
            'node_selector': pod.spec.node_selector or {},
            'tolerations': [],
            'affinity': pod.spec.affinity,
            'security_context': pod.spec.security_context
        }
        
        # Extract tolerations
        if pod.spec.tolerations:
            pod_info['tolerations'] = [{
                'key': taint.key,
                'value': taint.value,
                'effect': taint.effect,
                'operator': taint.operator,
                'toleration_seconds': taint.toleration_seconds
            } for taint in pod.spec.tolerations]
        
        # Extract container information
        logger.info(f"[INFO_COLLECTION] Extracting container information...")
        for i, container in enumerate(pod.spec.containers):
            container_info = {
                'name': container.name,
                'image': container.image,
                'image_pull_policy': container.image_pull_policy,
                'command': container.command or [],
                'args': container.args or [],
                'working_dir': container.working_dir,
                'ports': [],
                'env': [],
                'env_from': [],
                'resources': {},
                'volume_mounts': [],
                'security_context': {},
                'liveness_probe': {},
                'readiness_probe': {},
                'startup_probe': {},
                'lifecycle': {}
            }
            
            # Extract ports
            if container.ports:
                for port in container.ports:
                    container_info['ports'].append({
                        'name': port.name,
                        'container_port': port.container_port,
                        'protocol': port.protocol,
                        'host_port': port.host_port,
                        'host_ip': port.host_ip
                    })
            
            # Extract environment variables
            if container.env:
                for env_var in container.env:
                    env_info = {
                        'name': env_var.name,
                        'value': env_var.value,
                        'value_from': {}
                    }
                    if env_var.value_from:
                        if env_var.value_from.field_ref:
                            env_info['value_from']['field_ref'] = {
                                'api_version': env_var.value_from.field_ref.api_version,
                                'field_path': env_var.value_from.field_ref.field_path
                            }
                        if env_var.value_from.resource_field_ref:
                            env_info['value_from']['resource_field_ref'] = {
                                'resource': env_var.value_from.resource_field_ref.resource,
                                'container_name': env_var.value_from.resource_field_ref.container_name,
                                'divisor': env_var.value_from.resource_field_ref.divisor
                            }
                        if env_var.value_from.config_map_key_ref:
                            env_info['value_from']['config_map_key_ref'] = {
                                'name': env_var.value_from.config_map_key_ref.name,
                                'key': env_var.value_from.config_map_key_ref.key,
                                'optional': env_var.value_from.config_map_key_ref.optional
                            }
                        if env_var.value_from.secret_key_ref:
                            env_info['value_from']['secret_key_ref'] = {
                                'name': env_var.value_from.secret_key_ref.name,
                                'key': env_var.value_from.secret_key_ref.key,
                                'optional': env_var.value_from.secret_key_ref.optional
                            }
                    container_info['env'].append(env_info)
            
            # Extract resources
            if container.resources:
                container_info['resources'] = {
                    'limits': container.resources.limits or {},
                    'requests': container.resources.requests or {}
                }
            
            # Extract volume mounts
            if container.volume_mounts:
                for mount in container.volume_mounts:
                    container_info['volume_mounts'].append({
                        'name': mount.name,
                        'mount_path': mount.mount_path,
                        'sub_path': mount.sub_path,
                        'read_only': mount.read_only,
                        'mount_propagation': mount.mount_propagation
                    })
            
            # Extract security context
            if container.security_context:
                container_info['security_context'] = {
                    'run_as_user': container.security_context.run_as_user,
                    'run_as_group': container.security_context.run_as_group,
                    'run_as_non_root': container.security_context.run_as_non_root,
                    'read_only_root_filesystem': container.security_context.read_only_root_filesystem,
                    'allow_privilege_escalation': container.security_context.allow_privilege_escalation,
                    'privileged': container.security_context.privileged,
                    'capabilities': {}
                }
                if container.security_context.capabilities:
                    container_info['security_context']['capabilities'] = {
                        'add': container.security_context.capabilities.add or [],
                        'drop': container.security_context.capabilities.drop or []
                    }
            
            pod_info['containers'].append(container_info)
            logger.info(f"[INFO_COLLECTION] Container {i+1}: {container.name} ({container.image})")
        
        # Extract volume information
        logger.info(f"[INFO_COLLECTION] Extracting volume information...")
        if pod.spec.volumes:
            for volume in pod.spec.volumes:
                volume_info = {
                    'name': volume.name,
                    'volume_type': 'unknown',
                    'config': {}
                }
                
                # Determine volume type and extract configuration
                if volume.host_path:
                    volume_info['volume_type'] = 'host_path'
                    volume_info['config'] = {
                        'path': volume.host_path.path,
                        'type': volume.host_path.type
                    }
                elif volume.empty_dir:
                    volume_info['volume_type'] = 'empty_dir'
                    volume_info['config'] = {
                        'size_limit': volume.empty_dir.size_limit,
                        'medium': volume.empty_dir.medium
                    }
                elif volume.config_map:
                    volume_info['volume_type'] = 'config_map'
                    volume_info['config'] = {
                        'name': volume.config_map.name,
                        'items': volume.config_map.items or [],
                        'default_mode': volume.config_map.default_mode,
                        'optional': volume.config_map.optional
                    }
                elif volume.secret:
                    volume_info['volume_type'] = 'secret'
                    volume_info['config'] = {
                        'secret_name': volume.secret.secret_name,
                        'items': volume.secret.items or [],
                        'default_mode': volume.secret.default_mode,
                        'optional': volume.secret.optional
                    }
                elif volume.persistent_volume_claim:
                    volume_info['volume_type'] = 'persistent_volume_claim'
                    volume_info['config'] = {
                        'claim_name': volume.persistent_volume_claim.claim_name,
                        'read_only': volume.persistent_volume_claim.read_only
                    }
                
                pod_info['volumes'].append(volume_info)
                logger.info(f"[INFO_COLLECTION] Volume: {volume.name} ({volume_info['volume_type']})")
        
        logger.info(f"[INFO_COLLECTION] Successfully collected info for pod {pod_name}")
        logger.info(f"[INFO_COLLECTION]   Containers: {len(pod_info['containers'])}")
        logger.info(f"[INFO_COLLECTION]   Volumes: {len(pod_info['volumes'])}")
        logger.info(f"[INFO_COLLECTION]   Node: {pod_info['node_name']}")
        logger.info(f"[INFO_COLLECTION]   IP: {pod_info['pod_ip']}")
        
        return pod_info
        
    except Exception as e:
        logger.error(f"[INFO_COLLECTION] Failed to collect Docker and K8s info for pod {pod_name}: {e}")
        return {}

def install_checkpointing_tools_on_pod(ssh_client, pod_ip: str, pod_name: str) -> bool:
    """Install necessary checkpointing tools on a pod via SSH."""
    try:
        logger.info(f"[TOOL_INSTALL] Installing checkpointing tools on pod {pod_name} ({pod_ip})")
        
        # Commands to install tools (similar to Dockerfile.migrate)
        install_commands = [
            # Update package lists
            "apt-get update",
            
            # Install system dependencies
            "apt-get install -y curl wget gnupg docker.io procps psmisc htop openssh-server sshpass apt-transport-https ca-certificates",
            
            # Install kubectl
            "curl -LO https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl && chmod +x kubectl && mv kubectl /usr/local/bin/",
            
            # Install crictl
            "VERSION=v1.28.0 && curl -L https://github.com/kubernetes-sigs/cri-tools/releases/download/${VERSION}/crictl-${VERSION}-linux-amd64.tar.gz | tar -xz -C /usr/local/bin && chmod +x /usr/local/bin/crictl",
            
            # Install Python packages for checkpointing
            "pip3 install paramiko psutil kubernetes requests psycopg2-binary",
            
            # Create necessary directories
            "mkdir -p /root/.kube /var/run/secrets/kubernetes.io/serviceaccount /tmp/checkpoint /var/run /sys/fs/cgroup",
            
            # Set permissions
            "chmod 700 /root/.kube",
            
            # Verify installations
            "kubectl version --client",
            "crictl --version",
            "python3 -c 'import paramiko, psutil, kubernetes; print(\"All Python packages installed successfully\")'"
        ]
        
        for i, command in enumerate(install_commands):
            logger.info(f"[TOOL_INSTALL] Executing command {i+1}/{len(install_commands)}: {command[:50]}...")
            
            stdin, stdout, stderr = ssh_client.exec_command(command)
            exit_code = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode('utf-8')
            stderr_text = stderr.read().decode('utf-8')
            
            if exit_code != 0:
                logger.warning(f"[TOOL_INSTALL] Command failed (exit code {exit_code}): {command}")
                logger.warning(f"[TOOL_INSTALL] stderr: {stderr_text}")
                # Continue with other commands even if one fails
            else:
                logger.info(f"[TOOL_INSTALL] Command succeeded: {command[:50]}...")
                if stdout_text.strip():
                    logger.info(f"[TOOL_INSTALL] Output: {stdout_text.strip()}")
        
        logger.info(f"[TOOL_INSTALL] Tool installation completed on pod {pod_name}")
        return True
        
    except Exception as e:
        logger.error(f"[TOOL_INSTALL] Failed to install tools on pod {pod_name}: {e}")
        return False

def setup_ssh_on_pod(ssh_client, pod_ip: str, pod_name: str) -> bool:
    """Setup SSH server on a pod if not already configured."""
    try:
        logger.info(f"[SSH_SETUP] Setting up SSH on pod {pod_name} ({pod_ip})")
        
        # Check if SSH is already running
        stdin, stdout, stderr = ssh_client.exec_command("systemctl is-active ssh || service ssh status")
        exit_code = stdout.channel.recv_exit_status()
        stdout_text = stdout.read().decode('utf-8')
        
        if "active" in stdout_text.lower() or "running" in stdout_text.lower():
            logger.info(f"[SSH_SETUP] SSH is already running on pod {pod_name}")
            return True
        
        # Setup SSH server
        ssh_commands = [
            # Install SSH server if not present
            "apt-get update && apt-get install -y openssh-server",
            
            # Configure SSH
            "mkdir -p /var/run/sshd",
            "echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config",
            "echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config",
            "echo 'PubkeyAuthentication yes' >> /etc/ssh/sshd_config",
            
            # Set root password
            "echo 'root:password123' | chpasswd",
            
            # Generate SSH host keys if they don't exist
            "[ ! -f /etc/ssh/ssh_host_rsa_key ] && ssh-keygen -A || true",
            
            # Start SSH server
            "/usr/sbin/sshd -D &"
        ]
        
        for command in ssh_commands:
            logger.info(f"[SSH_SETUP] Executing: {command}")
            stdin, stdout, stderr = ssh_client.exec_command(command)
            exit_code = stdout.channel.recv_exit_status()
            
            if exit_code != 0:
                logger.warning(f"[SSH_SETUP] Command failed: {command}")
            else:
                logger.info(f"[SSH_SETUP] Command succeeded: {command}")
        
        logger.info(f"[SSH_SETUP] SSH setup completed on pod {pod_name}")
        return True
        
    except Exception as e:
        logger.error(f"[SSH_SETUP] Failed to setup SSH on pod {pod_name}: {e}")
        return False

def wait_for_ssh_ready(pod_ip: str, pod_name: str, max_wait: int = 60) -> bool:
    """Wait for SSH to be ready on a pod by checking if port 22 is open."""
    import socket
    
    logger.info(f"[SSH_WAIT] Waiting for SSH to be ready on pod {pod_name} ({pod_ip})")
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((pod_ip, 22))
            sock.close()
            
            if result == 0:
                logger.info(f"[SSH_WAIT] SSH is ready on pod {pod_name} after {time.time() - start_time:.1f} seconds")
                return True
            else:
                logger.info(f"[SSH_WAIT] SSH not ready yet, waiting... ({time.time() - start_time:.1f}s elapsed)")
                time.sleep(2)
                
        except Exception as e:
            logger.warning(f"[SSH_WAIT] Error checking SSH readiness: {e}")
            time.sleep(2)
    
    logger.warning(f"[SSH_WAIT] SSH not ready on pod {pod_name} after {max_wait} seconds")
    return False

def migrate_pod(
    namespace: str,
    pod_name: str,
    target_node: str,
    target_pod: str = None,
    delete_original: bool = True,
    debug: bool = True
) -> str:
    """
    Migrate a pod from its current node to a target node using live migration.
    This orchestrates the complete migration process with Docker/K8s info acquisition.
    """
    timing_data = {
        'pod_name': pod_name,
        'total_migration_time': 0,
        'pod_clone_creation_time': 0,
        'pod_ready_time': 0,
        'original_pod_deletion_time': 0,
        'migration_success': False
    }
    
    start_time = time.time()
    
    # Load Kubernetes configuration
    logger.info("=" * 80)
    logger.info("[MIGRATION] ===== STARTING ENHANCED POD MIGRATION PROCESS =====")
    logger.info(f"[MIGRATION] Pod: {pod_name}")
    logger.info(f"[MIGRATION] Namespace: {namespace}")
    logger.info(f"[MIGRATION] Target Node: {target_node}")
    logger.info(f"[MIGRATION] Delete Original: {delete_original}")
    logger.info(f"[MIGRATION] Debug Mode: {debug}")
    logger.info("=" * 80)
    
    load_kubernetes_config()
    api = client.CoreV1Api()
    
    try:
        # Step 1: Verify pod exists and get detailed information
        logger.info(f"[MIGRATION] Step 1: Verifying original pod {pod_name} exists")
        original_pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        original_node = original_pod.spec.node_name
        
        # Log detailed pod information
        logger.info(f"[MIGRATION] Pod Details:")
        logger.info(f"[MIGRATION]   Name: {original_pod.metadata.name}")
        logger.info(f"[MIGRATION]   Namespace: {original_pod.metadata.namespace}")
        logger.info(f"[MIGRATION]   Current Node: {original_node}")
        logger.info(f"[MIGRATION]   Phase: {original_pod.status.phase}")
        logger.info(f"[MIGRATION]   Containers: {len(original_pod.spec.containers)}")
        
        for i, container in enumerate(original_pod.spec.containers):
            logger.info(f"[MIGRATION]   Container {i+1}: {container.name}")
            logger.info(f"[MIGRATION]     Image: {container.image}")
            logger.info(f"[MIGRATION]     Resources: {container.resources}")
        
        # Check if already on target node
        if original_node == target_node:
            logger.info(f"[MIGRATION] Pod is already on target node {target_node}. No migration needed.")
            timing_data['migration_success'] = True
            timing_data['total_migration_time'] = time.time() - start_time
            log_migration_timing(timing_data)
            return pod_name
        
        # Step 2: Get comprehensive Docker and Kubernetes information
        logger.info(f"[MIGRATION] Step 2: Collecting Docker and Kubernetes information...")
        source_pod_info = get_docker_and_k8s_info(api, namespace, pod_name)
        if not source_pod_info:
            raise Exception("Failed to collect source pod information")
        
        logger.info(f"[MIGRATION] Source pod info collected:")
        logger.info(f"[MIGRATION]   Containers: {len(source_pod_info['containers'])}")
        logger.info(f"[MIGRATION]   Volumes: {len(source_pod_info['volumes'])}")
        logger.info(f"[MIGRATION]   Node: {source_pod_info['node_name']}")
        logger.info(f"[MIGRATION]   IP: {source_pod_info['pod_ip']}")
        
        # Step 3: Create pod clone on target node using collected information
        logger.info(f"[MIGRATION] Step 3: Creating pod clone on target node {target_node}")
        clone_start = time.time()
        target_pod_name = create_pod_clone_for_node(
            api, namespace, pod_name, target_node, target_pod
        )
        timing_data['pod_clone_creation_time'] = time.time() - clone_start
        
        logger.info(f"[MIGRATION] Pod clone created successfully:")
        logger.info(f"[MIGRATION]   Original Pod: {pod_name} (node: {original_node})")
        logger.info(f"[MIGRATION]   New Pod: {target_pod_name} (node: {target_node})")
        logger.info(f"[MIGRATION]   Clone Creation Time: {timing_data['pod_clone_creation_time']:.2f}s")
        
        # Step 4: Wait for new pod to be running
        logger.info(f"[MIGRATION] Step 4: Waiting for new pod {target_pod_name} to be running")
        ready_start = time.time()
        if not wait_for_pod_running(api, namespace, target_pod_name):
            raise Exception(f"Failed to start pod {target_pod_name} on target node")
        timing_data['pod_ready_time'] = time.time() - ready_start
        
        logger.info(f"[MIGRATION] New pod is now running:")
        logger.info(f"[MIGRATION]   Pod Ready Time: {timing_data['pod_ready_time']:.2f}s")
        
        # Step 5: Get information about the target pod
        logger.info(f"[MIGRATION] Step 5: Collecting target pod information...")
        target_pod_info = get_docker_and_k8s_info(api, namespace, target_pod_name)
        if not target_pod_info:
            logger.warning(f"[MIGRATION] Failed to collect target pod information")
        else:
            logger.info(f"[MIGRATION] Target pod info collected:")
            logger.info(f"[MIGRATION]   Containers: {len(target_pod_info['containers'])}")
            logger.info(f"[MIGRATION]   Volumes: {len(target_pod_info['volumes'])}")
            logger.info(f"[MIGRATION]   Node: {target_pod_info['node_name']}")
            logger.info(f"[MIGRATION]   IP: {target_pod_info['pod_ip']}")
        
        # Step 6: Prepare for containerd-based migration
        logger.info(f"[MIGRATION] Step 6: Preparing for containerd-based migration...")
        logger.info(f"[MIGRATION] Containerd migration will use KIND node communication via docker exec")
        logger.info(f"[MIGRATION] No SSH setup required for containerd-based migration")
        
        # Step 7: Create containerd live migration
        logger.info(f"[MIGRATION] Step 7: Creating containerd live migration...")
        try:
            from .live_migration import ContainerdLiveMigrationTracker
            
            # Create containerd live migration tracker
            tracker = ContainerdLiveMigrationTracker(
                source_pod_name=pod_name,
                target_node=target_node,
                namespace=namespace,
                checkpoint_dir="/tmp/checkpoints"
            )
            
            logger.info(f"[MIGRATION] Starting containerd live migration...")
            logger.info(f"[MIGRATION] Source pod: {pod_name}")
            logger.info(f"[MIGRATION] Target node: {target_node}")
            
            # Perform the streaming live migration
            migration_success = tracker.perform_streaming_migration()
            
            if migration_success:
                logger.info(f"[MIGRATION] Containerd live migration completed successfully:")
                logger.info(f"[MIGRATION]   Checkpoints Created: {tracker.migration_state['checkpoints_created']}")
                logger.info(f"[MIGRATION]   Checkpoints Transferred: {tracker.migration_state['checkpoints_transferred']}")
                logger.info(f"[MIGRATION]   Migration Complete: {tracker.migration_state['migration_complete']}")
                
                # Clean up checkpoint directories
                tracker.cleanup()
                
                # Update target pod name to reflect live migration
                target_pod_name = f"{target_pod_name}-live-migrated"
                logger.info(f"[MIGRATION] Live migration completed, target pod: {target_pod_name}")
            else:
                raise Exception("Containerd live migration failed")
            
        except Exception as e:
            logger.warning(f"[MIGRATION] Containerd live migration failed: {e}")
            logger.info(f"[MIGRATION] Continuing with standard migration...")
            
            # Clean up tracker even on failure
            try:
                tracker.cleanup()
            except:
                pass
        
        # Step 8: Delete original pod if requested
        if delete_original:
            logger.info(f"[MIGRATION] Step 8: Deleting original pod {pod_name}")
            delete_start = time.time()
            api.delete_namespaced_pod(name=pod_name, namespace=namespace)
            timing_data['original_pod_deletion_time'] = time.time() - delete_start
            
            logger.info(f"[MIGRATION] Original pod deleted:")
            logger.info(f"[MIGRATION]   Deletion Time: {timing_data['original_pod_deletion_time']:.2f}s")
        else:
            logger.info(f"[MIGRATION] Step 8: Keeping original pod {pod_name} (delete_original=False)")
        
        # Calculate total time
        timing_data['total_migration_time'] = time.time() - start_time
        timing_data['migration_success'] = True
        
        logger.info("=" * 80)
        logger.info("[MIGRATION] ===== ENHANCED MIGRATION COMPLETED SUCCESSFULLY =====")
        logger.info(f"[MIGRATION] Final Results:")
        logger.info(f"[MIGRATION]   Original Pod: {pod_name} -> {target_pod_name}")
        logger.info(f"[MIGRATION]   Source Node: {original_node} -> Target Node: {target_node}")
        logger.info(f"[MIGRATION]   Total Migration Time: {timing_data['total_migration_time']:.2f}s")
        logger.info(f"[MIGRATION]   Clone Creation: {timing_data['pod_clone_creation_time']:.2f}s")
        logger.info(f"[MIGRATION]   Pod Ready: {timing_data['pod_ready_time']:.2f}s")
        logger.info(f"[MIGRATION]   Original Deletion: {timing_data['original_pod_deletion_time']:.2f}s")
        logger.info(f"[MIGRATION]   Source Pod Info: {len(source_pod_info.get('containers', []))} containers, {len(source_pod_info.get('volumes', []))} volumes")
        logger.info(f"[MIGRATION]   Target Pod Info: {len(target_pod_info.get('containers', []))} containers, {len(target_pod_info.get('volumes', []))} volumes")
        logger.info("=" * 80)
        
        # Log timing data
        log_migration_timing(timing_data)
        
        return target_pod_name
        
    except Exception as e:
        logger.error("=" * 80)
        logger.error("[MIGRATION] ===== ENHANCED MIGRATION FAILED =====")
        logger.error(f"[MIGRATION] Error: {e}")
        logger.error(f"[MIGRATION] Failed after: {time.time() - start_time:.2f}s")
        logger.error("=" * 80)
        
        timing_data['total_migration_time'] = time.time() - start_time
        timing_data['migration_success'] = False
        log_migration_timing(timing_data)
        raise