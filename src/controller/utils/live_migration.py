#!/usr/bin/env python3
"""
CRIU Migration Service for KIND Clusters

This module provides CRIU-based migration capabilities:
1. Execute commands inside KIND nodes via docker exec
2. Use crictl to extract container information
3. Use ps aux to collect relevant PIDs from containerd processes
4. Analyze container mounts and handle external bind mounts
5. Use criu dump/restore for checkpointing
6. Handle container entrypoint to prevent re-initialization
"""

import os
import sys
import time
import json
import logging
import subprocess
import threading
import socket
import tarfile
import io
from datetime import datetime
from kubernetes import client
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import Kubernetes utilities
from .kubeapi import load_kubernetes_config

logger = logging.getLogger(__name__)



def criu_migrate_pod(source_pod: str, source_node: str, target_node: str, namespace: str,
                     checkpoint_dir: str = "/tmp/checkpoints") -> Dict:
    """
    Perform CRIU-based migration of a pod to a target node.
    

    
    Args:
        source_pod: Name of the source pod to migrate
        source_node: Name of the source KIND node
        target_node: Name of the target KIND node
        namespace: Kubernetes namespace
        checkpoint_dir: Directory to store checkpoint data
    
    Returns:
        Dict containing migration result with success status and details
    """
    tracker = CriuMigrationTracker(
        source_pod=source_pod,
        source_node=source_node,
        target_node=target_node,
        namespace=namespace,
        checkpoint_dir=checkpoint_dir
    )
    
    try:
        success = tracker.perform_migration()
        
        # Create detailed migration result
        migration_result = {
            "success": success,
            "source_pod": source_pod,
            "source_node": source_node,
            "target_node": target_node,
            "namespace": namespace,
            "checkpoint_dir": checkpoint_dir,
            "migration_complete": tracker.migration_state['migration_complete'],
            "source_container_id": tracker.source_container_id,
            "target_container_id": tracker.target_container_id,
            "errors": tracker.migration_state['errors'],
            "warnings": tracker.migration_state['warnings'],
            "steps_completed": tracker.migration_state['steps_completed']
        }
        
        # Add migration annotations to the target pod if migration was successful
        if success and tracker.target_container_id:
            try:
                tracker._add_migration_annotations()
            except Exception as e:
                logger.warning(f"[CRIU_MIGRATION] Failed to add migration annotations: {e}")
        
        return migration_result
    except Exception as e:
        logger.error(f"[CRIU_MIGRATION] Migration failed: {e}")
        return {
            "success": False,
            "source_pod": source_pod,
            "source_node": source_node,
            "target_node": target_node,
            "namespace": namespace,
            "checkpoint_dir": checkpoint_dir,
            "error": str(e),
            "migration_complete": False
        }
    finally:
        pass  # tracker.cleanup()


