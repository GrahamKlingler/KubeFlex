from datetime import datetime, timedelta
import requests
import json
import time
import psycopg2
import os
import sys
import logging
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from prettytable import PrettyTable
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection parameters
db_config = {
    'host': 'db-service',
    'port': 5432,
    'dbname': 'postgres',
    'user': 'sfarokhi',
    'password': 'wordpass'
}

min_query = """
CREATE OR REPLACE FUNCTION get_min_intensity_records(
    start_date TIMESTAMP,
    end_date TIMESTAMP
)
RETURNS TEXT[] AS $$
DECLARE
    r RECORD;
    results_array TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOR r IN
        SELECT source, datetime, carbon_intensity_direct_avg
        FROM public.table
        WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
        AND (datetime::TIMESTAMP, carbon_intensity_direct_avg) IN (
            SELECT datetime::TIMESTAMP, MIN(carbon_intensity_direct_avg)
            FROM public.table
            WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
            GROUP BY datetime::TIMESTAMP
        )
        ORDER BY datetime::TIMESTAMP DESC
    LOOP
        results_array := array_append(results_array, 
            r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
        );
    END LOOP;

    RETURN results_array;
END;
$$ LANGUAGE plpgsql; 
"""

general_query = """
CREATE OR REPLACE FUNCTION get_records_by_source(
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    source_list TEXT[]
)
RETURNS TEXT[] AS $$
DECLARE
    r RECORD;
    results_array TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOR r IN
        SELECT source, datetime, carbon_intensity_direct_avg
        FROM public.table
        WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
        AND source = ANY(source_list)
        ORDER BY datetime::TIMESTAMP DESC
    LOOP
        results_array := array_append(results_array, 
            r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
        );
    END LOOP;

    RETURN results_array;
END;
$$ LANGUAGE plpgsql;
"""

# Connect to PostgreSQL database
def connect_to_db(db_params):
    """Connect to PostgreSQL database."""
    try:
        connection = psycopg2.connect(**db_params)
        logger.info("Successfully connected to PostgreSQL database")
        return connection
    except psycopg2.Error as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        raise

# Query the minimum carbon emissions from the db from the given start and end date
def fetch_min_slope(conn, start_date, end_date):
    try:
        with conn.cursor() as cur:
            cur.execute(min_query)  # Create or replace the function
            cur.execute("SELECT get_min_intensity_records(%s, %s);", (start_date, end_date))
            result = cur.fetchone()[0]  # [0] because fetchone() returns a tuple
            # logger.info("Fetched results array:", result)

            min_region, min_ts, min_intensity = [], [], [] 
            for record in sorted(result):

                min_region.append(record.split(" | ")[0])
                min_ts.append(record.split(" | ")[1])
                min_intensity.append(float(record.split(" | ")[2]))

            return min_region, min_ts, min_intensity

    except Exception as e:
        logger.info(f"Error fetching results: {e}")

# Query the minimum carbon emissions from the db from the given start and end date
def fetch_region_slopes(conn, start_date, end_date, regions):
    try:
        with conn.cursor() as cur:
            cur.execute(general_query)  # Create or replace the function
            cur.execute("SELECT get_records_by_source(%s, %s, %s);", (start_date, end_date, regions))
            result = cur.fetchone()[0]  # [0] because fetchone() returns a tuple
            # logger.info("Fetched results array:", result)

            min_region, min_ts, min_intensity = [], [], [] 
            for record in sorted(result):

                min_region.append(record.split(" | ")[0])
                min_ts.append(record.split(" | ")[1])
                min_intensity.append(float(record.split(" | ")[2]))

            return min_region, min_ts, min_intensity

    except Exception as e:
        logger.info(f"Error fetching results: {e}")

# URL of the cAdvisor API
def get_cadvisor_url():
    return os.getenv('CADVISOR_URL', 'http://127.0.0.1:8080')

# Connect to the cAdvisor API
def create_cadvisor_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[600, 502, 503, 504]
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    return session

# Wait for cAdvisor to be ready
def wait_for_cadvisor(session, url):
    logger.info("Waiting for cAdvisor to be ready...")
    for _ in range(30):
        try:
            response = session.get(f"{url}/api/v1.3/docker/")
            if response.status_code == 200:
                logger.info("cAdvisor is ready")
                return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to cAdvisor: {e}")
        time.sleep(10)
    return False

# Collect metrics from cAdvisor
def fetch_cadvisor_metrics(session, api_url, endpoint, selector=None):
    try:
        url = f"{api_url}/api/v1.3/docker{endpoint}"
        
        # Filter containers after fetching
        response = session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # NEED TO ADD LATER SUPPORT FOR KUBERNETES POD/CONTAINER NAMES
        if selector:
            namespace = selector.split('=')[1]
            filtered_data = {}
            for container_id, container_info in data.items():
                labels = container_info.get('spec', {}).get('labels', {})
                container_namespace = labels.get('io.kubernetes.pod.namespace')
                if container_namespace == namespace:
                    filtered_data[container_id] = container_info
            data = filtered_data
            
        logger.info(f"Found {len(data)} containers in namespace {namespace}")
        return data
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        return None

