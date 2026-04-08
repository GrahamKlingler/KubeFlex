#!/usr/bin/env python3
"""
KubeFlex Controller Main Module

This module provides the main controller functionality for the KubeFlex system,
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
from apscheduler.triggers.interval import IntervalTrigger
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# Local imports - adjust path to find db and migrator modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from db.db import *
from migrator.live_migration import load_kubernetes_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

class KubeFlexController:
    """Main controller class for KubeFlex system."""
    
    def __init__(self, scheduler_time: Optional[float] = None, scheduling_policy: int = 3):
        self.scheduler = None
        self.db_conn = None
        self.nodes_info = []
        self.migration_url = os.getenv('MIGRATION_SERVICE_URL', "http://python-migrate-service:8000/live-migrate")
        
        # Environment variables
        self.pod_selector = os.getenv('POD_SELECTOR', 'io.kubernetes.pod.namespace=test-namespace')
        self.forecast_interval = int(os.getenv('FORECAST_INTERVAL', '72'))
        self.server_url = os.getenv('CARBON_SERVER_URL', 'http://metadata-service:8008')
        self.server_port = int(os.getenv('SERVER_PORT', 8008))
        
        # Scheduling policy: 1=initial placement only, 2=hourly migration, 3=forecast-based,
        # 4=forecast-aware adaptive, 5=always-best-region (migrate whenever a better region exists)
        if scheduling_policy not in [1, 2, 3, 4, 5]:
            raise ValueError(f"Invalid scheduling policy: {scheduling_policy}. Must be 1, 2, 3, 4, or 5.")
        self.scheduling_policy = scheduling_policy
        logger.info(f"Using scheduling policy: {scheduling_policy}")

        # Check interval: how often (in seconds of real time) to run migration checks,
        # and how many simulated hours to advance per check.
        self.check_interval_seconds = int(os.getenv('CHECK_INTERVAL_SECONDS', '3600'))
        self.sim_hours_per_check = int(os.getenv('SIM_HOURS_PER_CHECK', '1'))
        logger.info(f"Check interval: {self.check_interval_seconds}s real time, advancing {self.sim_hours_per_check}h sim time per check")

        # Policy 4 parameters
        self.forecast_window = int(os.getenv('FORECAST_WINDOW', '4'))
        self.cost_multiplier = float(os.getenv('MIGRATION_COST_MULTIPLIER', '2.0'))
        
        # Scheduler time (Unix timestamp) - defaults to current time if not provided
        # Valid range: 1577836800 (2020-01-01 00:00:00) to 1672527600 (2022-12-31 23:00:00)
        if scheduler_time is not None:
            self.scheduler_time = float(scheduler_time)
            # Validate timestamp range
            if self.scheduler_time < 1577836800 or self.scheduler_time > 1672527600:
                raise ValueError(f"Scheduler time {self.scheduler_time} is outside valid range (1577836800-1672527600)")
        else:
            # Default to current time, adjusted to data range
            current_time = time.time()
            # If current time is after data range, use end of data range
            if current_time > 1672527600:
                self.scheduler_time = 1672527600
            # If current time is before data range, use start of data range
            elif current_time < 1577836800:
                self.scheduler_time = 1577836800
            else:
                self.scheduler_time = current_time
        
        # Global state
        self.db_min = []
        self.breakpoints = []
        
        # Current simulation time (starts at scheduler_time)
        self.current_simulation_time = self.scheduler_time
        
        # Time conversion: track when simulation started in real time
        # This allows us to convert simulation time to real time for scheduling
        self.simulation_start_real_time = time.time()  # Real time when simulation started
        self.simulation_start_sim_time = self.scheduler_time  # Simulation time when started
        
        # Migration timing tracking
        self.migration_log_path = os.getenv('MIGRATION_LOG_PATH', '/tmp/migration_timings.log')
        self.last_criu_dump_duration = None  # Duration of last CRIU dump in seconds
        self.last_pre_criu_duration = None  # Duration from migration start to CRIU dump start

    def initialize(self) -> bool:
        """Initialize the controller with all required connections."""
        try:
            logger.info("Initializing KubeFlex Controller...")
            
            # Connect to PostgreSQL database
            self.db_conn = connect_to_db(db_config)
            if not self.db_conn:
                logger.error("Failed to connect to PostgreSQL database")
                return False
            
            # Load Kubernetes configuration
            if not load_kubernetes_config():
                logger.error("Failed to load Kubernetes configuration")
                return False
            
            # List nodes with labels and annotations
            api = client.CoreV1Api()
            nodes = api.list_node()
            
            self.nodes_info = []
            for node in nodes.items:
                node_info = {
                    "name": node.metadata.name,
                    "labels": node.metadata.labels or {},
                    "annotations": node.metadata.annotations or {}
                }
                self.nodes_info.append(node_info)
            
            logger.info(f"Found {len(self.nodes_info)} nodes in cluster:")
            for node in self.nodes_info:
                logger.info(f"  Node: {node['name']}, Labels: {node['labels']}")
            
            # Initialize scheduler with configured time
            self.scheduler = BackgroundScheduler()
            scheduler_datetime = datetime.fromtimestamp(self.scheduler_time, tz=pytz.UTC)
            logger.info(f"Scheduler initialized with time: {scheduler_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC (timestamp: {self.scheduler_time})")
            
            # Schedule hourly migration checks only for policy 2, 3, 4, and 5
            if self.scheduling_policy in [2, 3, 4, 5]:
                # Run on a configurable interval (default: every hour)
                self.scheduler.add_job(
                    self.hourly_migration_check,
                    trigger=IntervalTrigger(seconds=self.check_interval_seconds),
                    id='hourly_migration_check',
                    name='Hourly migration check',
                    replace_existing=True
                )
                
                # Start the scheduler
                self.scheduler.start()
                logger.info("Hourly migration scheduler started")
                
                # Run initial migration check
                logger.info("Running initial migration check...")
                self.hourly_migration_check()
            else:
                logger.info("Scheduling policy 1: No hourly migration checks (initial placement only)")
            
            logger.info("Controller initialization completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize controller: {e}")
            return False
    
    def migrate_pod(self, namespace: str, pod: str, target_node: str, 
                   delete_original: bool = False, debug: bool = True) -> Dict:
        """Migrate a pod to another node using the migration service (matches live_migration.py interface)."""
        try:
            logger.info(f"[MIGRATION] Starting migration: {pod} -> {target_node} in namespace {namespace}")
            
            # Get source node from pod
            api = client.CoreV1Api()
            source_pod_obj = api.read_namespaced_pod(name=pod, namespace=namespace)
            source_node = source_pod_obj.spec.node_name
            
            if not source_node:
                raise Exception(f"Pod {pod} is not assigned to any node")
            
            # Get target region from target node
            target_region = None
            try:
                target_node_obj = api.read_node(name=target_node)
                target_region = target_node_obj.metadata.labels.get("REGION") if target_node_obj.metadata.labels else None
                if target_region:
                    logger.info(f"[MIGRATION] Target region: {target_region}")
                else:
                    logger.warning(f"[MIGRATION] Could not determine target region from node {target_node}")
            except Exception as e:
                logger.warning(f"[MIGRATION] Failed to get target region from node: {e}")
            
            logger.info(f"[MIGRATION] Source node: {source_node}, Target node: {target_node}")
            
            headers = {"Content-Type": "application/json"}
            json_body = {
                "namespace": namespace,
                "pod": pod,
                "source_node": source_node,
                "target_node": target_node,
                "target_region": target_region,
                "delete_original": delete_original
            }
            
            # Log what we're sending to the migration service
            logger.info(f"[MIGRATION] Sending migration request with target_region: {target_region} (type: {type(target_region)})")
            logger.debug(f"[MIGRATION] Full request body: {json_body}")
            
            response = requests.post(self.migration_url, json=json_body, headers=headers, timeout=300)
            
            result = {
                "status_code": response.status_code,
                "response": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
                "success": response.status_code == 200
            }
            
            if result["success"]:
                logger.info(f"[MIGRATION] Migration successful: {result['response']}")
                # Pod deletion is now handled by the migration service
            else:
                logger.error(f"[MIGRATION] Migration failed: {result['response']}")
            
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[MIGRATION] Request error during migration: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[MIGRATION] Error during migration: {e}")
            return {"success": False, "error": str(e)}
    
    
    def wait_for_pod_ready(self, pod_name: str, namespace: str = "test-namespace", 
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
    
    def get_pod_logs(self, pod_name: str, namespace: str = "test-namespace", 
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
    
    def stream_pod_logs(self, pod_name: str, namespace: str = "test-namespace", 
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
    
    def delete_pod(self, pod_name: str, namespace: str = "test-namespace") -> bool:
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
    
    def _extract_base_pod_name(self, pod_name: str) -> str:
        """
        Extract the base pod name by removing numeric suffixes.
        Handles patterns like: test-pod-1, test-pod-2, test-pod-10
        This matches the logic in live_migration.py
        """
        import re
        # Match pattern: name followed by - and one or more digits at the end
        match = re.match(r'^(.+)-(\d+)$', pod_name)
        if match:
            return match.group(1)
        
        # No numeric suffix found, return original name
        return pod_name
    
    def _get_next_expected_pod_name(self, base_name: str, namespace: str) -> str:
        """
        Get the next expected pod name by finding the highest existing counter and incrementing.
        This matches the logic in live_migration.py
        """
        try:
            api = client.CoreV1Api()
            pods = api.list_namespaced_pod(namespace=namespace)
            
            max_counter = 0
            for pod in pods.items:
                pod_name = pod.metadata.name
                # Check if this pod matches our base name pattern
                if pod_name == base_name:
                    # Base name exists, start from 1
                    max_counter = max(max_counter, 0)
                elif pod_name.startswith(f"{base_name}-"):
                    # Extract counter from pod name
                    suffix = pod_name[len(f"{base_name}-"):]
                    try:
                        counter = int(suffix)
                        max_counter = max(max_counter, counter)
                    except ValueError:
                        # Not a numeric suffix, ignore
                        pass
            
            # Next counter is max_counter + 1
            next_counter = max_counter + 1
            return f"{base_name}-{next_counter}"
            
        except Exception as e:
            logger.warning(f"[MIGRATION_TEST] Failed to determine next pod name, using counter 1: {e}")
            # Fallback to counter 1 if we can't query existing pods
            return f"{base_name}-1"
    
    def _get_pod_counter(self, pod_name: str, base_name: str) -> int:
        """Get the numeric counter suffix from a pod name. Returns 0 for the base pod."""
        if pod_name == base_name:
            return 0
        suffix = pod_name[len(base_name) + 1:]  # skip the "-"
        try:
            return int(suffix)
        except ValueError:
            return 0

    def discover_pods_for_migration(self, namespace: str = "test-namespace") -> List[Dict]:
        """Discover pods that can be migrated based on pod selector.

        For each migration chain (same base name), only the pod with the highest
        counter is returned — older replicas are stale and should not be migrated.
        """
        try:
            api = client.CoreV1Api()
            pods = api.list_namespaced_pod(namespace=namespace)

            # Group running pods by base name, keep only the latest (highest counter)
            best_per_base = {}  # base_name -> (counter, pod_info)
            for pod in pods.items:
                if pod.status.phase == "Running" and pod.spec.node_name:
                    base_pod_name = self._extract_base_pod_name(pod.metadata.name)
                    counter = self._get_pod_counter(pod.metadata.name, base_pod_name)

                    pod_info = {
                        "name": pod.metadata.name,
                        "base_name": base_pod_name,
                        "namespace": pod.metadata.namespace,
                        "node": pod.spec.node_name,
                        "region": pod.metadata.labels.get("REGION") if pod.metadata.labels else None,
                        "annotations": pod.metadata.annotations or {}
                    }

                    if base_pod_name not in best_per_base or counter > best_per_base[base_pod_name][0]:
                        best_per_base[base_pod_name] = (counter, pod_info)

            candidate_pods = [info for _, info in best_per_base.values()]

            logger.info(f"[DISCOVERY] Found {len(candidate_pods)} candidate pods for migration "
                       f"(from {sum(1 for p in pods.items if p.status.phase == 'Running')} total running)")
            for pod_info in candidate_pods:
                logger.info(f"[DISCOVERY]   Latest in chain: {pod_info['name']} on {pod_info['node']}")
            return candidate_pods
            
        except Exception as e:
            logger.error(f"[DISCOVERY] Failed to discover pods: {e}")
            return []
    
    def get_forecast_data_from_metadata(self, duration_hours: int = 24) -> Optional[Dict]:
        """Call metadata endpoint to get forecast data (min forecast + all region forecasts)."""
        try:
            # Call metadata endpoint
            metadata_url = f"{self.server_url}"
            request_data = {"duration": duration_hours}
            
            logger.info(f"[METADATA] Requesting forecast for {duration_hours} hours from metadata service...")
            response = requests.post(metadata_url, json=request_data, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[METADATA] Metadata service returned HTTP {response.status_code}: {response.text}")
                return None
            
            forecast_data = response.json()
            return forecast_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[METADATA] Failed to connect to metadata service: {e}")
            return None
        except Exception as e:
            logger.error(f"[METADATA] Error getting forecast data: {e}")
            import traceback
            logger.error(f"[METADATA] Traceback: {traceback.format_exc()}")
            return None
    
    def get_minimum_region_from_metadata(self, duration_hours: int = 24) -> Optional[str]:
        """Call metadata endpoint to get the minimum region for the current simulation time."""
        try:
            # Use a forecast window that includes the current hour
            forecast_duration = max(1, duration_hours)
            
            # Call metadata endpoint
            forecast_data = self.get_forecast_data_from_metadata(forecast_duration)
            if not forecast_data:
                return None
            
            # Extract min_forecast data
            min_forecast = forecast_data.get('min_forecast', {}).get('forecast_data', [])
            if not min_forecast:
                logger.error("[METADATA] No min_forecast data in response")
                return None
            
            # Find the region for the current hour
            # The min_forecast is sorted by timestamp, find the entry closest to current simulation time
            current_datetime = datetime.fromtimestamp(self.current_simulation_time, tz=pytz.UTC)
            current_str = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
            
            # Find the entry that matches the current hour
            min_region = None
            for point in min_forecast:
                if len(point) >= 3:
                    point_time_str = point[0]  # timestamp string
                    point_region = point[1]    # region
                    # Check if this point matches the current hour
                    try:
                        point_datetime = datetime.strptime(point_time_str.split('+')[0], "%Y-%m-%d %H:%M:%S")
                        point_datetime = pytz.UTC.localize(point_datetime)
                        # Check if within the same hour
                        if abs((point_datetime - current_datetime).total_seconds()) < 3600:
                            min_region = point_region
                            logger.info(f"[METADATA] Found minimum region for current hour: {min_region} (timestamp: {point_time_str})")
                            break
                    except Exception as e:
                        logger.warning(f"[METADATA] Error parsing timestamp {point_time_str}: {e}")
                        continue
            
            # If no exact match, use the first entry (closest to start of forecast)
            if not min_region and min_forecast:
                min_region = min_forecast[0][1] if len(min_forecast[0]) >= 2 else None
                logger.info(f"[METADATA] Using first forecast entry region: {min_region}")
            
            return min_region
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[METADATA] Failed to connect to metadata service: {e}")
            return None
        except Exception as e:
            logger.error(f"[METADATA] Error getting minimum region: {e}")
            import traceback
            logger.error(f"[METADATA] Traceback: {traceback.format_exc()}")
            return None
    
    def find_target_node_for_region(self, target_region: str, source_node: str) -> Optional[str]:
        """Find a node in the target region.

        If the source node is already in the target region, returns None
        (no migration needed). Otherwise returns a node in the target region.
        """
        try:
            api = client.CoreV1Api()
            nodes = api.list_node()

            # First check if source node is already in target region
            for node in nodes.items:
                if node.metadata.name == source_node:
                    source_region = node.metadata.labels.get("REGION") if node.metadata.labels else None
                    if source_region == target_region:
                        logger.info(f"[NODE_SELECTION] Source node {source_node} is already in region {target_region}, no migration needed")
                        return None

            # Find a different node in the target region
            for node in nodes.items:
                if node.metadata.name != source_node:
                    region = node.metadata.labels.get("REGION") if node.metadata.labels else None
                    if region == target_region:
                        logger.info(f"[NODE_SELECTION] Found target node: {node.metadata.name} in region {target_region}")
                        return node.metadata.name

            logger.warning(f"[NODE_SELECTION] No node found in region {target_region}")
            return None
            
        except Exception as e:
            logger.error(f"[NODE_SELECTION] Failed to find target node: {e}")
            return None
    
    def parse_migration_timings(self, migration_result: Dict) -> Optional[Dict]:
        """Parse migration response to extract step timings and durations."""
        try:
            response_data = migration_result.get("response", {})
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    return None
            
            migration_details = response_data.get("migration_details", {})
            steps_completed = migration_details.get("steps_completed", [])
            
            if not steps_completed:
                logger.warning("[TIMING] No steps_completed found in migration response")
                return None
            
            # Parse steps: format is "timestamp: step_name"
            parsed_steps = []
            for step_str in steps_completed:
                if ':' in step_str:
                    parts = step_str.split(':', 1)
                    if len(parts) == 2:
                        try:
                            timestamp = float(parts[0].strip())
                            step_name = parts[1].strip()
                            parsed_steps.append((timestamp, step_name))
                        except ValueError:
                            continue
            
            if not parsed_steps:
                logger.warning("[TIMING] Could not parse any steps from migration response")
                return None
            
            # Calculate durations between consecutive steps
            step_durations = []
            for i in range(len(parsed_steps) - 1):
                start_time = parsed_steps[i][0]
                end_time = parsed_steps[i + 1][0]
                duration = end_time - start_time
                step_name = parsed_steps[i][1]
                step_durations.append({
                    "step": step_name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration_seconds": duration
                })
            
            # Find CRIU dump step specifically
            criu_dump_duration = None
            pre_criu_duration = None
            migration_start_time = parsed_steps[0][0] if parsed_steps else None
            
            for i, (timestamp, step_name) in enumerate(parsed_steps):
                if 'criu_dump' in step_name.lower() or 'performing_criu_dump' in step_name.lower():
                    if i + 1 < len(parsed_steps):
                        criu_dump_duration = parsed_steps[i + 1][0] - timestamp
                        # Calculate time from migration start to CRIU dump start
                        if migration_start_time:
                            pre_criu_duration = timestamp - migration_start_time
                        break
            
            # Calculate total migration time
            if len(parsed_steps) > 1:
                total_duration = parsed_steps[-1][0] - parsed_steps[0][0]
            else:
                total_duration = 0
            
            timing_data = {
                "total_steps": len(parsed_steps),
                "total_duration_seconds": total_duration,
                "step_durations": step_durations,
                "criu_dump_duration_seconds": criu_dump_duration,
                "pre_criu_duration_seconds": pre_criu_duration,
                "parsed_at": datetime.now(pytz.UTC).isoformat()
            }
            
            # Store CRIU dump duration and pre-CRIU duration for scheduling
            if criu_dump_duration is not None:
                self.last_criu_dump_duration = criu_dump_duration
                logger.info(f"[TIMING] CRIU dump duration: {criu_dump_duration:.3f} seconds")
            if pre_criu_duration is not None:
                self.last_pre_criu_duration = pre_criu_duration
                logger.info(f"[TIMING] Pre-CRIU duration (start to dump): {pre_criu_duration:.3f} seconds")
            
            return timing_data
            
        except Exception as e:
            logger.error(f"[TIMING] Error parsing migration timings: {e}")
            import traceback
            logger.error(f"[TIMING] Traceback: {traceback.format_exc()}")
            return None
    
    def write_migration_timings_log(self, pod_name: str, target_node: str, timing_data: Dict):
        """Write migration timing data to log file."""
        try:
            log_entry = {
                "pod_name": pod_name,
                "target_node": target_node,
                "simulation_time": self.current_simulation_time,
                "simulation_datetime": datetime.fromtimestamp(self.current_simulation_time, tz=pytz.UTC).isoformat(),
                "timing_data": timing_data
            }
            
            # Ensure log directory exists
            log_dir = os.path.dirname(self.migration_log_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            
            # Append to log file
            with open(self.migration_log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            logger.info(f"[TIMING] Migration timings written to {self.migration_log_path}")
            
        except Exception as e:
            logger.error(f"[TIMING] Error writing migration timings log: {e}")
            import traceback
            logger.error(f"[TIMING] Traceback: {traceback.format_exc()}")
    
    def find_next_region_breakpoint(self, duration_hours: int = 24) -> Optional[float]:
        """Find the next region breakpoint (when region changes) in the forecast."""
        try:
            forecast_data = self.get_forecast_data_from_metadata(duration_hours)
            if not forecast_data:
                return None
            
            min_forecast = forecast_data.get('min_forecast', {}).get('forecast_data', [])
            if not min_forecast:
                return None
            
            # Find the next breakpoint after current simulation time
            current_datetime = datetime.fromtimestamp(self.current_simulation_time, tz=pytz.UTC)
            
            last_region = None
            for point in min_forecast:
                if len(point) >= 3:
                    timestamp_str = point[0]
                    region = point[1]
                    
                    try:
                        # Parse timestamp (format: "YYYY-MM-DD HH:MM:SS" or with timezone)
                        timestamp_str_clean = timestamp_str.split('+')[0].strip()
                        point_datetime = datetime.strptime(timestamp_str_clean, "%Y-%m-%d %H:%M:%S")
                        point_datetime = pytz.UTC.localize(point_datetime)
                        point_timestamp = point_datetime.timestamp()
                        
                        # Check if this is a breakpoint (region change) and after current time
                        if last_region is not None and region != last_region:
                            if point_timestamp > self.current_simulation_time:
                                logger.info(f"[BREAKPOINT] Found next region breakpoint: {point_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC (region changes from {last_region} to {region})")
                                return point_timestamp
                        
                        last_region = region
                    except Exception as e:
                        logger.warning(f"[BREAKPOINT] Error parsing timestamp {timestamp_str}: {e}")
                        continue
            
            logger.warning("[BREAKPOINT] No region breakpoint found in forecast")
            return None
            
        except Exception as e:
            logger.error(f"[BREAKPOINT] Error finding next region breakpoint: {e}")
            import traceback
            logger.error(f"[BREAKPOINT] Traceback: {traceback.format_exc()}")
            return None
    
    def simulation_time_to_real_time(self, sim_time: float) -> float:
        """Convert simulation time to real time for scheduling.
        
        Maps simulation time to real time by maintaining a 1:1 ratio:
        - If 1 hour of simulation time has passed, schedule 1 hour of real time in the future
        - Formula: real_time = start_real_time + (sim_time - start_sim_time)
        """
        # Calculate how much simulation time has elapsed since start
        sim_time_elapsed = sim_time - self.simulation_start_sim_time
        # Map this to the same amount of real time elapsed
        # Real time = when simulation started (real time) + simulation time elapsed
        return self.simulation_start_real_time + sim_time_elapsed
    
    def reschedule_next_migration(self, namespace: str = "test-namespace", delay_seconds: int = 0):
        """Reschedule the next migration job.

        If delay_seconds > 0, schedule the next check after that many seconds
        (used by Policy 4 adaptive scheduling). Otherwise, schedule right before
        the next region breakpoint.
        """
        try:
            if delay_seconds > 0:
                # Adaptive scheduling: schedule next check after delay_seconds
                next_real_time = time.time() + delay_seconds
                next_datetime = datetime.fromtimestamp(next_real_time, tz=pytz.UTC)
                logger.info(f"[RESCHEDULE] Adaptive: next check in {delay_seconds}s at {next_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")

                if self.scheduler:
                    try:
                        self.scheduler.remove_job('hourly_migration_check')
                    except Exception:
                        pass

                    self.scheduler.add_job(
                        self.hourly_migration_check,
                        trigger=DateTrigger(run_date=next_datetime),
                        id='hourly_migration_check',
                        name='Hourly migration check',
                        replace_existing=True,
                        args=[namespace]
                    )
                    logger.info(f"[RESCHEDULE] Successfully rescheduled with adaptive delay")
                return

            # Find next breakpoint (in simulation time)
            next_breakpoint_sim = self.find_next_region_breakpoint(duration_hours=24)
            if not next_breakpoint_sim:
                logger.warning("[RESCHEDULE] Could not find next breakpoint, using default 1-hour interval")
                return
            
            # Calculate when to start migration (in simulation time)
            # We want CRIU dump to complete right before the breakpoint
            # Use last known durations, or defaults
            criu_dump_duration = self.last_criu_dump_duration if self.last_criu_dump_duration else 2.0
            pre_criu_duration = self.last_pre_criu_duration if self.last_pre_criu_duration else 5.0
            buffer_time = 5.0  # 5 second buffer before breakpoint
            
            # Calculate start time in simulation time: breakpoint - (pre_criu + criu_dump + buffer)
            # This ensures CRIU dump completes right before the breakpoint
            total_migration_time_to_criu_completion = pre_criu_duration + criu_dump_duration
            migration_start_time_sim = next_breakpoint_sim - total_migration_time_to_criu_completion - buffer_time
            
            # Ensure we don't schedule in the past (in simulation time)
            if migration_start_time_sim <= self.current_simulation_time:
                logger.warning(f"[RESCHEDULE] Calculated start time is in the past, using current simulation time + 1 hour")
                migration_start_time_sim = self.current_simulation_time + 3600
            
            # Convert simulation time to real time for APScheduler
            migration_start_time_real = self.simulation_time_to_real_time(migration_start_time_sim)
            next_breakpoint_real = self.simulation_time_to_real_time(next_breakpoint_sim)
            criu_completion_time_sim = next_breakpoint_sim - buffer_time
            criu_completion_time_real = self.simulation_time_to_real_time(criu_completion_time_sim)
            
            migration_start_datetime = datetime.fromtimestamp(migration_start_time_real, tz=pytz.UTC)
            criu_completion_datetime = datetime.fromtimestamp(criu_completion_time_real, tz=pytz.UTC)
            breakpoint_datetime = datetime.fromtimestamp(next_breakpoint_real, tz=pytz.UTC)
            
            logger.info(f"[RESCHEDULE] Next migration scheduled for (real time): {migration_start_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            logger.info(f"[RESCHEDULE] Simulation time: {datetime.fromtimestamp(migration_start_time_sim, tz=pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC")
            logger.info(f"[RESCHEDULE] Pre-CRIU duration: {pre_criu_duration:.3f}s, CRIU dump duration: {criu_dump_duration:.3f}s")
            logger.info(f"[RESCHEDULE] CRIU dump will complete at (real time): {criu_completion_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            logger.info(f"[RESCHEDULE] Region breakpoint occurs at (real time): {breakpoint_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            logger.info(f"[RESCHEDULE] Time buffer before breakpoint: {buffer_time:.3f}s")
            
            # Remove existing job
            if self.scheduler:
                try:
                    self.scheduler.remove_job('hourly_migration_check')
                except Exception:
                    pass
                
                # Schedule new job at calculated real time
                self.scheduler.add_job(
                    self.hourly_migration_check,
                    trigger=DateTrigger(run_date=migration_start_datetime),
                    id='hourly_migration_check',
                    name='Hourly migration check',
                    replace_existing=True,
                    args=[namespace]
                )
                logger.info(f"[RESCHEDULE] Successfully rescheduled migration job")
            
        except Exception as e:
            logger.error(f"[RESCHEDULE] Error rescheduling migration: {e}")
            import traceback
            logger.error(f"[RESCHEDULE] Traceback: {traceback.format_exc()}")
    
    def get_optimal_region_for_pod_forecast(self, pod_info: Dict) -> Optional[str]:
        """Policy 3: Get optimal region based on pod's EXPECTED_DURATION and forecast comparison."""
        try:
            # Get EXPECTED_DURATION from pod annotations
            expected_duration_str = pod_info.get("annotations", {}).get("EXPECTED_DURATION", "12")
            try:
                expected_duration = int(expected_duration_str)
            except ValueError:
                logger.warning(f"[POLICY_3] Invalid EXPECTED_DURATION '{expected_duration_str}', using default 12 hours")
                expected_duration = 12
            
            logger.info(f"[POLICY_3] Pod {pod_info['name']} has EXPECTED_DURATION: {expected_duration} hours")
            
            # Get forecast data for the expected duration
            forecast_data = self.get_forecast_data_from_metadata(duration_hours=expected_duration)
            if not forecast_data:
                logger.error(f"[POLICY_3] Could not get forecast data for pod {pod_info['name']}")
                return None
            
            # Get all region forecasts
            region_forecasts = forecast_data.get('region_forecasts', {})
            if not region_forecasts:
                logger.error(f"[POLICY_3] No region forecasts in response for pod {pod_info['name']}")
                return None
            
            # Calculate total carbon intensity for each region over the duration
            region_totals = {}
            for region, region_data in region_forecasts.items():
                forecast_points = region_data.get('forecast_data', [])
                if not forecast_points:
                    continue
                
                # Sum up all carbon intensity values for this region
                total_intensity = sum(float(point[2]) for point in forecast_points if len(point) >= 3)
                region_totals[region] = total_intensity
                logger.info(f"[POLICY_3] Region {region}: total intensity = {total_intensity:.2f} over {expected_duration} hours")
            
            if not region_totals:
                logger.error(f"[POLICY_3] No valid region totals calculated for pod {pod_info['name']}")
                return None
            
            # Find the region with the lowest total
            optimal_region = min(region_totals.items(), key=lambda x: x[1])[0]
            optimal_total = region_totals[optimal_region]
            
            logger.info(f"[POLICY_3] Optimal region for pod {pod_info['name']}: {optimal_region} (total intensity: {optimal_total:.2f})")
            return optimal_region
            
        except Exception as e:
            logger.error(f"[POLICY_3] Error calculating optimal region for pod {pod_info.get('name', 'unknown')}: {e}")
            import traceback
            logger.error(f"[POLICY_3] Traceback: {traceback.format_exc()}")
            return None
    
    def get_forecast_aware_migration_decision(self, pod_info: Dict) -> Tuple[bool, Optional[str], int]:
        """Policy 4: Forecast-aware adaptive migration with migration cost threshold.

        Returns:
            (should_migrate, target_region, next_check_seconds)
        """
        try:
            pod_name = pod_info["name"]
            pod_node = pod_info["node"]

            # Determine current region from pod's node
            api = client.CoreV1Api()
            current_region = None
            try:
                node_obj = api.read_node(name=pod_node)
                current_region = node_obj.metadata.labels.get("REGION") if node_obj.metadata.labels else None
            except Exception as e:
                logger.warning(f"[POLICY_4] Could not get region for node {pod_node}: {e}")

            if not current_region:
                logger.warning(f"[POLICY_4] No region found for pod {pod_name} on node {pod_node}")
                return False, None, 3600

            logger.info(f"[POLICY_4] Evaluating pod {pod_name} in region {current_region}, forecast_window={self.forecast_window}h")

            # Fetch extended forecast for all regions over the forecast window
            current_datetime = datetime.fromtimestamp(self.current_simulation_time, tz=pytz.UTC)
            end_datetime = current_datetime + timedelta(hours=self.forecast_window)
            start_str = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
            end_str = end_datetime.strftime("%Y-%m-%d %H:%M:%S")

            extended_data = fetch_extended_region_data(self.db_conn, start_str, end_str)
            if not extended_data:
                logger.warning(f"[POLICY_4] No extended forecast data available, falling back to metadata service")
                # Fallback: use metadata service like Policy 3
                forecast_data = self.get_forecast_data_from_metadata(duration_hours=self.forecast_window)
                if not forecast_data:
                    return False, None, 3600

                region_forecasts = forecast_data.get('region_forecasts', {})
                region_scores = {}
                all_intensities = []
                for region, rdata in region_forecasts.items():
                    points = rdata.get('forecast_data', [])
                    score = sum(float(p[2]) for p in points if len(p) >= 3)
                    region_scores[region] = score
                    all_intensities.extend([float(p[2]) for p in points if len(p) >= 3])
            else:
                # Group data by region and compute scores
                region_scores = {}
                all_intensities = []
                for row in extended_data:
                    # row: [timestamp, region, intensity, wind, solar, pct_renewable]
                    region = row[1]
                    intensity = row[2]
                    if region not in region_scores:
                        region_scores[region] = 0.0
                    region_scores[region] += intensity
                    all_intensities.append(intensity)

            if not region_scores:
                logger.warning(f"[POLICY_4] No region scores computed")
                return False, None, 3600

            # Log region scores
            for region, score in sorted(region_scores.items()):
                logger.info(f"[POLICY_4] Region {region}: cumulative intensity score = {score:.2f}")

            # Find best region
            best_region = min(region_scores, key=region_scores.get)
            best_score = region_scores[best_region]
            current_score = region_scores.get(current_region, float('inf'))

            # Compute migration benefit
            benefit = current_score - best_score
            logger.info(f"[POLICY_4] Current region {current_region} score={current_score:.2f}, "
                       f"best region {best_region} score={best_score:.2f}, benefit={benefit:.2f}")

            # Compute migration cost (carbon overhead of CRIU dump/restore)
            criu_dump_dur = self.last_criu_dump_duration if self.last_criu_dump_duration else 2.0
            pre_criu_dur = self.last_pre_criu_duration if self.last_pre_criu_duration else 5.0
            migration_seconds = pre_criu_dur + criu_dump_dur

            # Get current and target intensities for this hour
            current_intensity = current_score / max(self.forecast_window, 1)
            target_intensity = best_score / max(self.forecast_window, 1)
            migration_carbon = (migration_seconds / 3600.0) * max(current_intensity, target_intensity)

            logger.info(f"[POLICY_4] Migration cost: {migration_carbon:.4f} gCO2 "
                       f"(migration_seconds={migration_seconds:.1f}s, "
                       f"cost_multiplier={self.cost_multiplier})")

            # Decision: migrate only if benefit exceeds cost * multiplier
            threshold = migration_carbon * self.cost_multiplier
            should_migrate = benefit > threshold

            logger.info(f"[POLICY_4] Decision: benefit={benefit:.2f} vs threshold={threshold:.4f} -> "
                       f"{'MIGRATE' if should_migrate else 'STAY'}")

            # Adaptive scheduling: compute volatility
            import statistics
            if len(all_intensities) >= 2:
                volatility = statistics.stdev(all_intensities)
            else:
                volatility = 0.0

            if volatility > 50:
                next_check_seconds = 1800  # 30 minutes
                logger.info(f"[POLICY_4] High volatility (σ={volatility:.1f} > 50): recheck in 30 min")
            else:
                next_check_seconds = 7200  # 2 hours
                logger.info(f"[POLICY_4] Low volatility (σ={volatility:.1f} ≤ 50): recheck in 2 hours")

            target = best_region if should_migrate else None
            return should_migrate, target, next_check_seconds

        except Exception as e:
            logger.error(f"[POLICY_4] Error in forecast-aware decision for pod {pod_info.get('name', 'unknown')}: {e}")
            import traceback
            logger.error(f"[POLICY_4] Traceback: {traceback.format_exc()}")
            return False, None, 3600

    def get_best_region_now(self, pod_info: Dict) -> Tuple[bool, Optional[str]]:
        """Policy 5: Always migrate to the region with lowest carbon intensity for the NEXT hour.

        Uses perfect information (lookahead): queries the intensity for the upcoming
        hour so the pod is already in the best region when that hour begins.

        Returns:
            (should_migrate, target_region)
        """
        try:
            pod_name = pod_info["name"]
            pod_node = pod_info["node"]

            # Determine current region
            api = client.CoreV1Api()
            current_region = None
            try:
                node_obj = api.read_node(name=pod_node)
                current_region = node_obj.metadata.labels.get("REGION") if node_obj.metadata.labels else None
            except Exception as e:
                logger.warning(f"[POLICY_5] Could not get region for node {pod_node}: {e}")

            if not current_region:
                logger.warning(f"[POLICY_5] No region found for pod {pod_name} on node {pod_node}")
                return False, None

            # Fetch intensity for all regions for the NEXT hour (perfect lookahead)
            next_hour_datetime = datetime.fromtimestamp(self.current_simulation_time, tz=pytz.UTC) + timedelta(hours=1)
            end_datetime = next_hour_datetime + timedelta(hours=1)
            start_str = next_hour_datetime.strftime("%Y-%m-%d %H:%M:%S")
            end_str = end_datetime.strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[POLICY_5] Lookahead: querying intensity for next hour {start_str} - {end_str}")

            extended_data = fetch_extended_region_data(self.db_conn, start_str, end_str)

            if extended_data:
                region_intensity = {}
                for row in extended_data:
                    region = row[1]
                    intensity = row[2]
                    # Take the first (closest) value per region
                    if region not in region_intensity:
                        region_intensity[region] = intensity

                # If current region is missing from all-regions query, fetch it explicitly
                if current_region not in region_intensity:
                    logger.info(f"[POLICY_5] Current region {current_region} missing from all-regions query, fetching directly")
                    current_data = fetch_extended_region_data(self.db_conn, start_str, end_str, region=current_region)
                    if current_data:
                        region_intensity[current_region] = current_data[0][2]
            else:
                # Fallback to metadata service — request 2 hours and use the second point (next hour)
                logger.info(f"[POLICY_5] No DB data, falling back to metadata service")
                forecast_data = self.get_forecast_data_from_metadata(duration_hours=2)
                if not forecast_data:
                    return False, None

                region_intensity = {}
                for region, rdata in forecast_data.get('region_forecasts', {}).items():
                    points = rdata.get('forecast_data', [])
                    # Use second point (next hour) if available, otherwise first
                    if len(points) >= 2 and len(points[1]) >= 3:
                        region_intensity[region] = float(points[1][2])
                    elif points and len(points[0]) >= 3:
                        region_intensity[region] = float(points[0][2])

            if not region_intensity:
                logger.warning(f"[POLICY_5] No region intensity data available")
                return False, None

            # If current region has no data, we can't make a comparison — stay put
            if current_region not in region_intensity:
                logger.warning(f"[POLICY_5] No intensity data for current region {current_region}, staying put")
                return False, None

            # Log all region intensities for the next hour
            for region, intensity in sorted(region_intensity.items()):
                marker = " <-- current" if region == current_region else ""
                logger.info(f"[POLICY_5] Region {region}: next-hour intensity = {intensity:.2f}{marker}")

            # Find the best region for the next hour
            best_region = min(region_intensity, key=region_intensity.get)
            current_region_next_intensity = region_intensity[current_region]
            best_intensity = region_intensity[best_region]

            if best_region != current_region and best_intensity < current_region_next_intensity:
                logger.info(f"[POLICY_5] MIGRATE (lookahead): {current_region} ({current_region_next_intensity:.2f}) -> "
                           f"{best_region} ({best_intensity:.2f}) for next hour")
                return True, best_region
            else:
                logger.info(f"[POLICY_5] STAY: {current_region} ({current_region_next_intensity:.2f}) is already best for next hour")
                return False, None

        except Exception as e:
            logger.error(f"[POLICY_5] Error for pod {pod_info.get('name', 'unknown')}: {e}")
            import traceback
            logger.error(f"[POLICY_5] Traceback: {traceback.format_exc()}")
            return False, None

    def cleanup_stale_pods(self, namespace: str = "test-namespace"):
        """Delete old pods from migration chains, keeping only the latest per chain."""
        try:
            api = client.CoreV1Api()
            pods = api.list_namespaced_pod(namespace=namespace)

            # Group all pods by base name
            chains = {}  # base_name -> [(counter, pod_name, phase)]
            for pod in pods.items:
                name = pod.metadata.name
                base = self._extract_base_pod_name(name)
                counter = self._get_pod_counter(name, base)
                phase = pod.status.phase or "Unknown"
                if base not in chains:
                    chains[base] = []
                chains[base].append((counter, name, phase))

            for base, members in chains.items():
                if len(members) <= 1:
                    continue

                # Sort by counter descending — highest counter is the latest
                members.sort(key=lambda x: x[0], reverse=True)
                latest = members[0]

                for counter, name, phase in members[1:]:
                    # Delete all older pods in the chain
                    try:
                        api.delete_namespaced_pod(name=name, namespace=namespace)
                        logger.info(f"[CLEANUP] Deleted stale pod {name} (phase={phase}, chain={base})")
                    except ApiException as e:
                        if e.status != 404:
                            logger.warning(f"[CLEANUP] Failed to delete {name}: {e.reason}")

        except Exception as e:
            logger.warning(f"[CLEANUP] Error during stale pod cleanup: {e}")

    def hourly_migration_check(self, namespace: str = "test-namespace"):
        """Check every hour if pods need to be migrated based on scheduling policy."""
        try:
            logger.info("=" * 80)
            logger.info(f"[HOURLY_CHECK] Starting hourly migration check (Policy {self.scheduling_policy})")

            # Clean up stale pods from previous migrations
            self.cleanup_stale_pods(namespace)

            # Update current simulation time
            self.current_simulation_time += 3600 * self.sim_hours_per_check

            current_datetime = datetime.fromtimestamp(self.current_simulation_time, tz=pytz.UTC)
            logger.info(f"[HOURLY_CHECK] Current simulation time: {current_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            # Discover all pods in the namespace
            pods = self.discover_pods_for_migration(namespace)
            if not pods:
                logger.info("[HOURLY_CHECK] No pods found to check")
                return
            
            # Check each pod and migrate if needed based on policy
            migrations_attempted = 0
            migrations_successful = 0
            should_reschedule = False
            policy4_next_check_seconds = 0  # Track adaptive delay from Policy 4
            
            for pod_info in pods:
                pod_name = pod_info["name"]
                pod_node = pod_info["node"]
                pod_region = pod_info.get("region")
                
                # Determine target region based on policy
                if self.scheduling_policy == 2:
                    # Policy 2: Migrate to minimum region for current hour
                    target_region = self.get_minimum_region_from_metadata(duration_hours=24)
                    if not target_region:
                        logger.warning(f"[HOURLY_CHECK] Could not determine minimum region for pod {pod_name}, skipping")
                        continue
                elif self.scheduling_policy == 3:
                    # Policy 3: Each pod gets its own optimal region based on forecast
                    target_region = self.get_optimal_region_for_pod_forecast(pod_info)
                    if not target_region:
                        logger.warning(f"[HOURLY_CHECK] Could not determine optimal region for pod {pod_name}, skipping")
                        continue
                elif self.scheduling_policy == 4:
                    # Policy 4: Forecast-aware adaptive migration with cost threshold
                    should_migrate, target_region, next_check_seconds = self.get_forecast_aware_migration_decision(pod_info)
                    policy4_next_check_seconds = next_check_seconds
                    if not should_migrate:
                        logger.info(f"[HOURLY_CHECK] Policy 4: No migration needed for pod {pod_name}")
                        # Reschedule with adaptive delay
                        self.reschedule_next_migration(namespace, delay_seconds=next_check_seconds)
                        continue
                    if not target_region:
                        logger.warning(f"[HOURLY_CHECK] Policy 4: Migration recommended but no target region for pod {pod_name}")
                        continue
                elif self.scheduling_policy == 5:
                    # Policy 5: Always move to best region, no heuristic
                    should_migrate, target_region = self.get_best_region_now(pod_info)
                    if not should_migrate:
                        logger.info(f"[HOURLY_CHECK] Policy 5: Pod {pod_name} already in best region")
                        continue
                    if not target_region:
                        logger.warning(f"[HOURLY_CHECK] Policy 5: No target region for pod {pod_name}")
                        continue
                else:
                    logger.warning(f"[HOURLY_CHECK] Policy {self.scheduling_policy} does not support hourly checks")
                    continue
                
                # Find nodes in the target region
                api = client.CoreV1Api()
                nodes = api.list_node()
                target_region_nodes = []
                for node in nodes.items:
                    region = node.metadata.labels.get("REGION") if node.metadata.labels else None
                    if region == target_region:
                        target_region_nodes.append(node.metadata.name)
                
                if not target_region_nodes:
                    logger.warning(f"[HOURLY_CHECK] No nodes found in target region {target_region} for pod {pod_name}")
                    continue
                
                # Check if pod is already on a node in the target region
                if pod_node in target_region_nodes:
                    logger.info(f"[HOURLY_CHECK] Pod {pod_name} is already on node {pod_node} in target region {target_region}")
                    continue
                
                # Pod needs to be migrated to target region
                logger.info(f"[HOURLY_CHECK] Pod {pod_name} on node {pod_node} needs migration to region {target_region}")

                # Find a target node in the target region (excludes source node)
                target_node = self.find_target_node_for_region(target_region, pod_node)
                if not target_node:
                    logger.warning(f"[HOURLY_CHECK] Could not find target node for pod {pod_name}")
                    continue

                # Safety: never migrate to the same node
                if target_node == pod_node:
                    logger.info(f"[HOURLY_CHECK] Pod {pod_name} already on target node {target_node}, skipping")
                    continue

                # Perform migration
                logger.info(f"[HOURLY_CHECK] Migrating {pod_name} from {pod_node} to {target_node} (region: {target_region})")
                migrations_attempted += 1
                
                migration_result = self.migrate_pod(
                    namespace=namespace,
                    pod=pod_name,
                    target_node=target_node,
                    delete_original=True,
                    debug=True
                )

                if migration_result.get("success"):
                    migrations_successful += 1
                    logger.info(f"[HOURLY_CHECK] ✓ Successfully migrated {pod_name} to {target_node}")

                    # Ensure the old pod is deleted (migration service may not have done it)
                    try:
                        api = client.CoreV1Api()
                        api.delete_namespaced_pod(name=pod_name, namespace=namespace)
                        logger.info(f"[HOURLY_CHECK] Deleted original pod {pod_name}")
                    except ApiException as e:
                        if e.status == 404:
                            logger.info(f"[HOURLY_CHECK] Original pod {pod_name} already deleted")
                        else:
                            logger.warning(f"[HOURLY_CHECK] Failed to delete original pod {pod_name}: {e}")

                    # Parse and log migration timings
                    timing_data = self.parse_migration_timings(migration_result)
                    if timing_data:
                        self.write_migration_timings_log(pod_name, target_node, timing_data)
                        should_reschedule = True  # Mark that we should reschedule after processing all pods
                    else:
                        logger.warning(f"[HOURLY_CHECK] Could not parse migration timings for {pod_name}")
                else:
                    error_msg = migration_result.get("error", "Unknown error")
                    logger.error(f"[HOURLY_CHECK] ✗ Failed to migrate {pod_name}: {error_msg}")
            
            # Reschedule next migration after all pods are processed (if any migration was successful)
            if should_reschedule and migrations_successful > 0:
                if self.scheduling_policy == 5:
                    # Policy 5: Keep the regular interval, no special rescheduling
                    logger.info(f"[HOURLY_CHECK] Policy 5: Continuing with regular {self.check_interval_seconds}s check interval")
                elif self.scheduling_policy == 4 and policy4_next_check_seconds > 0:
                    logger.info(f"[HOURLY_CHECK] Policy 4: Rescheduling with adaptive delay of {policy4_next_check_seconds}s...")
                    self.reschedule_next_migration(namespace, delay_seconds=policy4_next_check_seconds)
                else:
                    logger.info("[HOURLY_CHECK] Rescheduling next migration based on timing analysis...")
                    self.reschedule_next_migration(namespace)
            
            logger.info(f"[HOURLY_CHECK] Migration check completed: {migrations_attempted} attempted, {migrations_successful} successful")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"[HOURLY_CHECK] Error during hourly migration check: {e}")
            import traceback
            logger.error(f"[HOURLY_CHECK] Traceback: {traceback.format_exc()}")
    
    def run_migration_test(self, namespace: str = "test-namespace", 
                          log_duration: int = 120) -> Dict:
        """Run a complete migration workflow (matches test.sh and live_migration.py patterns)."""
        logger.info("=" * 80)
        logger.info("[MIGRATION_TEST] Starting migration workflow")
        logger.info(f"[MIGRATION_TEST] Scheduler time: {datetime.fromtimestamp(self.scheduler_time, tz=pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.info("=" * 80)
        
        test_results = {
            "pods_discovered": 0,
            "migrations_attempted": 0,
            "migrations_successful": 0,
            "errors": []
        }
        
        try:
            # Step 1: Discover pods for migration
            logger.info("[MIGRATION_TEST] Step 1: Discovering pods for migration...")
            candidate_pods = self.discover_pods_for_migration(namespace)
            test_results["pods_discovered"] = len(candidate_pods)
            
            if not candidate_pods:
                test_results["errors"].append("No candidate pods found for migration")
                logger.warning("[MIGRATION_TEST] No pods found to migrate")
                return test_results
            
            logger.info(f"[MIGRATION_TEST] Found {len(candidate_pods)} candidate pods")
            
            # Step 2: Migrate each candidate pod
            for pod_info in candidate_pods:
                pod_name = pod_info["name"]
                source_node = pod_info["node"]
                
                logger.info(f"[MIGRATION_TEST] Processing pod: {pod_name} on node {source_node}")
                
                # Step 3: Find optimal target node based on scheduling policy
                logger.info(f"[MIGRATION_TEST] Finding optimal target node for {pod_name} (Policy {self.scheduling_policy})...")
                
                if self.scheduling_policy == 1:
                    # Policy 1: Initial placement to lowest region at runtime
                    min_region = self.get_minimum_region_from_metadata(duration_hours=24)
                    if min_region:
                        target_node = self.find_target_node_for_region(min_region, source_node)
                    else:
                        target_node = self.find_optimal_target_node(source_node, namespace)
                elif self.scheduling_policy == 2:
                    # Policy 2: Migrate to minimum region (same as hourly check)
                    min_region = self.get_minimum_region_from_metadata(duration_hours=24)
                    if min_region:
                        target_node = self.find_target_node_for_region(min_region, source_node)
                    else:
                        target_node = self.find_optimal_target_node(source_node, namespace)
                elif self.scheduling_policy == 3:
                    # Policy 3: Forecast-based optimal region
                    optimal_region = self.get_optimal_region_for_pod_forecast(pod_info)
                    if optimal_region:
                        target_node = self.find_target_node_for_region(optimal_region, source_node)
                    else:
                        # Fallback to minimum region
                        min_region = self.get_minimum_region_from_metadata(duration_hours=24)
                        if min_region:
                            target_node = self.find_target_node_for_region(min_region, source_node)
                        else:
                            target_node = self.find_optimal_target_node(source_node, namespace)
                elif self.scheduling_policy == 4:
                    # Policy 4: Forecast-aware adaptive migration
                    should_migrate, target_region, _ = self.get_forecast_aware_migration_decision(pod_info)
                    if should_migrate and target_region:
                        target_node = self.find_target_node_for_region(target_region, source_node)
                    else:
                        logger.info(f"[MIGRATION_TEST] Policy 4: No migration needed for {pod_name}")
                        continue
                elif self.scheduling_policy == 5:
                    # Policy 5: Always best region
                    should_migrate, target_region = self.get_best_region_now(pod_info)
                    if should_migrate and target_region:
                        target_node = self.find_target_node_for_region(target_region, source_node)
                    else:
                        logger.info(f"[MIGRATION_TEST] Policy 5: Already in best region for {pod_name}")
                        continue
                else:
                    # Fallback to old method
                    target_node = self.find_optimal_target_node(source_node, namespace)
                
                if not target_node:
                    test_results["errors"].append(f"Could not find target node for pod {pod_name}")
                    logger.warning(f"[MIGRATION_TEST] Skipping {pod_name} - no target node found")
                    continue
                
                logger.info(f"[MIGRATION_TEST] Target node for {pod_name}: {target_node}")
                
                # Get target region from target node for pod naming
                target_region = None
                try:
                    api = client.CoreV1Api()
                    target_node_obj = api.read_node(name=target_node)
                    target_region = target_node_obj.metadata.labels.get("REGION") if target_node_obj.metadata.labels else None
                except Exception as e:
                    logger.warning(f"[MIGRATION_TEST] Could not get target region from node {target_node}: {e}")
                
                # Step 4: Perform migration
                logger.info(f"[MIGRATION_TEST] Migrating {pod_name} from {source_node} to {target_node} (region: {target_region or 'unknown'})...")
                test_results["migrations_attempted"] += 1
                
                migration_result = self.migrate_pod(
                    namespace=namespace,
                    pod=pod_name,
                    target_node=target_node,
                    delete_original=True,
                    debug=True
                )

                if migration_result.get("success"):
                    test_results["migrations_successful"] += 1
                    logger.info(f"[MIGRATION_TEST] ✓ Migration of {pod_name} completed successfully")
                    
                    # Step 5: Monitor migrated pod (if it has a new name)
                    # The migration service creates a new pod with {base_pod}-{counter} naming
                    # Extract base pod name (strip numeric suffixes if present)
                    base_pod_name = self._extract_base_pod_name(pod_name)
                    
                    # Find the next expected pod name by checking existing pods
                    # This matches the logic in the migration service
                    migrated_pod_name = self._get_next_expected_pod_name(base_pod_name, namespace)
                    
                    if self.wait_for_pod_ready(migrated_pod_name, namespace, timeout=300):
                        logger.info(f"[MIGRATION_TEST] ✓ Migrated pod {migrated_pod_name} is ready")
                        
                        # Stream logs for monitoring
                        logger.info(f"[MIGRATION_TEST] Monitoring {migrated_pod_name} for {log_duration} seconds...")
                        self.stream_pod_logs(migrated_pod_name, namespace, duration=log_duration)
                    else:
                        logger.warning(f"[MIGRATION_TEST] Migrated pod {migrated_pod_name} did not become ready")
                else:
                    error_msg = migration_result.get("error", "Unknown error")
                    test_results["errors"].append(f"Migration of {pod_name} failed: {error_msg}")
                    logger.error(f"[MIGRATION_TEST] ✗ Migration of {pod_name} failed: {error_msg}")
            
        except Exception as e:
            logger.error(f"[MIGRATION_TEST] Error during migration workflow: {e}")
            test_results["errors"].append(str(e))
            import traceback
            logger.error(f"[MIGRATION_TEST] Traceback: {traceback.format_exc()}")
        
        # Print test results
        logger.info("=" * 80)
        logger.info("[MIGRATION_TEST] Migration Workflow Results")
        logger.info("=" * 80)
        logger.info(f"Pods Discovered: {test_results['pods_discovered']}")
        logger.info(f"Migrations Attempted: {test_results['migrations_attempted']}")
        logger.info(f"Migrations Successful: {test_results['migrations_successful']}")
        
        if test_results["errors"]:
            logger.error("Errors encountered:")
            for error in test_results["errors"]:
                logger.error(f"  - {error}")
        
        logger.info("=" * 80)
        return test_results


def main():
    """Main entry point for the KubeFlex Controller (matches live_migration.py and test.sh patterns)."""
    parser = argparse.ArgumentParser(
        description='KubeFlex Controller - Carbon-aware pod migration scheduler',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use current time (within data range)
  python main.py --namespace test-namespace
  
  # Set scheduler to specific timestamp (Unix epoch)
  python main.py --scheduler-time 1609459200 --namespace test-namespace
  
  # Set scheduler to timestamp from data range (2021-01-01 00:00:00)
  python main.py --scheduler-time 1609459200

Valid timestamp range: 1577836800 (2020-01-01 00:00:00) to 1672527600 (2022-12-31 23:00:00)

Scheduling Policies:
  1 - Initial Placement Only: Assign pods to lowest region at runtime, no migrations
  2 - Hourly Migration: Automatically migrate all pods to minimum region every hour
  3 - Forecast-Based: For each pod, compare forecasts for all regions over EXPECTED_DURATION
      and migrate to the region with lowest total carbon intensity
  4 - Forecast-Aware Adaptive: Sliding-window forecast with migration cost threshold.
      Only migrates when carbon benefit exceeds migration cost. Adaptive recheck intervals
      based on volatility. Configure via FORECAST_WINDOW and MIGRATION_COST_MULTIPLIER env vars
  5 - Always-Best-Region: Migrate to the lowest carbon intensity region every check.
      No heuristic — if any region is better right now, migrate immediately
        """
    )
    parser.add_argument('--namespace', default='test-namespace',
                       help='Kubernetes namespace (default: test-namespace)')
    parser.add_argument('--scheduler-time', type=float, default=None,
                       help='Unix timestamp for scheduler clock (default: from SCHEDULER_TIME env var or current time, clamped to data range 1577836800-1672527600)')
    parser.add_argument('--log-duration', type=int, default=120,
                       help='Duration to stream logs after migration (seconds, default: 120)')
    parser.add_argument('--skip-migration', action='store_true',
                       help='Skip automatic migration on startup (default: False, migration runs automatically)')
    parser.add_argument('--scheduling-policy', type=int, choices=[1, 2, 3, 4, 5], default=None,
                       help='Scheduling policy: 1=initial placement only, 2=hourly migration to minimum, 3=forecast-based optimal, 4=forecast-aware adaptive, 5=always-best-region (default: from SCHEDULING_POLICY env var or 3)')
    
    args = parser.parse_args()
    
    # Get scheduler time from argument, environment variable, or default
    scheduler_time = args.scheduler_time
    if scheduler_time is None:
        # Try to read from environment variable (set by ConfigMap)
        scheduler_time_str = os.getenv('SCHEDULER_TIME')
        if scheduler_time_str:
            try:
                scheduler_time = float(scheduler_time_str)
                logger.info(f"Using scheduler time from SCHEDULER_TIME environment variable: {scheduler_time}")
            except ValueError:
                logger.warning(f"Invalid SCHEDULER_TIME environment variable: {scheduler_time_str}, using default")
                scheduler_time = None
    
    # Get scheduling policy from argument, environment variable, or default
    scheduling_policy = args.scheduling_policy
    if scheduling_policy is None:
        # Try to read from environment variable (set by ConfigMap)
        scheduling_policy_str = os.getenv('SCHEDULING_POLICY')
        if scheduling_policy_str:
            try:
                scheduling_policy = int(scheduling_policy_str)
                if scheduling_policy not in [1, 2, 3, 4, 5]:
                    raise ValueError(f"Invalid scheduling policy: {scheduling_policy}")
                logger.info(f"Using scheduling policy from SCHEDULING_POLICY environment variable: {scheduling_policy}")
            except (ValueError, TypeError):
                logger.warning(f"Invalid SCHEDULING_POLICY environment variable: {scheduling_policy_str}, using default 3")
                scheduling_policy = 3
        else:
            scheduling_policy = 3  # Default to policy 3
            logger.info(f"No SCHEDULING_POLICY environment variable, using default: {scheduling_policy}")
    
    # Initialize controller with scheduler time and scheduling policy
    try:
        controller = KubeFlexController(scheduler_time=scheduler_time, scheduling_policy=scheduling_policy)
    except ValueError as e:
        logger.error(f"Invalid configuration: {e}")
        sys.exit(1)
    
    if not controller.initialize():
        logger.error("Failed to initialize controller")
        sys.exit(1)
    
    # Run migration workflow only if not skipped
    if args.skip_migration:
        logger.info("=" * 80)
        logger.info("KubeFlex Controller - Running in scheduled mode")
        logger.info("Initial migration workflow skipped (--skip-migration flag set)")
        logger.info("Hourly migration checks are active and will run automatically")
        logger.info("=" * 80)
        logger.info("Controller initialized and ready. Hourly checks will migrate pods to minimum region.")
        # Keep the controller running
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Controller shutting down...")
            if controller.scheduler:
                controller.scheduler.shutdown()
    else:
        logger.info("=" * 80)
        logger.info("KubeFlex Controller - Starting Initial Migration Workflow")
        logger.info("=" * 80)
        
        results = controller.run_migration_test(
            namespace=args.namespace,
            log_duration=args.log_duration
        )
        
        logger.info("=" * 80)
        logger.info("Initial migration workflow completed")
        logger.info("Controller will continue running with hourly migration checks")
        logger.info("=" * 80)
        
        # Keep the controller running for hourly checks
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Controller shutting down...")
            if controller.scheduler:
                controller.scheduler.shutdown()
            
            # Exit with appropriate code on shutdown
            if results["migrations_successful"] > 0:
                logger.info("Migration workflow completed with at least one successful migration")
                sys.exit(0)
            elif results["migrations_attempted"] > 0:
                logger.warning("Migration workflow completed but no migrations were successful")
                sys.exit(1)
            else:
                logger.error("Migration workflow completed but no migrations were attempted")
                sys.exit(1)


if __name__ == "__main__":
    main()