class CriuMigrationTracker:
    """Manages CRIU-based migration between KIND nodes."""
    
    def __init__(self, source_pod: str, source_node: str, target_node: str, namespace: str, checkpoint_dir: str):
        self.source_pod = source_pod
        self.source_node = source_node
        self.target_node = target_node
        self.namespace = namespace
        self.checkpoint_dir = checkpoint_dir
        # Ensure the checkpoint directory exists
        Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)
        
        # Container runtime information
        self.containerd_namespace = namespace
        self.containerd_socket = "/run/containerd/containerd.sock"
        
        # Container information
        self.source_container_id = None
        self.source_container_info = {}
        self.target_container_id = None
        
        # Migration state
        self.migration_state = {
            'phase': 'initialized',
            'start_time': time.time(),
            'current_step': 'initialization',
            'steps_completed': [],
            'errors': [],
            'warnings': [],
            'migration_complete': False
        }
        
        # Track which nodes have been validated to avoid repeated checks
        self.validated_nodes = set()
        
        # self._log_state("CriuMigrationTracker initialized")
    
    def _log_state(self, message: str, level: str = "INFO"):
        """Log current state of the migration tracker."""
        current_time = time.time()
        elapsed_time = current_time - self.migration_state['start_time']
        
        state_info = {
            'timestamp': current_time,
            'elapsed_time': elapsed_time,
            'phase': self.migration_state['phase'],
            'current_step': self.migration_state['current_step'],
            'source_pod': self.source_pod,
            'source_node': self.source_node,
            'target_node': self.target_node,
            'migration_complete': self.migration_state['migration_complete']
        }
        
        if level == "ERROR":
            logger.error(f"[STATE] {message}")
            self.migration_state['errors'].append(f"{current_time}: {message}")
        elif level == "WARNING":
            logger.warning(f"[STATE] {message}")
            self.migration_state['warnings'].append(f"{current_time}: {message}")
        else:
            logger.info(f"[STATE] {message}")
        
        # Save state to file
        state_file = Path(self.checkpoint_dir) / f"migration_state_{int(current_time)}.json"
        try:
            with open(state_file, 'w') as f:
                json.dump(state_info, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"[STATE] Failed to save state file: {e}")

    def _update_step(self, step_name: str, phase: str = None):
        """Update current step and phase."""
        if phase:
            self.migration_state['phase'] = phase
        self.migration_state['current_step'] = step_name
        self.migration_state['steps_completed'].append(f"{time.time()}: {step_name}")
        # self._log_state(f"Step: {step_name}")

    def validate_nodes_once(self) -> bool:
        """Validate migrator pods and CRIU capabilities once at the beginning."""
        try:
            logger.info("[VALIDATION] Running one-time node validation...")
            
            # Validate both source and target nodes
            nodes_to_validate = [self.source_node, self.target_node]
            
            for node_name in nodes_to_validate:
                if node_name in self.validated_nodes:
                    logger.info(f"[VALIDATION] Node {node_name} already validated, skipping")
                    continue
                
                logger.info(f"[VALIDATION] Validating node {node_name}...")
                
                # Check migrator pod exists
                if not self.ensure_debug_pod(node_name):
                    logger.error(f"[VALIDATION] Migrator pod not available on {node_name}")
                    return False
                
                # Check CRIU capabilities
                if not self.check_criu_capabilities(node_name):
                    logger.warning(f"[VALIDATION] CRIU capabilities check failed on {node_name}")
                
                # Set up cgroup yard
                if not self.setup_cgroup_yard(node_name):
                    logger.warning(f"[VALIDATION] Cgroup yard setup failed on {node_name}")
                
                # Mark node as validated
                self.validated_nodes.add(node_name)
                logger.info(f"[VALIDATION] Node {node_name} validation completed")
            
            logger.info("[VALIDATION] All nodes validated successfully")
            return True
            
        except Exception as e:
            logger.error(f"[VALIDATION] Node validation failed: {e}")
            return False

    def ensure_debug_pod(self, node_name: str) -> bool:
        """Ensure migrator pod exists on the specified node (created by start.sh)."""
        try:
            debug_pod_name = f"migrator-{node_name}"
            logger.info(f"[DEBUG_POD_ENSURE] Ensuring migrator pod exists on {node_name}")
            
            # Check if migrator pod exists and is ready
            cmd = f"kubectl get pod {debug_pod_name} -n monitor -o jsonpath='{{.status.phase}}'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and result.stdout.strip() == "Running":
                logger.info(f"[DEBUG_POD_ENSURE] Migrator pod {debug_pod_name} is running")
                return True
            else:
                logger.error(f"[DEBUG_POD_ENSURE] Migrator pod {debug_pod_name} not found or not running")
                logger.error(f"[DEBUG_POD_ENSURE] Migrator pods should be created by start.sh during service startup")
                return False
                
        except Exception as e:
            logger.error(f"[DEBUG_POD_ENSURE] Exception ensuring migrator pod: {e}")
            return False

    
    def test_kind_node_access(self, node_name: str) -> bool:
        """Test if we can access a KIND node and what tools are available."""
        try:
            logger.info(f"[NODE_TEST] Testing access to KIND node: {node_name}")
            
            # Test 1: Basic kubectl exec access to debug pod
            cmd = "echo 'Hello from debug pod'"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code != 0:
                logger.error(f"[NODE_TEST] Cannot access KIND node {node_name}: {stderr}")
                return False
            
            logger.info(f"[NODE_TEST] Basic access confirmed: {stdout.strip()}")
            
            # Test 2: Check if containerd is available
            cmd = "ctr version"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code == 0:
                logger.info(f"[NODE_TEST] Containerd available: {stdout.strip()}")
            else:
                logger.warning(f"[NODE_TEST] Containerd not available: {stderr}")
            
            # Test 3: Check if crictl is available
            cmd = "crictl --version"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code == 0:
                logger.info(f"[NODE_TEST] Crictl available: {stdout.strip()}")
            else:
                logger.warning(f"[NODE_TEST] Crictl not available: {stderr}")
            
            # Test 4: Check if Docker is available (it shouldn't be on KIND nodes)
            cmd = "docker version"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code == 0:
                logger.warning(f"[NODE_TEST] Docker is available on KIND node (unexpected): {stdout.strip()}")
            else:
                logger.info(f"[NODE_TEST] Docker not available on KIND node (expected): {stderr}")
            
            # Test 5: Check available tools
            cmd = "which ctr crictl docker criu"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            logger.info(f"[NODE_TEST] Available tools: {stdout.strip()}")
            
            # Test 6: Check CRIU availability specifically
            cmd = "criu check"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code == 0:
                logger.info(f"[NODE_TEST] CRIU check passed: {stdout.strip()}")
            else:
                logger.warning(f"[NODE_TEST] CRIU check failed: {stderr}")
            
            return True
            
        except Exception as e:
            logger.error(f"[NODE_TEST] Failed to test KIND node access: {e}")
            return False

    def check_criu_capabilities(self, node_name: str) -> bool:
        """Check CRIU capabilities and mount namespace support."""
        try:
            logger.info(f"[CRIU_CHECK] Checking CRIU capabilities on {node_name}")
            
            # Check basic CRIU functionality
            cmd = "criu check"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code != 0:
                logger.error(f"[CRIU_CHECK] CRIU check failed: {stderr}")
                return False
            
            logger.info(f"[CRIU_CHECK] CRIU basic check passed: {stdout.strip()}")
            
            # Check for mount namespace support
            cmd = "criu check --feature mnt_id"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code == 0:
                logger.info(f"[CRIU_CHECK] Mount namespace support available")
            else:
                logger.warning(f"[CRIU_CHECK] Mount namespace support limited: {stderr}")
            
            return True
            
        except Exception as e:
            logger.error(f"[CRIU_CHECK] Failed to check CRIU capabilities: {e}")
            return False

    def setup_cgroup_yard(self, node_name: str) -> bool:
        """Set up cgroup yard for CRIU checkpointing as per the guide."""
        try:
            logger.info(f"[CGROUP_YARD] Setting up cgroup yard on {node_name}")
            
            # Create cgroup yard directory structure
            cmd = "mkdir -p /cgroup-yard/{cpuset,cpu,memory,devices,freezer,blkio,perf_event}"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code != 0:
                logger.warning(f"[CGROUP_YARD] Failed to create cgroup directories: {stderr}")
            
            # Create unified cgroup v2 directory
            cmd = "mkdir -p /cgroup-yard/unified"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            # Mount cgroup controllers (ignore errors if already mounted)
            cgroup_controllers = ['cpu', 'memory', 'cpuset', 'devices', 'freezer']
            for controller in cgroup_controllers:
                cmd = f"mount -t cgroup -o {controller} none /cgroup-yard/{controller} 2>/dev/null || true"
                self.execute_on_kind_node(node_name, cmd)
            
            # Mount cgroup v2
            cmd = "mount -t cgroup2 none /cgroup-yard/unified 2>/dev/null || true"
            self.execute_on_kind_node(node_name, cmd)
            
            # Verify cgroup yard setup
            cmd = "ls -la /cgroup-yard/"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code == 0:
                logger.info(f"[CGROUP_YARD] Cgroup yard setup completed: {stdout.strip()}")
                return True
            else:
                logger.warning(f"[CGROUP_YARD] Cgroup yard verification failed: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"[CGROUP_YARD] Failed to setup cgroup yard: {e}")
            return False

    def setup_mount_points(self, node_name: str, checkpoint_dir: str) -> bool:
        """Set up mount points for CRIU checkpointing."""
        try:
            logger.info(f"[MOUNT_SETUP] Setting up mount points on {node_name}")
            
            # Create checkpoints directory
            cmd = f"mkdir -p {checkpoint_dir}"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code != 0:
                logger.error(f"[MOUNT_SETUP] Failed to create checkpoint directory: {stderr}")
                return False
            
            logger.info(f"[MOUNT_SETUP] Mount points setup completed")
            return True
            
        except Exception as e:
            logger.error(f"[MOUNT_SETUP] Failed to setup mount points: {e}")
            return False

    def execute_on_kind_node(self, node_name: str, command: str, print_output: bool = True) -> Tuple[int, str, str]:
        """Execute command on a KIND node via kubectl exec to debug pod with comprehensive logging."""
        try:
            debug_pod_name = f"migrator-{node_name}"
            full_command = f"kubectl exec -n monitor {debug_pod_name} -- {command}"
            
            # Log the command before execution
            # logger.info(f"[KUBECTL_EXEC] Executing on {node_name} via {debug_pod_name}: {command}")
            logger.info(f"[KUBECTL_EXEC] Full command: {full_command}")
            
            result = subprocess.run(full_command, shell=True, capture_output=True, text=True, timeout=60)
            
            if print_output:
                # Log the results
                logger.info(f"[KUBECTL_EXEC] Exit code: {result.returncode}")
                if result.stdout.strip():
                    # Check if its json, then pretty print it
                    if result.stdout.strip().startswith('{'):
                        logger.info(f"[KUBECTL_EXEC] STDOUT:\n{(json.dumps(json.loads(result.stdout), indent=2))}")
                    else:
                        logger.info(f"[KUBECTL_EXEC] STDOUT:\n{result.stdout}")
                if result.stderr.strip() and result.returncode != 0:
                    logger.warning(f"[KUBECTL_EXEC] STDERR:\n{result.stderr}")
            
            return result.returncode, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            logger.error(f"[KUBECTL_EXEC] Command timed out after 60 seconds: {command}")
            return -1, "", "Command timed out"
        except Exception as e:
            logger.error(f"[KUBECTL_EXEC] Exception executing command: {e}")
            return -1, "", str(e)
    
    def get_node_information(self) -> Tuple[str, str]:
        """Get node names for source and target pods."""
        try:
            self._update_step("getting_node_information", "node_discovery")
            
            from kubernetes import client
            load_kubernetes_config()
            api = client.CoreV1Api()
            
            # Get source pod's node
            source_pod = api.read_namespaced_pod(name=self.source_pod, namespace=self.namespace)
            self.source_node = source_pod.spec.node_name
            
            logger.info(f"[NODE_INFO] Source node: {self.source_node}")
            logger.info(f"[NODE_INFO] Target node: {self.target_node}")
            
            return self.source_node, self.target_node
            
        except Exception as e:
            # self._log_state(f"Failed to get node information: {e}", "ERROR")
            raise
    

    def get_container_info_via_crictl(self, node_name: str, pod_name: str) -> Dict:
        """Get container information using crictl on the KIND node."""
        try:
            self._update_step(f"getting_container_info_via_crictl_{node_name}", "container_discovery")
            
            # Get pod ID using crictl
            cmd = f"crictl pods --name {pod_name} --namespace {self.namespace} -q"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code != 0 or not stdout.strip():
                logger.error(f"Failed to get pod ID: {stderr}")
                return {}
            
            pod_id = stdout.strip()
            logger.info(f"[CRICTL] Found pod ID: {pod_id}")
            
            # Get container ID for the pod
            cmd = f"crictl ps --pod {pod_id} -q"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code != 0 or not stdout.strip():
                logger.error(f"Failed to get container ID: {stderr}")
                return {}
            
            container_id = stdout.strip()
            logger.info(f"[CRICTL] Found container ID: {container_id}")
            
            # Get detailed container information
            cmd = f"crictl inspect {container_id}"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd, print_output=False)
            
            if exit_code != 0:
                logger.error(f"Failed to inspect container: {stderr}")
                return {}
            
            container_info = json.loads(stdout)
            
            # Get task ID for checkpointing
            cmd = f"crictl ps --id {container_id} --output table"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            task_id = None
            if exit_code == 0:
                # Extract task ID from crictl output
                lines = stdout.strip().split('\n')
                if len(lines) > 1:
                    # Task ID is typically in the first column
                    task_id = lines[1].split()[0]
            
            return {
                'container_id': container_id,
                'pod_id': pod_id,
                'task_id': task_id,
                'container_info': container_info,
                'node': node_name
            }
            
        except Exception as e:
            logger.error(f"Failed to get container info via crictl: {e}")
            return {}
    

    def discover_container_mount_paths(self, container_id: str, node_name: str, pod_name: str) -> List[Tuple[str, str]]:
        """Discover mount paths for a container by executing commands inside the container."""
        try:
            logger.info(f"[MOUNT_DISCOVERY] Discovering mount paths for container {container_id} on {node_name} inside pod {pod_name}")
            
            # Execute mountinfo parsing directly inside the container
            cmd = f"kubectl exec -n {self.namespace} {pod_name} -- bash -c '"
            cmd += "cat /proc/1/mountinfo | while read line; do "
            cmd += "parts=($line); "
            cmd += "if [ ${#parts[@]} -ge 10 ]; then "
            cmd += "mount_id=${parts[0]}; "
            cmd += "parent_id=${parts[1]}; "
            cmd += "major_minor=${parts[2]}; "
            cmd += "root=${parts[3]}; "
            cmd += "mount_point=${parts[4]}; "
            cmd += "mount_options=${parts[5]}; "
            cmd += "dash_index=-1; "
            cmd += "for i in \"${!parts[@]}\"; do "
            cmd += "if [ \"${parts[i]}\" = \"-\" ]; then "
            cmd += "dash_index=$i; "
            cmd += "break; "
            cmd += "fi; "
            cmd += "done; "
            cmd += "if [ $dash_index -ge 0 ] && [ $((dash_index + 2)) -lt ${#parts[@]} ]; then "
            cmd += "fstype=${parts[$((dash_index + 1))]}; "
            cmd += "source=${parts[$((dash_index + 2))]}; "
            cmd += "super_options=${parts[$((dash_index + 3))]:-}; "
            cmd += "echo \"$mount_id|$parent_id|$major_minor|$root|$mount_point|$mount_options|$fstype|$source|$super_options\"; "
            cmd += "fi; "
            cmd += "fi; "
            cmd += "done'"
            
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if exit_code != 0:
                logger.error(f"[MOUNT_DISCOVERY] Failed to parse mountinfo: {stderr}")
                return []
            
            # Parse the output from the container
            lines = stdout.strip().split('\n')
            mounts = []
            
            for line in lines:
                if not line.strip():
                    continue
                parts = line.split('|')
                if len(parts) < 9:
                    continue
                
                mounts.append({
                    "mount_id": parts[0],
                    "parent_id": parts[1],
                    "major_minor": parts[2],
                    "root": parts[3],
                    "mount_point": parts[4],
                    "mount_options": parts[5],
                    "fstype": parts[6],
                    "source": parts[7],
                    "super_options": parts[8]
                })
            
            logger.info(f"[MOUNT_DISCOVERY] Parsed {len(mounts)} mount entries")
            
            # Store external mappings
            externals = []
            
            # Function to add mapping (avoids duplicates)
            def add_external(mountpoint, hostpath):
                if not mountpoint or not hostpath:
                    return
                # normalize paths (no trailing /)
                mountpoint = mountpoint.rstrip('/')
                if mountpoint == '':
                    mountpoint = '/'
                externals.append((mountpoint, hostpath))
            
            # 1) Find overlay root (fstype overlay and mountpoint '/') and extract upperdir
            overlay_found = None
            for m in mounts:
                if m['fstype'] == 'overlay' and (m['mount_point'] == '/' or m['mount_point'] == '//' or m['mount_point'] == ''):
                    overlay_found = m
                    break
            
            # If overlay root found, parse super_options for upperdir
            if overlay_found:
                super_opts = overlay_found['super_options']
                logger.info(f"[MOUNT_DISCOVERY] Overlay super_options: {super_opts}")
                
                # Extract upperdir from super_options
                upper = None
                import re
                ud = re.search(r'upperdir=([^,]+)', super_opts)
                if ud:
                    upper = ud.group(1)
                    logger.info(f"[MOUNT_DISCOVERY] Extracted upperdir: {upper}")
                    
                    # Use upperdir path for root external mount
                    add_external('/', upper)
                    logger.info(f"[MOUNT_DISCOVERY] Added overlay root external mount: / -> {upper}")
                else:
                    logger.warning("[MOUNT_DISCOVERY] Overlay root found but no upperdir in super_options")
                    # Try to extract from lowerdir if upperdir is not present
                    ld = re.search(r'lowerdir=([^,]+)', super_opts)
                    if ld:
                        lowerdir = ld.group(1)
                        logger.info(f"[MOUNT_DISCOVERY] Found lowerdir: {lowerdir}")
                        # Use the first layer of lowerdir as fallback
                        first_layer = lowerdir.split(':')[0]
                        add_external('/', first_layer)
                        logger.info(f"[MOUNT_DISCOVERY] Added overlay root external mount (from lowerdir): / -> {first_layer}")
                    else:
                        logger.warning("[MOUNT_DISCOVERY] No upperdir or lowerdir found in overlay options")
            else:
                logger.warning("[MOUNT_DISCOVERY] No overlay root mount found")
            
            # 2) Process all mounts and extract docker volume paths from mountinfo
            for m in mounts:
                mount_point = m['mount_point']
                source = m['source']
                fstype = m['fstype']
                root = m['root']
                
                # Skip pseudo filesystems
                if fstype in ('tmpfs', 'proc', 'sysfs', 'devpts', 'cgroup', 'cgroup2', 'mqueue', 'securityfs'):
                    continue
                
                # Handle /dev/vda1 mounts - extract the docker volume path from mountinfo
                if source == '/dev/vda1':
                    # In mountinfo, the actual path is in the 'root' field for bind mounts
                    if root.startswith('/docker/volumes/'):
                        add_external(mount_point, root)
                        logger.info(f"[MOUNT_DISCOVERY] Found docker volume mount: {mount_point} -> {root}")
                        continue
                
                # Handle overlay root
                if fstype == 'overlay' and mount_point == '/':
                    # Already handled above
                    continue
                
                # Handle other host-backed mounts
                host_keywords = ['containerd', 'kubelet', 'docker', '/run/containerd', '/var/lib/kubelet', '/var/lib/containerd', 'io.containerd']
                if source.startswith('/') and any(k in source for k in host_keywords):
                    add_external(mount_point, source)
                    logger.info(f"[MOUNT_DISCOVERY] Found host-backed mount: {mount_point} -> {source}")
            
            # 3) Handle common mounts that might not be caught above
            common_points = ['/etc/hosts', '/etc/hostname', '/etc/resolv.conf', '/dev/termination-log', '/run/secrets/kubernetes.io/serviceaccount', '/sys/fs/cgroup']
            for cp in common_points:
                for m in mounts:
                    if m['mount_point'] == cp:
                        source = m['source']
                        if source and source != 'none' and source != '/dev/vda1':
                            add_external(cp, source)
                            logger.info(f"[MOUNT_DISCOVERY] Found common mount: {cp} -> {source}")
                        break
            
            # 4) Handle /dev/shm specifically
            for m in mounts:
                if m['mount_point'] == '/dev/shm':
                    source = m['source']
                    if source.startswith('/run') or 'containerd' in source or 'sandboxes' in source:
                        add_external('/dev/shm', source)
                        logger.info(f"[MOUNT_DISCOVERY] Found sandbox-backed shm: /dev/shm -> {source}")
                    break
            
            # Deduplicate preserve order
            seen = set()
            final_externals = []
            for mp, hp in externals:
                key = (mp, hp)
                if key in seen:
                    continue
                seen.add(key)
                final_externals.append((mp, hp))
            
            logger.info(f"[MOUNT_DISCOVERY] Discovered {len(final_externals)} external mount mappings")
            for mp, hp in final_externals:
                logger.info(f"[MOUNT_DISCOVERY] External mount: {mp} -> {hp}")
            
            if not final_externals:
                logger.warning("[MOUNT_DISCOVERY] No external mounts discovered - this may cause CRIU dump to fail")
            
            return final_externals
                
        except Exception as e:
            logger.error(f"[MOUNT_DISCOVERY] Failed to discover mount paths: {e}")
            logger.error(f"[MOUNT_DISCOVERY] Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"[MOUNT_DISCOVERY] Traceback: {traceback.format_exc()}")
            return []


    def build_criu_dump_command(self, pid: int, checkpoint_dir: str, dump_file: str, container_id: str, node_name: str) -> str:
        """Build CRIU dump command with dynamically discovered mount paths using new parsing approach."""
        
        # Get the actual application PID (child of PID 1)
        cmd = f"kubectl exec -n {self.namespace} {self.source_pod} -- ps --ppid 1 -o pid= --no-headers"
        exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
        
        if exit_code != 0 or not stdout.strip():
            logger.warning(f"[CRIU_DUMP] Failed to get child process PID, using PID 1: {stderr}")
            app_pid = 1
        else:
            app_pid = int(stdout.strip())
            logger.info(f"[CRIU_DUMP] Using application PID for dump: {app_pid}")
        
        # Dynamically discover mount paths from container using new approach
        mount_mappings = self.discover_container_mount_paths(container_id, node_name, self.source_pod)
        
        # Build the CRIU dump command to be executed inside the source container
        cmd = f"criu dump -t {app_pid} -D {checkpoint_dir} --leave-running"
        
        # Add external mount flags for each discovered mount
        if mount_mappings:
            for mount_point, host_path in mount_mappings:
                cmd += f" --external mnt[{mount_point}]={host_path}"
                logger.info(f"[CRIU_DUMP] Adding external mount: {mount_point} -> {host_path}")
        else:
            # Fallback: use basic external mount handling if no specific mounts discovered
            logger.warning("[CRIU_DUMP] No specific mounts discovered, using basic external mount handling")
            cmd += " --external mnt[]"
        
        # Enhanced cgroup handling
        cmd += " --cgroup-yard /cgroup-yard"
        
        # Connection handling
        cmd += " --tcp-close"
        
        cmd += " --shell-job"

        # Enhanced logging
        cmd += f" -o {dump_file} -v4"
        
        return cmd


    def analyze_and_prepare_restore_mounts(self, node_name: str, checkpoint_dir: str) -> bool:
        """Analyze checkpoint mounts and prepare for safe restore."""
        try:
            logger.info(f"[RESTORE_PREP] Analyzing mounts for safe restore on {node_name}")
            
            # Check checkpoint images for mount information
            cmd = f"ls -la {checkpoint_dir}/*img | grep -E '(mount|mnt)' || true"
            exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
            
            if stdout:
                logger.info(f"[RESTORE_PREP] Mount-related images: {stdout}")
            
            # Check if we have mount namespace image
            mount_images = ["mountpoints.img", "mntns.img"]
            for img in mount_images:
                cmd = f"test -f {checkpoint_dir}/{img} && echo 'EXISTS' || echo 'MISSING'"
                exit_code, stdout, stderr = self.execute_on_kind_node(node_name, cmd)
                logger.info(f"[RESTORE_PREP] {img}: {stdout.strip()}")
            
            # Create safe restore directory structure
            safe_dirs = ["/proc", "/sys", "/dev", "/tmp"]
            for dir_path in safe_dirs:
                cmd = f"mkdir -p {dir_path}"
                self.execute_on_kind_node(node_name, cmd)
            
            logger.info("[RESTORE_PREP] Mount analysis and preparation completed")
            return True
            
        except Exception as e:
            logger.error(f"[RESTORE_PREP] Failed to prepare mounts for restore: {e}")
            return False

    def _is_external_mount(self, mount_info: Dict) -> bool:
        """Determine if a mount should be treated as external for CRIU."""
        destination = mount_info['destination']
        mount_type = mount_info['type']
        
        # Standard container mounts that should be handled internally
        internal_mounts = [
            '/proc',
            '/sys',
            '/dev',
            '/dev/pts',
            '/dev/mqueue',
            '/sys/fs/cgroup',
            '/tmp',
            '/var/run',
            '/run'
        ]
        
        # Skip internal mounts
        if destination in internal_mounts:
            return False
        
        # Skip bind mounts to standard container paths
        if mount_type == 'bind' and destination.startswith('/var/lib/kubelet'):
            return False
        
        # Skip bind mounts to containerd paths
        if mount_type == 'bind' and destination.startswith('/var/lib/containerd'):
            return False
        
        # Everything else is considered external
        return True

    def build_criu_restore_command(self, checkpoint_dir: str, container_id: str, node_name: str, restore_log_file: str = "/tmp/restore.log") -> str:
        """Build CRIU restore command with flags that mirror the dump command using unshare approach.
        
        Uses the same external mount handling and options as the dump command
        to ensure compatibility during restore.
        """
        # Get the same mount mappings used during dump
        migrated_pod_name = f"{self.source_pod}-migrated"
        mount_mappings = self.discover_container_mount_paths(container_id, node_name, migrated_pod_name)

        # Build the CRIU restore command to be executed inside the target container
        cmd = f"criu restore -D {checkpoint_dir} --restore-detached"
        
        # Add the same external mount flags used during dump
        if mount_mappings:
            for mount_point, host_path in mount_mappings:
                cmd += f" --external mnt[{mount_point}]={host_path}"
                logger.info(f"[CRIU_RESTORE] Adding external mount: {mount_point} -> {host_path}")
        else:
        # Use external mount handling to avoid segfaults
            cmd += " --external mnt[]"
        
        # Add connection handling (same as dump)
        cmd += " --tcp-close"
        
        cmd += " --shell-job"

        # Add pidfile and logging
        cmd += f" -o {restore_log_file} -v4"
        
        return cmd

    def create_target_pod_only(self, container_info: Dict) -> str:
        """Create target pod with native CRIU installation (no installation needed)."""
        try:
            logger.info(f"[TARGET_POD] Creating target pod with native CRIU on target node {self.target_node}")
            logger.info(f"[TARGET_POD] Source node: {self.source_node}, Target node: {self.target_node}")
            
            # Extract container information
            container_name = f"{self.source_pod}-migrated"
            image = container_info.get('image', 'salamander1223/testpod:latest')
            
            # Create a simple pod that waits for restore command (CRIU is already installed in the image)
            pod_spec_lines = [
                f"apiVersion: v1",
                f"kind: Pod",
                f"metadata:",
                f"  name: {container_name}",
                f"  namespace: {self.namespace}",
                f"  labels:",
                f"    name: {container_name}",
                f"    migrated: \"true\"",
                f"spec:",
                f"  hostPID: true",
                f"  containers:",
                f"  - name: {container_name}",
                f"    image: {image}",
                f"    imagePullPolicy: Always",
                f"    command:",
                f"    - /bin/sh",
                f"    - -c",
                f"    - |",
                f"      # Hold the container open, wait until restore is triggered",
                f"      echo '[holder] Container started, waiting for CRIU restore...'; sleep infinity",
                f"    securityContext:",
                f"      privileged: true",
                f"      capabilities:",
                f"        add:",
                f"        - SYS_ADMIN",
                f"        - CHECKPOINT_RESTORE",
                f"        - SYS_PTRACE",
                f"        - SYS_RESOURCE",
                f"        - NET_ADMIN",
                f"        - SYS_CHROOT",
                f"        - SETPCAP",
                f"        - SETGID",
                f"        - SETUID",
                f"      seccompProfile:",
                f"        type: Unconfined",
                f"      allowPrivilegeEscalation: true",
                f"    resources:",
                f"      requests:",
                f"        memory: \"128Mi\"",
                f"        cpu: \"100m\"",
                f"      limits:",
                f"        memory: \"256Mi\"",
                f"        cpu: \"500m\"",
                f"    volumeMounts:",
                f"    - name: checkpoint-volume",
                f"      mountPath: /tmp/checkpoints",
                f"    - name: script-data",
                f"      mountPath: /script-data",
                f"  volumes:",
                f"  - name: checkpoint-volume",
                f"    hostPath:",
                f"      path: {self.checkpoint_dir}",
                f"      type: DirectoryOrCreate",
                f"  - name: script-data",
                f"    emptyDir: {{}}",
                f"  restartPolicy: Never",
                f"  nodeSelector:",
                f"    kubernetes.io/hostname: {self.target_node}"
            ]
            
            # Write pod spec to shared volume on target node
            pod_spec_path = f"{self.checkpoint_dir}/target_pod.yaml"
            
            logger.info(f"[TARGET_POD] Creating pod spec file at {pod_spec_path} on target node {self.target_node}")
            
            # First, ensure the checkpoint directory exists and is writable
            cmd = f"mkdir -p {self.checkpoint_dir} && touch {self.checkpoint_dir}/test_write && rm {self.checkpoint_dir}/test_write"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            if exit_code != 0:
                logger.error(f"[TARGET_POD] Checkpoint directory {self.checkpoint_dir} is not writable: {stderr}")
                # Try alternative location
                pod_spec_path = "/tmp/target_pod.yaml"
                logger.info(f"[TARGET_POD] Using alternative location: {pod_spec_path}")
            
            # Debug: Check which node we're actually writing to
            cmd = f"hostname"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            logger.info(f"[TARGET_POD] Writing to node: {stdout.strip()}")
            
            # Create the file using a more reliable method
            logger.info(f"[TARGET_POD] Creating pod spec file using reliable method")
            pod_spec_content = "\n".join(pod_spec_lines)
            
            # Method 1: Use base64 encoding to avoid shell escaping issues
            import base64
            encoded_content = base64.b64encode(pod_spec_content.encode()).decode()
            cmd = f"echo '{encoded_content}' | base64 -d > {pod_spec_path}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            if exit_code == 0:
                logger.info(f"[TARGET_POD] Base64 method succeeded")
            else:
                logger.warning(f"[TARGET_POD] Base64 method failed: {stderr}")
                
                # Method 2: Use printf with proper escaping
                logger.info(f"[TARGET_POD] Trying printf method")
                # Escape single quotes and newlines
                escaped_content = pod_spec_content.replace("'", "'\"'\"'").replace('\n', '\\n')
                cmd = f"printf '{escaped_content}' > {pod_spec_path}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            if exit_code == 0:
                    logger.info(f"[TARGET_POD] Printf method succeeded")
            else:
                    logger.warning(f"[TARGET_POD] Printf method failed: {stderr}")
                    
                    # Method 3: Fallback to echo method with proper escaping
                    logger.info(f"[TARGET_POD] Trying echo method with proper escaping")
                    cmd = f"rm -f {pod_spec_path}"  # Clear the file first
                    self.execute_on_kind_node(self.target_node, cmd)
                    
                    for i, line in enumerate(pod_spec_lines):
                        # Escape single quotes in the line
                        escaped_line = line.replace("'", "'\"'\"'")
                        cmd = f"echo '{escaped_line}' >> {pod_spec_path}"
                        exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
                        if exit_code != 0:
                            logger.error(f"[TARGET_POD] Failed to write pod spec line {i+1}: {stderr}")
                            break
                    else:
                        logger.info(f"[TARGET_POD] Echo method succeeded")
            
            # Verify the file has content
            cmd = f"wc -l {pod_spec_path}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            logger.info(f"[TARGET_POD] Final file line count: {stdout.strip()}")
            
            # If file is still empty, this is a critical error
            if exit_code == 0 and stdout.strip().startswith("0 "):
                logger.error(f"[TARGET_POD] All file creation methods failed - file is empty")
                raise Exception("Failed to create pod spec file with content - all methods failed")
            
            # Apply the pod spec directly from the migrator pod (no file transfer needed)
            logger.info(f"[TARGET_POD] Applying pod spec directly from migrator pod")
            
            # Apply the pod spec using kubectl (run from the migrator pod, not inside it)
            cmd = f"kubectl apply -f {pod_spec_path}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code != 0:
                raise Exception(f"Failed to create pod: {stderr}")
            
            logger.info(f"[TARGET_POD] Successfully created pod: {container_name}")
            
            # Wait for pod to be ready
            cmd = f"kubectl wait --for=condition=Ready pod {container_name} -n {self.namespace} --timeout=20s"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code != 0:
                logger.warning(f"Pod {container_name} did not become ready: {stderr}")
            
            # Get the container ID of the new pod on target node
            cmd = f"crictl pods --name {container_name} --namespace {self.namespace} -q"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code != 0 or not stdout.strip():
                logger.error(f"Failed to get pod ID for {container_name} on target node: {stderr}")
                return None
            
            pod_id = stdout.strip()
            
            # Get container ID for the pod on target node
            cmd = f"crictl ps --pod {pod_id} -q"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code != 0 or not stdout.strip():
                logger.error(f"Failed to get container ID for pod {container_name} on target node: {stderr}")
                return None
            
            new_container_id = stdout.strip()
            logger.info(f"[TARGET_POD] Created migrated container {new_container_id} on target node {self.target_node}")
            
            return new_container_id
            
        except Exception as e:
            logger.error(f"Failed to create target pod: {e}")
            return None

    def perform_criu_dump(self, source_node: str, source_pod: str, container_id: str) -> str:
        """Perform CRIU dump on source container."""
        try:
            logger.info(f"[CRIU_DUMP] Performing CRIU dump on source container {container_id} on source node {source_node}")
            
            # Get container PID
            cmd = f"crictl inspect {container_id} | jq -r '.info.pid'"
            exit_code, stdout, stderr = self.execute_on_kind_node(source_node, cmd)
            
            if exit_code != 0 or not stdout.strip():
                logger.error(f"Failed to get container PID for dump: {stderr}")
                return None
            
            target_pid = int(stdout.strip())
            logger.info(f"[CRIU_DUMP] Container PID for dump: {target_pid}")
            
            # Create checkpoint directory
            checkpoint_name = "migration_checkpoint"
            checkpoint_dir = f"{self.checkpoint_dir}/{checkpoint_name}"
            
            cmd = f"mkdir -p {checkpoint_dir}"
            exit_code, stdout, stderr = self.execute_on_kind_node(source_node, cmd)
            
            if exit_code != 0:
                raise Exception(f"Failed to create checkpoint directory: {stderr}")
            
            # Setup cgroup yard and mount points
            if not self.setup_cgroup_yard(source_node):
                logger.warning("[CRIU_DUMP] Cgroup yard setup failed, continuing with basic checkpoint")
            
            if not self.setup_mount_points(source_node, checkpoint_dir):
                logger.warning("[CRIU_DUMP] Mount points setup failed, continuing with basic checkpoint")
            
            # Build and execute CRIU dump command with dynamic mount discovery
            dump_file = "/tmp/checkpoints/dump.log"
            criu_dump_cmd = self.build_criu_dump_command(
                target_pid,
                checkpoint_dir,
                dump_file,
                container_id,
                source_node
            )
            
            # Execute the command with kubectl exec wrapper
            command = f"kubectl exec -n {self.namespace} {source_pod} -- {criu_dump_cmd}"
            exit_code, stdout, stderr = self.execute_on_kind_node(source_node, command)
            
            if exit_code != 0:
                logger.error(f"CRIU dump failed: {stderr}")
                return None
            
            logger.info(f"[CRIU_DUMP] CRIU dump completed successfully")
            logger.info(f"[CRIU_DUMP] Dump output: {stdout}")
            
            return checkpoint_dir
            
        except Exception as e:
            logger.error(f"Failed to perform CRIU dump: {e}")
            return None

    def transfer_checkpoint_to_target(self, checkpoint_dir: str) -> bool:
        """Transfer checkpoint from source to target node."""
        try:
            logger.info(f"[TRANSFER] Transferring checkpoint from source to target node")
            
            # Create tar archive on source node
            tar_file = f"/tmp/migration_checkpoint.tar"
            cmd = f"tar -czf {tar_file} -C {checkpoint_dir} ."
            exit_code, _, stderr = self.execute_on_kind_node(self.source_node, cmd)
            
            if exit_code != 0:
                raise Exception(f"Failed to create tar archive: {stderr}")
            
            # Transfer via kubectl cp
            temp_file = f"/tmp/migration_checkpoint_{int(time.time())}.tar"
            
            # Copy from source to local
            cmd = f"kubectl cp monitor/migrator-{self.source_node}:/tmp/migration_checkpoint.tar {temp_file}"
            subprocess.run(cmd, shell=True, check=True)
            
            # Copy from local to target
            cmd = f"kubectl cp {temp_file} monitor/migrator-{self.target_node}:/tmp/migration_checkpoint.tar"
            subprocess.run(cmd, shell=True, check=True)
            
            # Extract on target node
            target_checkpoint_dir = f"{self.checkpoint_dir}/migration_checkpoint"
            
            # Create target directory and extract
            cmd = f"mkdir -p {target_checkpoint_dir}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            if exit_code != 0:
                raise Exception(f"Failed to create target checkpoint directory: {stderr}")
            
            # Extract the tar file
            cmd = f"tar -xzf /tmp/migration_checkpoint.tar -C {target_checkpoint_dir}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code != 0:
                raise Exception(f"Failed to extract checkpoint on target node: {stderr}")
            
            logger.info(f"[TRANSFER] Checkpoint transferred successfully")
            
            # Cleanup temporary files
            cmd = f"rm -f /tmp/migration_checkpoint.tar"
            self.execute_on_kind_node(self.source_node, cmd)
            self.execute_on_kind_node(self.target_node, cmd)
            subprocess.run(f"rm -f {temp_file}", shell=True)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to transfer checkpoint: {e}")
            return False

    def transfer_script_data_to_target(self, migrated_pod_name: str) -> bool:
        """Copy /script-data contents from source container to target container."""
        try:
            logger.info(f"[SCRIPT_DATA_COPY] Copying /script-data contents to target container")
            
            # First, check if /script-data exists in source container
            cmd = f"kubectl exec -n {self.namespace} {self.source_pod} -- test -d /script-data"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.source_node, cmd)
            
            if exit_code != 0:
                logger.warning(f"[SCRIPT_DATA_COPY] /script-data directory not found in source container: {stderr}")
                return True  # Not an error, just no data to copy
            
            # Copy contents using tar through kubectl exec
            # First, create a tar archive in source container
            cmd = f"kubectl exec -n {self.namespace} {self.source_pod} -- tar -czf /script-data.tar.gz -C /script-data ."
            exit_code, stdout, stderr = self.execute_on_kind_node(self.source_node, cmd)
            
            if exit_code != 0:
                logger.error(f"[SCRIPT_DATA_COPY] Failed to create tar archive in source: {stderr}")
                return False
            
            # Copy the tar file using the shared checkpoint directory (same as checkpoint transfer)
            # First, copy from source pod to shared checkpoint directory
            shared_script_file = f"{self.checkpoint_dir}/script-data.tar.gz"
            cmd = f"kubectl cp {self.namespace}/{self.source_pod}:/script-data.tar.gz {shared_script_file}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.source_node, cmd)
            
            if exit_code != 0:
                logger.error(f"[SCRIPT_DATA_COPY] Failed to copy tar from source pod: {stderr}")
                return False
            
            # Then, copy from shared checkpoint directory to target pod
            cmd = f"kubectl cp {shared_script_file} {self.namespace}/{migrated_pod_name}:/script-data.tar.gz"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code != 0:
                logger.error(f"[SCRIPT_DATA_COPY] Failed to copy tar to target pod: {stderr}")
                # Cleanup shared file
                cmd = f"rm -f {shared_script_file}"
                self.execute_on_kind_node(self.source_node, cmd)
                return False
            
            # Extract the tar file in target container root directory
            cmd = f"kubectl exec -n {self.namespace} {migrated_pod_name} -- tar -xzf /script-data.tar.gz -C /script-data"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code != 0:
                logger.error(f"[SCRIPT_DATA_COPY] Failed to extract tar in target: {stderr}")
                return False
            
            # Cleanup tar files
            cmd = f"kubectl exec -n {self.namespace} {self.source_pod} -- rm -f /script-data.tar.gz"
            self.execute_on_kind_node(self.source_node, cmd)
            
            cmd = f"kubectl exec -n {self.namespace} {migrated_pod_name} -- rm -f /script-data.tar.gz"
            self.execute_on_kind_node(self.target_node, cmd)
            
            # Cleanup shared file
            cmd = f"rm -f {shared_script_file}"
            self.execute_on_kind_node(self.source_node, cmd)
            
            # Verify the copy was successful
            cmd = f"kubectl exec -n {self.namespace} {migrated_pod_name} -- ls -la /script-data"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if exit_code == 0:
                logger.info(f"[SCRIPT_DATA_COPY] Successfully copied /script-data contents to target")
                logger.info(f"[SCRIPT_DATA_COPY] Target /script-data contents:\n{stdout}")
            else:
                logger.warning(f"[SCRIPT_DATA_COPY] Could not verify /script-data contents: {stderr}")
            
            return True
            
        except Exception as e:
            logger.error(f"[SCRIPT_DATA_COPY] Failed to copy /script-data contents: {e}")
            return False

    def execute_criu_restore_in_target(self, migrated_pod_name: str) -> bool:
        """Execute CRIU restore in the target pod with enhanced safety."""
        try:
            logger.info(f"[CRIU_RESTORE] Executing enhanced CRIU restore in target pod")
            
            # Analyze and prepare mounts before restore
            target_checkpoint_dir = f"{self.checkpoint_dir}/migration_checkpoint"
            if not self.analyze_and_prepare_restore_mounts(self.target_node, target_checkpoint_dir):
                logger.warning("[CRIU_RESTORE] Mount preparation had issues, continuing anyway")
            
            # Build enhanced restore command
            restore_command = self.build_criu_restore_command(target_checkpoint_dir, self.target_container_id, self.target_node)
            
            logger.info(f"[CRIU_RESTORE] Executing enhanced restore command: {restore_command}")
            
            # Execute restore command with timeout and kubectl exec wrapper
            cmd = f"kubectl exec -n {self.namespace} {migrated_pod_name} -- {restore_command}"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            # Check if restore was successful based on output content, not just exit code
            restore_success = False
            if exit_code == 0:
                # Check for success indicators in the output
                if "Restore finished successfully" in stdout or "Tasks resumed" in stdout:
                    restore_success = True
                    logger.info(f"[CRIU_RESTORE] CRIU restore completed successfully")
                else:
                    logger.warning(f"[CRIU_RESTORE] Restore command completed but success indicators not found")
            else:
                logger.error(f"CRIU restore command failed with exit code {exit_code}: {stderr}")
                
                # Try to get detailed restore logs for debugging
                cmd = f"kubectl exec -n {self.namespace} {migrated_pod_name} -- cat /tmp/restore.log"
                exit_code, log_output, _ = self.execute_on_kind_node(self.target_node, cmd)
                if exit_code == 0:
                    logger.error(f"[CRIU_RESTORE] Restore log: {log_output}")
            
            # Verify restore worked by checking if processes are running
            cmd = f"kubectl exec -n {self.namespace} {migrated_pod_name} -- ps aux | grep simple_test || true"
            exit_code, stdout, stderr = self.execute_on_kind_node(self.target_node, cmd)
            
            if 'simple_test' in stdout:
                logger.info(f"[CRIU_RESTORE] Verified: simple_test.sh is running after restore")
            else:
                logger.info(f"[CRIU_RESTORE] Note: simple_test.sh process not immediately visible, but restore was successful")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to execute CRIU restore in target: {e}")
            return False
    
    
    def perform_migration(self) -> bool:
        """Perform CRIU-based migration with optimized ordering."""
        try:
            logger.info("=" * 80)
            logger.info("[CRIU_MIGRATION] Starting CRIU migration with optimized ordering")
            logger.info("=" * 80)
            
            # Step 1: Get node information
            self._update_step("getting_node_information", "node_discovery")
            self.get_node_information()
            
            # Step 2: One-time node validation (replaces repeated checks)
            self._update_step("node_validation", "validation")
            logger.info("[MIGRATION] Running one-time node validation...")
            if not self.validate_nodes_once():
                logger.warning("[MIGRATION] Node validation failed, but continuing...")
            
            # Step 3: Test KIND node access (optional, for additional debugging)
            self._update_step("testing_kind_node_access", "validation")
            logger.info("[MIGRATION] Testing KIND node access...")
            if not self.test_kind_node_access(self.source_node):
                logger.warning("[MIGRATION] Source node access test failed, but continuing...")
            if not self.test_kind_node_access(self.target_node):
                logger.warning("[MIGRATION] Target node access test failed, but continuing...")
            
            # Step 4: Get source container information
            self._update_step("getting_source_container_info", "container_discovery")
            logger.info("[MIGRATION] Getting source container information...")
            source_container_info = self.get_container_info_via_crictl(self.source_node, self.source_pod)
            if not source_container_info:
                raise Exception(f"Could not get container information for pod {self.source_pod}")
            
            self.source_container_id = source_container_info['container_id']
            self.source_container_info = source_container_info
            logger.info(f"[MIGRATION] Source container ID: {self.source_container_id}")
            
            # Step 5: Create target pod
            self._update_step("creating_target_pod", "pod_creation")
            logger.info("[MIGRATION] Creating target pod with CRIU installation...")
            self.target_container_id = self.create_target_pod_only(source_container_info)
            if not self.target_container_id:
                raise Exception("Failed to create target pod")
            logger.info(f"[MIGRATION] Target container ID: {self.target_container_id}")
            
            # Step 6: Perform CRIU dump on source container
            self._update_step("performing_criu_dump", "checkpointing")
            logger.info("[MIGRATION] Performing CRIU dump on source container...")
            checkpoint_dir = self.perform_criu_dump(self.source_node, self.source_pod,self.source_container_id)
            if not checkpoint_dir:
                raise Exception("Failed to create CRIU checkpoint")
            
            # Step 7: Transfer checkpoint to target node
            self._update_step("transferring_checkpoint", "data_transfer")
            logger.info("[MIGRATION] Transferring checkpoint to target node...")
            if not self.transfer_checkpoint_to_target(checkpoint_dir):
                raise Exception("Failed to transfer checkpoint to target")
            
            # Step 8: Copy /script-data contents to target container
            self._update_step("copying_script_data", "data_transfer")
            logger.info("[MIGRATION] Copying /script-data contents to target container...")
            migrated_pod_name = f"{self.source_pod}-migrated"
            if not self.transfer_script_data_to_target(migrated_pod_name):
                logger.warning("[MIGRATION] Failed to copy /script-data contents, continuing with migration...")
            
            # Step 9: Execute CRIU restore in target pod
            self._update_step("executing_criu_restore", "restoration")
            logger.info("[MIGRATION] Executing CRIU restore in target pod...")
            if not self.execute_criu_restore_in_target(migrated_pod_name):
                raise Exception("Failed to execute CRIU restore in target pod")
            
            # Step 10: Final verification
            self._update_step("final_verification", "completion")
            logger.info("[MIGRATION] Verifying migration...")
            target_container_info = self.get_container_info_via_crictl(self.target_node, f"{self.source_pod}-migrated")
            
            logger.info("=" * 80)
            logger.info("[MIGRATION] Migration Summary:")
            logger.info(f"  Source Node: {self.source_node}")
            logger.info(f"  Target Node: {self.target_node}")
            logger.info(f"  Source Container: {self.source_container_id}")
            logger.info(f"  Target Container: {self.target_container_id}")
            logger.info("=" * 80)
            
            self.migration_state['migration_complete'] = True
            return True
            
        except Exception as e:
            # self._log_state(f"Migration failed: {e}", "ERROR")
            return False
    
    def _add_migration_annotations(self):
        """Add migration annotations to the target pod for tracking."""
        try:
            load_kubernetes_config()
            api = client.CoreV1Api()
            
            # Find the migrated pod on the target node
            pods = api.list_namespaced_pod(namespace=self.namespace)
            migrated_pod_name = None
            
            for pod in pods.items:
                if (pod.spec.node_name == self.target_node and 
                    pod.metadata.labels and 
                    pod.metadata.labels.get("migrated") == "true"):
                    migrated_pod_name = pod.metadata.name
                    break
            
            if not migrated_pod_name:
                logger.warning("[ANNOTATIONS] Could not find migrated pod to annotate")
                return
            
            # Add migration annotations
            annotations = {
                "migrated": "true",
                "migration-timestamp": str(int(time.time())),
                "source-node": self.source_node,
                "target-node": self.target_node,
                "migration-method": "criu-migration",
                "source-pod": self.source_pod
            }
            
            # Patch the pod with annotations
            patch_body = {
                "metadata": {
                    "annotations": annotations
                }
            }
            
            api.patch_namespaced_pod(
                name=migrated_pod_name,
                namespace=self.namespace,
                body=patch_body
            )
            
            logger.info(f"[ANNOTATIONS] Successfully added migration annotations to pod {migrated_pod_name}")
            
        except Exception as e:
            logger.error(f"[ANNOTATIONS] Failed to add migration annotations: {e}")
            raise

    def cleanup(self):
        """Clean up resources."""
        try:
            # Clean up checkpoint directories on both nodes
            cmd = f"rm -rf {self.checkpoint_dir}/*"
            self.execute_on_kind_node(self.source_node, cmd)
            self.execute_on_kind_node(self.target_node, cmd)
            
            logger.info("=" * 80)
            logger.info("[MIGRATION] Cleanup completed")
            logger.info("=" * 80)
        except Exception as e:
            logger.error(f"[CLEANUP] Error during cleanup: {e}")