# Extract the friendly name of the container from cadvisor 
def get_friendly_name(container_info):
    # Check for Kubernetes labels first
    if 'labels' in container_info.get('spec', {}):
        labels = container_info['spec']['labels']
        k8s_name = labels.get('io.kubernetes.pod.name')
        k8s_namespace = labels.get('io.kubernetes.pod.namespace')
        if k8s_name and k8s_namespace:
            return f"{k8s_namespace}/{k8s_name}"
    
    # Fall back to Docker Compose service name
    labels = container_info.get('spec', {}).get('labels', {})
    compose_service = labels.get('com.docker.compose.service')
    if compose_service:
        return compose_service
    
    # Finally try aliases
    aliases = container_info.get('aliases', [])
    filtered_aliases = [a for a in aliases if not a.startswith('/') and len(a) < 64]
    return filtered_aliases[0] if filtered_aliases else container_info.get('name', 'unknown')

# Lint the essential metrics from the cAdvisor response
def collect_container_metrics(containers):
    data = {}
    for container_id, container_info in containers.items():
        if not container_info.get('stats'):
            continue
            
        latest_stats = container_info['stats'][-1]
        
        # Extract container name from aliases
        friendly_name = get_friendly_name(container_info)
        data[friendly_name] = {
            'cpu': {
                'total_usage': latest_stats['cpu']['usage']['total'],
                'user_mode_usage': latest_stats['cpu']['usage']['user'],
                'system_mode_usage': latest_stats['cpu']['usage']['system']
            },
            'memory': {
                'current_usage': latest_stats['memory']['usage'],
                'max_usage': latest_stats['memory']['max_usage'],
                'cache': latest_stats['memory']['cache'],
                'rss': latest_stats['memory']['rss'],
                'swap': latest_stats['memory']['swap'],
                'working_set': latest_stats['memory']['working_set']
            },
            'network': {
                'tx_bytes': latest_stats['network']['tx_bytes'],
                'rx_bytes': latest_stats['network']['rx_bytes'],
                'tx_packets': latest_stats['network']['tx_packets'],
                'rx_packets': latest_stats['network']['rx_packets'],
                'tx_errors': latest_stats['network']['tx_errors'],
                'rx_errors': latest_stats['network']['rx_errors']
            },
            'timestamp': latest_stats['timestamp'],
            'container_id': container_id
        }
    logger.info("Data Extracted")
    return data

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

# Format dictionary data for table display
def format_dict_for_table(data_dict):
    """Format dictionary data for table display"""
    if not data_dict:
        return ""
    
    result = []
    for k, v in data_dict.items():
        result.append(f"{k}={v}")
    
    return "\n".join(result)

# Get the status of a pod
def get_pod_status(pod):
    """Get the status of a pod"""
    if pod.status.phase:
        if pod.status.reason:
            return f"{pod.status.phase}: {pod.status.reason}"
        return pod.status.phase
    
    return "Unknown"

# List all resources in a namespace with k8s library
def list_resources(namespace, output_format="table", include_system=False) -> list:
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

    # # Format and return the results based on output format
    # if output_format == "json":
    #     logger.info(json.dumps(all_resources, default=str, indent=2))
    # else:  # table format
    #     if not all_resources:
    #         logger.info(f"No resources found in namespace '{namespace}'")
    #         return
            
    #     table = PrettyTable()
    #     table.field_names = ["Kind", "Name", "Labels", "Annotations", "State", "Age"]
    #     table.align = "l"
    #     table.max_width = 40
        
    #     for resource in all_resources:
    #         # Format labels and annotations for better readability
    #         labels_str = format_dict_for_table(resource['labels'])
    #         annotations_str = format_dict_for_table(resource['annotations'])
            
    #         table.add_row([
    #             resource['kind'],
    #             resource['name'],
    #             labels_str,
    #             annotations_str,
    #             resource['state'],
    #             resource['age']
    #         ])
        
    #     logger.info(table)
    
    return all_resources

