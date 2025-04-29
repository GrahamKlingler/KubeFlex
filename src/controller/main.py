import requests
import json
import time
import psycopg2
import os
from datetime import datetime
import logging
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

def connect_to_db(db_params):
    """Connect to PostgreSQL database."""
    try:
        connection = psycopg2.connect(**db_params)
        logger.info("Successfully connected to PostgreSQL database")
        return connection
    except psycopg2.Error as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        raise

def min_slope(conn, start_date, end_date):

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT get_min_intensity_records(%s, %s);",
                (start_date, end_date)
            )
            result = cur.fetchone()[0]  # [0] because fetchone() returns a tuple
            # print("Fetched results array:", result)

            min_region, min_ts, min_intensity = [], [], [] 
            for record in sorted(result):

                min_region.append(record.split(" | ")[0])
                min_ts.append(record.split(" | ")[1])
                min_intensity.append(float(record.split(" | ")[2]))

            return min_region, min_ts, min_intensity

    except Exception as e:
        print(f"Error fetching results: {e}")

def get_cadvisor_url():
    return os.getenv('CADVISOR_URL', 'http://127.0.0.1:8080')

def create_cadvisor_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[600, 502, 503, 504]
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    return session

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

def main():
    cadvisor_url = get_cadvisor_url()
    # Ensure proper label format
    pod_selector = os.getenv('POD_SELECTOR', 'io.kubernetes.pod.namespace=monitor')
    interval = int(os.getenv('POLLING_INTERVAL', '300'))
    session = create_cadvisor_session()
    
    if not wait_for_cadvisor(session, cadvisor_url):
        logger.error("cAdvisor not available after timeout")
        return
    
    while True:
        containers = fetch_cadvisor_metrics(session, cadvisor_url, "/", pod_selector)
        if containers:
            data = collect_container_metrics(containers)
            for container_name, metrics in data.items():
                logger.info(f"Container: {container_name}")
                logger.info(f"CPU: {metrics['cpu']}")
                logger.info(f"Memory: {metrics['memory']}")
                logger.info(f"Network: {metrics['network']}")
                logger.info("\n")

        time.sleep(interval)

if __name__ == "__main__":
    main()