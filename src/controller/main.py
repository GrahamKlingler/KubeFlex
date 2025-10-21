#!/usr/bin/env python3
"""
Flex-Nautilus Controller Main Module

This module provides the main controller functionality for the Flex-Nautilus system,
including carbon-aware pod migration, job management, and testing capabilities.
"""

import os
import sys
import time
import json
import logging
import argparse
import subprocess
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Third-party imports
import requests
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# Local imports
from utils.cadvisor import *
from utils.db import *

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

class FlexNautilusController:
    """Main controller class for Flex-Nautilus system."""
    
    def __init__(self):
        self.scheduler = None
        self.db_conn = None
        self.nodes_info = []
        self.migration_url = os.getenv('MIGRATION_SERVICE_URL', "http://localhost:8000/migrate")
        
        # Environment variables
        self.pod_selector = os.getenv('POD_SELECTOR', 'io.kubernetes.pod.namespace=monitor')
        self.forecast_interval = int(os.getenv('FORECAST_INTERVAL', '72'))
        self.server_url = os.getenv('CARBON_SERVER_URL', 'http://metadata:8008')
        self.server_port = int(os.getenv('SERVER_PORT', 8008))
        
        # Global state
        self.db_min = []
        self.breakpoints = []

    def initialize(self) -> bool:
        """Initialize the controller with all required connections."""
        try:
            logger.info("Initializing Flex-Nautilus Controller...")
            
            # Connect to PostgreSQL database
            self.db_conn = connect_to_db(db_config)
            if not self.db_conn:
                logger.error("Failed to connect to PostgreSQL database")
                return False
            
            # Load Kubernetes configuration
            load_kubernetes_config()
            self.nodes_info = list_nodes_with_labels_annotations()
            
            logger.info(f"Found {len(self.nodes_info)} nodes in cluster:")
            for node in self.nodes_info:
                logger.info(f"  Node: {node['name']}, Labels: {node['labels']}")
            
            # Initialize scheduler
            self.scheduler = BackgroundScheduler()
            
            logger.info("Controller initialization completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize controller: {e}")
            return False
    
    def migrate_pod(self, namespace: str, pod: str, target_pod: str, 
                   target_node: str, delete_original: bool = True, 
                   debug: bool = True) -> Dict:
        """Migrate a pod to another node using the migration service."""
        try:
            logger.info(f"Starting migration: {pod} -> {target_pod} on {target_node}")
            
            headers = {"Content-Type": "application/json"}
            json_body = {
                "namespace": namespace,
                "pod": pod,
                "target_pod": target_pod,
                "target_node": target_node,
                "delete_original": delete_original,
                "debug": debug
            }
            
            response = requests.post(self.migration_url, json=json_body, headers=headers)
            
            result = {
                "status_code": response.status_code,
                "response": response.text,
                "success": response.status_code == 200
            }
            
            if result["success"]:
                logger.info(f"Migration successful: {response.text}")
            else:
                logger.error(f"Migration failed: {response.text}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error during migration: {e}")
            return {"success": False, "error": str(e)}
    
    def create_test_pod(self, pod_name: str, namespace: str = "foo", 
                       region: str = "TEN", thread_count: int = 1) -> bool:
        """Create a test pod for migration testing."""
        try:
            logger.info(f"Creating test pod: {pod_name} in namespace {namespace}")
            
            # Create pod manifest
            pod_manifest = {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": pod_name,
                    "namespace": namespace,
                    "labels": {"name": pod_name},
                    "annotations": {
                        "REGION": region,
                        "EXPECTED_DURATION": "12"
                    }
                },
                "spec": {
                    "affinity": {
                        "nodeAffinity": {
                            "preferredDuringSchedulingIgnoredDuringExecution": [{
                                "weight": 100,
                                "preference": {
                                    "matchExpressions": [{
                                        "key": "REGION",
                                        "operator": "In",
                                        "values": [region]
                                    }]
                                }
                            }]
                        }
                    },
                    "containers": [{
                        "name": "test-container",
                        "image": "debian:latest",
                        "command": ["/bin/bash", "-c"],
                        "args": [f"""
                            # Create test script
                            cat > /tmp/simple_test.sh << 'EOF'
                            #!/bin/bash
                            counter=0
                            while true; do
                                echo "Counter: $counter, Time: $(date), Threads: {thread_count}" >> /tmp/container.log
                                counter=$((counter + 1))
                                sleep 10
                            done
                            EOF
                            
                            chmod +x /tmp/simple_test.sh && \
                            apt-get update && \
                            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends criu htop procps && \
                            apt-get clean && \
                            rm -rf /var/lib/apt/lists/* && \
                            exec /tmp/simple_test.sh
                        """],
                        "imagePullPolicy": "IfNotPresent",
                        "securityContext": {
                            "privileged": True,
                            "capabilities": {
                                "add": ["SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE", "SYS_RESOURCE", "ALL"]
                            }
                        },
                        "resources": {
                            "requests": {"memory": "128Mi", "cpu": "1000m"},
                            "limits": {"memory": "1024Mi", "cpu": "2000m"}
                        },
                        "volumeMounts": [
                            {"name": "checkpoint-dir", "mountPath": "/tmp/checkpoint"},
                            {"name": "proc", "mountPath": "/proc"},
                            {"name": "sys", "mountPath": "/sys"},
                            {"name": "dev", "mountPath": "/dev"},
                            {"name": "var-run", "mountPath": "/var/run"},
                            {"name": "cgroup", "mountPath": "/sys/fs/cgroup"}
                        ]
                    }],
                    "volumes": [
                        {"name": "checkpoint-dir", "emptyDir": {}},
                        {"name": "proc", "hostPath": {"path": "/proc"}},
                        {"name": "sys", "hostPath": {"path": "/sys"}},
                        {"name": "dev", "hostPath": {"path": "/dev"}},
                        {"name": "var-run", "hostPath": {"path": "/var/run"}},
                        {"name": "cgroup", "hostPath": {"path": "/sys/fs/cgroup"}}
                    ]
                }
            }
            
            # Create pod using Kubernetes API
            core_v1 = client.CoreV1Api()
            pod = core_v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
            
            logger.info(f"Test pod {pod_name} created successfully")
            return True
            
        except ApiException as e:
            logger.error(f"Failed to create test pod: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating test pod: {e}")
            return False
    
    def wait_for_pod_ready(self, pod_name: str, namespace: str = "foo", 
                          timeout: int = 300) -> bool:
        """Wait for a pod to be ready."""
        try:
            logger.info(f"Waiting for pod {pod_name} to be ready...")
            
            core_v1 = client.CoreV1Api()
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                    
                    if pod.status.phase == "Running":
                        logger.info(f"Pod {pod_name} is now running")
                        return True
                    
                    if pod.status.phase in ["Failed", "Unknown"]:
                        logger.error(f"Pod {pod_name} entered {pod.status.phase} state")
                        return False
                    
                    logger.info(f"Pod {pod_name} status: {pod.status.phase}")
                    time.sleep(5)
                    
                except ApiException as e:
                    logger.warning(f"Error checking pod status: {e}")
                    time.sleep(5)
            
            logger.error(f"Timeout waiting for pod {pod_name} to be ready")
            return False
            
        except Exception as e:
            logger.error(f"Error waiting for pod: {e}")
            return False
    
    def get_pod_logs(self, pod_name: str, namespace: str = "foo", 
                    container: str = "test-container", lines: int = 50) -> str:
        """Get logs from a pod."""
        try:
            core_v1 = client.CoreV1Api()
            
            # Get logs
            logs = core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=lines
            )
            
            return logs
            
        except ApiException as e:
            logger.error(f"Failed to get logs for pod {pod_name}: {e}")
            return f"Error getting logs: {e}"
    
    def stream_pod_logs(self, pod_name: str, namespace: str = "foo", 
                       container: str = "test-container", duration: int = 60):
        """Stream pod logs for a specified duration."""
        try:
            logger.info(f"Streaming logs for pod {pod_name} for {duration} seconds...")
            
            core_v1 = client.CoreV1Api()
            start_time = time.time()
            
            while time.time() - start_time < duration:
                try:
                    logs = core_v1.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        container=container,
                        tail_lines=10
                    )
                    
                    if logs.strip():
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {pod_name}: {logs.strip()}")
                    
                    time.sleep(2)
                    
                except ApiException as e:
                    logger.warning(f"Error streaming logs: {e}")
                    time.sleep(2)
            
            logger.info(f"Finished streaming logs for pod {pod_name}")
            
        except Exception as e:
            logger.error(f"Error streaming logs: {e}")
    
    def delete_pod(self, pod_name: str, namespace: str = "foo") -> bool:
        """Delete a pod."""
        try:
            logger.info(f"Deleting pod {pod_name}")
            
            core_v1 = client.CoreV1Api()
            core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            
            logger.info(f"Pod {pod_name} deleted successfully")
            return True
            
        except ApiException as e:
            logger.error(f"Failed to delete pod {pod_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting pod: {e}")
            return False
    
    def run_migration_test(self, pod_name: str = "test-pod", 
                          namespace: str = "foo", 
                          source_region: str = "TEN",
                          target_region: str = "NE",
                          thread_count: int = 1,
                          log_duration: int = 60) -> Dict:
        """Run a complete migration test workflow."""
        logger.info("=" * 60)
        logger.info("STARTING MIGRATION TEST")
        logger.info("=" * 60)
        
        test_results = {
            "pod_creation": False,
            "pod_ready": False,
            "migration": False,
            "logs_before": "",
            "logs_after": "",
            "errors": []
        }
        
        try:
            # Step 1: Create test pod
            logger.info("Step 1: Creating test pod...")
            if self.create_test_pod(pod_name, namespace, source_region, thread_count):
                test_results["pod_creation"] = True
                logger.info("✓ Test pod created successfully")
            else:
                test_results["errors"].append("Failed to create test pod")
                return test_results
            
            # Step 2: Wait for pod to be ready
            logger.info("Step 2: Waiting for pod to be ready...")
            if self.wait_for_pod_ready(pod_name, namespace):
                test_results["pod_ready"] = True
                logger.info("✓ Pod is ready")
            else:
                test_results["errors"].append("Pod failed to become ready")
                return test_results
            
            # Step 3: Get logs before migration
            logger.info("Step 3: Collecting logs before migration...")
            test_results["logs_before"] = self.get_pod_logs(pod_name, namespace)
            logger.info("✓ Logs collected before migration")
            
            # Step 4: Find target node
            logger.info("Step 4: Finding target node...")
            target_nodes = [n['name'] for n in self.nodes_info 
                           if n['labels'].get('REGION') == target_region]
            
            if not target_nodes:
                test_results["errors"].append(f"No nodes found with REGION={target_region}")
                return test_results
            
            target_node = target_nodes[0]
            target_pod = f"{pod_name}-migrated"
            logger.info(f"✓ Target node: {target_node}")
            
            # Step 5: Perform migration
            logger.info("Step 5: Performing migration...")
            migration_result = self.migrate_pod(
                namespace, pod_name, target_pod, target_node, 
                delete_original=True, debug=True
            )
            
            if migration_result["success"]:
                test_results["migration"] = True
                logger.info("✓ Migration completed successfully")
                
                # Step 6: Wait for migrated pod to be ready
                logger.info("Step 6: Waiting for migrated pod to be ready...")
                if self.wait_for_pod_ready(target_pod, namespace):
                    logger.info("✓ Migrated pod is ready")
                    
                    # Step 7: Get logs after migration
                    logger.info("Step 7: Collecting logs after migration...")
                    test_results["logs_after"] = self.get_pod_logs(target_pod, namespace)
                    logger.info("✓ Logs collected after migration")
                    
                    # Step 8: Stream logs for monitoring
                    logger.info("Step 8: Streaming logs for monitoring...")
                    self.stream_pod_logs(target_pod, namespace, duration=log_duration)
                    
                    # Step 9: Cleanup
                    logger.info("Step 9: Cleaning up...")
                    self.delete_pod(target_pod, namespace)
                    logger.info("✓ Cleanup completed")
                    
                else:
                    test_results["errors"].append("Migrated pod failed to become ready")
            else:
                test_results["errors"].append(f"Migration failed: {migration_result.get('error', 'Unknown error')}")
            
        except Exception as e:
            logger.error(f"Error during migration test: {e}")
            test_results["errors"].append(str(e))
        
        # Print test results
        logger.info("=" * 60)
        logger.info("MIGRATION TEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"Pod Creation: {'✓' if test_results['pod_creation'] else '✗'}")
        logger.info(f"Pod Ready: {'✓' if test_results['pod_ready'] else '✗'}")
        logger.info(f"Migration: {'✓' if test_results['migration'] else '✗'}")
        
        if test_results["errors"]:
            logger.error("Errors encountered:")
            for error in test_results["errors"]:
                logger.error(f"  - {error}")
        
        logger.info("=" * 60)
        return test_results


def main():
    """Main entry point for the Flex-Nautilus Controller."""
    parser = argparse.ArgumentParser(description='Flex-Nautilus Controller')
    parser.add_argument('--pod-name', default='test-pod',
                       help='Name of the test pod to create')
    parser.add_argument('--namespace', default='foo',
                       help='Kubernetes namespace')
    parser.add_argument('--source-region', default='TEN',
                       help='Source region for the test pod')
    parser.add_argument('--target-region', default='NE',
                       help='Target region for migration')
    parser.add_argument('--thread-count', type=int, default=1,
                       help='Number of threads for stress testing')
    parser.add_argument('--log-duration', type=int, default=60,
                       help='Duration to stream logs (seconds)')
    
    args = parser.parse_args()
    
    # Initialize controller
    controller = FlexNautilusController()
    
    if not controller.initialize():
        logger.error("Failed to initialize controller")
        sys.exit(1)
    
    # Start production mode
    logger.info("Running Flex-Nautilus Controller")
    logger.info("Production mode not yet implemented")
    sys.exit(0)


if __name__ == "__main__":
    main()