def main():

    # Load environment variables
    pod_selector = os.getenv('POD_SELECTOR', 'io.kubernetes.pod.namespace=monitor')
    interval = int(os.getenv('POLLING_INTERVAL', '300'))

    # Connect to cadvisor API
    cadvisor_url = get_cadvisor_url()
    session = create_cadvisor_session()
    if not wait_for_cadvisor(session, cadvisor_url):
        logger.error("cAdvisor not available after timeout")
        return
    
    # Connect to PostgreSQL database
    db_conn = connect_to_db(db_config)
    if not db_conn:
        logger.error("Failed to connect to PostgreSQL database")
        return

    # Load the cluster config    
    load_kubernetes_config()

    # Current date minus three years
    current_date = datetime.now()- timedelta(days=365 * 3)
    current_date_str = current_date.strftime("%Y-%m-%d")
    
    epoch = current_date + timedelta(days=1)
    epoch_str = epoch.strftime("%Y-%m-%d")

    # Get the minimum carbon emissions from the db
    try:
        min_db = fetch_min_slope(db_conn, current_date_str, epoch_str)
        logger.info(f"Minimum carbon emissions for {pod_selector} in the given time range:")
        if min_db:
            for i in range(len(min_db[0])):
                logger.info(f"Region: {min_db[0][i]}, Timestamp: {min_db[1][i]}, Intensity: {min_db[2][i]}")
        else:
            logger.info("No records found in the database for the given time range")
    except Exception as e:
        logger.info(f"Error fetching results: {e}")

    url = "http://0.0.0.0:8000/migrate"
    headers = {"Content-Type": "application/json"}
    json_body = {
        "namespace": "foo",
        "pod": "test-pod",
        "target_pod": "new-test-pod",
        "target_node": "desktop-worker2",
        "delete_original": True,
    }

    logger.info("Migrating test pod to the new node...")
    response = requests.post(url, json=json_body, headers=headers)
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Response: {response.text}")

    json_body = {
        "namespace": "foo",
        "pod": "new-test-pod",
        "target_pod": "test-pod",
        "target_node": "desktop-worker",
        "delete_original": True,
    }

    logger.info("Migrating test pod back to the original node...")
    response = requests.post(url, json=json_body, headers=headers)
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Response: {response.text}")

    time.sleep(100000)

    # while True:
        
    #     logger.info("Collecting cadvisor metrics...")
    #     cadvsisor_containers = fetch_cadvisor_metrics(session, cadvisor_url, "/", pod_selector)
    #     if cadvsisor_containers:
    #         cadvisor_data = collect_container_metrics(cadvsisor_containers)

    #     logger.info("Collecting k8s resources...")
    #     k8s_data = list_resources(pod_selector.split('=')[1], output_format="table", include_system=False)

    #     # logger.info(cadvisor_data)
    #     logger.info(k8s_data)

    #     # -----------------------------------------------
    #     # Necessary for test case: remove a delta of '3 years' from the timestamp, to match db records
    #     for resource in k8s_data:
    #         if 'age' in resource and isinstance(resource['age'], datetime):
    #             logger.info(f"{type(resource['age'])}, {resource['age']}")
    #             resource['age'] = resource['age'] - timedelta(days=365 * 3)
    #     # -----------------------------------------------

    #     # Get the minimum carbon emissions from the db
    #     try:
    #         for resource in k8s_data:
    #             start_date = datetime.fromisoformat(str(resource['age']))

    #             # Assumes `EXPECTED_DURATION` is inside each resource's 'annotations'
    #             expected_duration = int(resource.get('annotations', {}).get('EXPECTED_DURATION', 0))

    #             end_date = start_date + timedelta(hours=expected_duration)

    #             start_string = start_date.strftime("%Y-%m-%d")
    #             end_string = end_date.strftime("%Y-%m-%d")

    #             logger.info(f"Start date: {start_string}, End date: {end_string}")
    #             min_db = fetch_min_slope(db_conn, start_string, end_string)

    #             logger.info(f"Minimum carbon emissions for {resource['name']} in the given time range:")
    #             if min_db:
    #                 for i in range(len(min_db[0])):
    #                     logger.info(f"Region: {min_db[0][i]}, Timestamp: {min_db[1][i]}, Intensity: {min_db[2][i]}")
    #             else:
    #                 logger.info("No records found in the database for the given time range")

    #             # Add the minimum carbon emissions to the resource data 
    #             logger.info(f"Mininum regions for {resource['name']}: {set(min_db[0])}")

    #             min_regions = list(set(min_db[0]))

    #             if min_regions:
    #                 regions_db = fetch_region_slopes(db_conn, start_string, end_string, min_regions)
    #                 regions_data = {region: [] for region in min_regions}

    #                 logger.info(f"Minimum carbon emissions for {resource['name']} in the given time range:")
    #                 if regions_db:
    #                     for i in range(len(regions_db[0])):
    #                         regions_data[regions_db[0][i]].append([regions_db[1][i], regions_db[2][i]])

    #                     for region, values in regions_data.items():
    #                         logger.info(f"Region: {region}")
    #                         for value in values:
    #                             logger.info(f"Timestamp: {value[0]}, Intensity: {value[1]}")
    #                 else:
    #                     logger.info("No records found in the database for the given time range")

    #     except Exception as e:
    #         logger.info("No records found in the database for the given time range")

    time.sleep(interval)

if __name__ == "__main__":
    main()